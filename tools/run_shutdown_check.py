"""Graceful-shutdown check: a native Venom server must drain in-flight requests on a real signal.

For each serving mode (event loop `serve_async`, threaded `serve_on` workers) and each
backend, the server is started, /healthz is probed, a 1-second /slow request is put in
flight, and the process receives SIGTERM (POSIX) or CTRL_BREAK_EVENT (Windows). The slow
request must still get its 200, new connections must be refused or closed, and the process
must print STOPPED and exit 0 within the grace period.

Usage: python tools/run_shutdown_check.py [--backend rust|llvm|both]
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tools" / "shutdown" / "app.py"


def http_get(port: int, path: str, timeout: float = 5.0) -> bytes:
    """One GET with Connection: close; returns the raw response ('' on any socket error)."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
        out = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            out += chunk
        s.close()
        return out
    except OSError:
        return b""


def stop_signal(proc: subprocess.Popen) -> None:
    """Deliver the platform's graceful-stop signal."""
    if sys.platform == "win32":
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGTERM)


def check(exe: Path, mode: str) -> tuple[bool, str]:
    """Run one server and judge the drain; returns (ok, detail)."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen([str(exe), mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, creationflags=flags)
    try:
        port = int(proc.stdout.readline().split()[1])
        health = http_get(port, "/healthz")
        result: dict[str, bytes] = {}
        t = threading.Thread(target=lambda: result.__setitem__("slow", http_get(port, "/slow")))
        t.start()
        time.sleep(0.3)
        t0 = time.time()
        stop_signal(proc)
        t.join(timeout=15)
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            return False, "server did not exit within 15s"
        elapsed = time.time() - t0
        late = http_get(port, "/healthz", timeout=1.0)
        slow = result.get("slow", b"")
        ok = (health.startswith(b"HTTP/1.1 200") and slow.startswith(b"HTTP/1.1 200")
              and b'"done"' in slow and "STOPPED" in out and proc.returncode == 0 and late == b"")
        detail = (f"health={health[:15]!r} slow={slow[:15]!r} exit={proc.returncode} "
                  f"stopped={'STOPPED' in out} after_signal={elapsed:.2f}s late_conn_refused={late == b''}")
        if not ok and err.strip():
            detail += f"\n  stderr: {err.strip()[-800:]}"
        return ok, detail
    finally:
        if proc.poll() is None:
            proc.kill()


def main() -> int:
    """Build the app per backend and run the drain check in both serving modes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="both", choices=["rust", "llvm", "both"])
    args = ap.parse_args()
    backends = ["rust", "llvm"] if args.backend == "both" else [args.backend]
    tmp = Path(tempfile.mkdtemp(prefix="serp_shutdown_"))
    failures = 0
    for backend in backends:
        exe = tmp / (f"app_{backend}" + (".exe" if sys.platform == "win32" else ""))
        b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(APP), "-o", str(exe),
                            "--backend", backend], capture_output=True, text=True, cwd=APP.parent)
        if b.returncode != 0:
            print(f"FAIL build ({backend})\n" + (b.stderr or b.stdout)[-3000:])
            failures += 2
            continue
        for mode in ("async", "threads"):
            ok, detail = check(exe, mode)
            print(f"{'ok  ' if ok else 'FAIL'} {backend:4} {mode:7} {detail}")
            failures += 0 if ok else 1
    total = len(backends) * 2
    print(f"\n{total - failures}/{total} graceful-shutdown checks passed ({sys.platform})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
