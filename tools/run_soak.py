"""Bounded soak test: native Venom server under steady keep-alive load; RSS and handle count must plateau.

Usage: python tools/run_soak.py [--seconds 600] [--clients 8] [--workers 3]
"""
import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tools" / "soak" / "app.py"


def sample(pid: int) -> tuple[float, int]:
    """(RSS in MiB, open handle/fd count) of a process."""
    if sys.platform == "win32":
        k32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")

        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        h = k32.OpenProcess(0x0400 | 0x0010, False, pid)
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        count = ctypes.c_ulong()
        k32.GetProcessHandleCount(h, ctypes.byref(count))
        k32.CloseHandle(h)
        return pmc.WorkingSetSize / 2**20, count.value
    rss = 0.0
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            rss = int(line.split()[1]) / 1024
    return rss, len(os.listdir(f"/proc/{pid}/fd"))


def client(port: int, stop: threading.Event, counts: list[int], idx: int) -> None:
    """Keep-alive loop over the app's routes; reconnects on any error."""
    body = json.dumps({"k": "v" * 200, "xs": list(range(50))}).encode()
    reqs = [b"GET /json HTTP/1.1\r\nHost: x\r\n\r\n",
            b"GET /items/abc123 HTTP/1.1\r\nHost: x\r\n\r\n",
            b"GET /kb HTTP/1.1\r\nHost: x\r\n\r\n",
            b"POST /echo HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode() + b"\r\n\r\n" + body]
    n = 0
    while not stop.is_set():
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            f = s.makefile("rb")
            for _ in range(200):
                if stop.is_set():
                    break
                s.sendall(reqs[n % len(reqs)])
                clen = 0
                while True:
                    line = f.readline()
                    if not line:
                        raise ConnectionError("closed")
                    if line.lower().startswith(b"content-length:"):
                        clen = int(line.split(b":")[1])
                    if line in (b"\r\n", b"\n"):
                        break
                f.read(clen)
                n += 1
                counts[idx] = n
            s.close()
        except OSError:
            time.sleep(0.05)


def main() -> int:
    """Build, serve, load, sample, and judge growth after warm-up."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=600)
    ap.add_argument("--clients", type=int, default=8)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    exe = Path(tempfile.mkdtemp(prefix="serp_soak_")) / ("app" + (".exe" if sys.platform == "win32" else ""))
    b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(APP), "-o", str(exe)],
                       capture_output=True, text=True, cwd=APP.parent)
    if b.returncode != 0:
        print("FAIL build\n" + (b.stderr or b.stdout)[-3000:])
        return 1
    srv = subprocess.Popen([str(exe), "0", str(args.workers)], stdout=subprocess.PIPE, text=True)
    port = int(srv.stdout.readline().split()[1])
    stop = threading.Event()
    counts = [0] * args.clients
    threads = [threading.Thread(target=client, args=(port, stop, counts, i), daemon=True)
               for i in range(args.clients)]
    for t in threads:
        t.start()
    samples = []
    t0 = time.time()
    while time.time() - t0 < args.seconds:
        time.sleep(15)
        if srv.poll() is not None:
            print(f"FAIL server exited early with {srv.returncode}")
            stop.set()
            return 1
        rss, handles = sample(srv.pid)
        samples.append((time.time() - t0, rss, handles, sum(counts)))
        print(f"t={samples[-1][0]:6.0f}s rss={rss:7.1f}MiB handles={handles:5d} requests={sum(counts)}")
    stop.set()
    time.sleep(1)
    srv.kill()
    srv.wait(timeout=30)
    released = False
    for _ in range(20):
        try:
            probe = socket.socket()
            probe.bind(("127.0.0.1", port))
            probe.close()
            released = True
            break
        except OSError:
            time.sleep(0.5)
    print(f"after termination: exit={srv.returncode}, port {port} released={released}")
    warm = [s for s in samples if s[0] >= min(120, args.seconds / 3)]
    first, last = warm[0], warm[-1]
    rss_growth = last[1] - first[1]
    handle_growth = last[2] - first[2]
    rps = (last[3] - samples[0][3]) / max(1.0, last[0] - samples[0][0])
    ok = rss_growth < max(8.0, 0.1 * first[1]) and handle_growth < 32 and last[3] > 0
    print(f"soak ({sys.platform}, {args.seconds}s, {args.clients} clients, {args.workers} workers): "
          f"{last[3]} requests (~{rps:.0f} rps); after warm-up RSS {first[1]:.1f}->{last[1]:.1f} MiB "
          f"({rss_growth:+.1f}), handles {first[2]}->{last[2]} ({handle_growth:+d}) -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
