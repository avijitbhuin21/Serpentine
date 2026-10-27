"""HTTP request-parser fuzzer: a native Venom server must survive arbitrary request bytes.

Builds tools/shutdown/app.py (Venom with /healthz) per backend and serving mode,
then throws mutated and malformed requests at it: broken request lines, garbage
and NUL bytes, oversized/duplicate/negative/non-numeric Content-Length, header
floods, truncated bodies, pipelined requests, random binary. Every reply must be
a well-formed `HTTP/1.1 <3 digits>` status line or a closed connection, the
process must stay alive, and /healthz must keep answering 200 between batches.

Usage: python tools/run_http_fuzz.py [--seed N] [--count N] [--backend rust|llvm|both]
"""
import argparse
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tools" / "shutdown" / "app.py"
STATUS = re.compile(rb"^HTTP/1\.1 \d{3} ")

BASE = [b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n",
        b"POST /healthz HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 13\r\n\r\n{\"a\": [1, 2]}",
        b"GET /healthz?x=1&y=%zz&z=%E2%82 HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n",
        b"DELETE /nope/../../etc HTTP/1.0\r\n\r\n"]
PIECES = [b"\r\n", b"\n", b"\r", b"\x00", b" ", b":", b"\xff\xfe", b"%", b"?", b"#", b"HTTP/9.9",
          b"Content-Length: -1\r\n", b"Content-Length: 99999999999999999999\r\n",
          b"Content-Length: abc\r\n", b"Content-Length: 5\r\nContent-Length: 7\r\n",
          b"Transfer-Encoding: chunked\r\n", b"Connection: close\r\n", b"Host:\r\n",
          b"X: " + b"a" * 70000 + b"\r\n", b"\xe2\x82\xac", b"GET", b"/" * 3000]


def mutate(rng: random.Random) -> bytes:
    """One fuzzed request payload."""
    r = rng.random()
    if r < 0.1:
        return bytes(rng.randrange(256) for _ in range(rng.randint(0, 2000)))
    if r < 0.2:
        return rng.choice(BASE) * rng.randint(2, 6)
    data = bytearray(rng.choice(BASE))
    for _ in range(rng.randint(1, 6)):
        op = rng.randrange(5)
        k = rng.randrange(len(data) + 1)
        if op == 0:
            data[k:k] = rng.choice(PIECES)
        elif op == 1 and data:
            del data[k:k + rng.randint(1, 20)]
        elif op == 2 and data:
            data[min(k, len(data) - 1)] = rng.randrange(256)
        elif op == 3:
            data = data[:k]
        else:
            h = rng.choice(PIECES)
            sep = data.find(b"\r\n")
            data[sep + 2 if sep >= 0 else 0:sep + 2 if sep >= 0 else 0] = h
    return bytes(data)


def send(port: int, payload: bytes) -> tuple[bool, bytes]:
    """Send one payload; (connected, first bytes of the reply) — b'' when closed without a reply."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=3)
    except OSError:
        return False, b""
    out = b""
    try:
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)
        while len(out) < 64:
            chunk = s.recv(4096)
            if not chunk:
                break
            out += chunk
    except OSError:
        pass
    finally:
        s.close()
    return True, out


def healthy(port: int) -> bool:
    """The server still answers /healthz with 200."""
    ok, resp = send(port, b"GET /healthz HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    return ok and resp.startswith(b"HTTP/1.1 200")


def fuzz_one(exe: Path, mode: str, seed: int, count: int) -> tuple[bool, str]:
    """Fuzz one server process; returns (ok, summary)."""
    proc = subprocess.Popen([str(exe), mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port = int(proc.stdout.readline().split()[1])
        rng = random.Random(seed)
        bad_replies = 0
        closed = 0
        statuses: dict[bytes, int] = {}
        for i in range(count):
            ok, resp = send(port, mutate(rng))
            if proc.poll() is not None:
                return False, f"server died after {i + 1} cases (exit {proc.returncode}): {proc.stderr.read()[-800:]}"
            if not ok:
                return False, f"connection refused after {i + 1} cases"
            if resp == b"":
                closed += 1
            elif STATUS.match(resp):
                code = resp[9:12]
                statuses[code] = statuses.get(code, 0) + 1
            else:
                bad_replies += 1
            if i % 100 == 99 and not healthy(port):
                return False, f"/healthz failed after {i + 1} cases"
        alive = proc.poll() is None and healthy(port)
        summary = (f"{count} cases: statuses {dict(sorted((k.decode(), v) for k, v in statuses.items()))}, "
                   f"{closed} closed, {bad_replies} malformed replies, alive={alive}")
        return alive and bad_replies == 0, summary
    finally:
        proc.kill()
        proc.wait(timeout=10)


def main() -> int:
    """Build per backend and fuzz both serving modes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=1500)
    ap.add_argument("--backend", default="both", choices=["rust", "llvm", "both"])
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="serp_httpfuzz_"))
    failures = 0
    runs = 0
    for backend in (["rust", "llvm"] if args.backend == "both" else [args.backend]):
        exe = tmp / (f"app_{backend}" + (".exe" if sys.platform == "win32" else ""))
        b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(APP), "-o", str(exe),
                            "--backend", backend], capture_output=True, text=True, cwd=APP.parent)
        if b.returncode != 0:
            print(f"FAIL build ({backend})\n" + (b.stderr or b.stdout)[-3000:])
            failures += 2
            runs += 2
            continue
        for mode in ("async", "threads"):
            t0 = time.time()
            ok, summary = fuzz_one(exe, mode, args.seed, args.count)
            runs += 1
            failures += 0 if ok else 1
            print(f"{'ok  ' if ok else 'FAIL'} {backend:4} {mode:7} {summary} ({time.time() - t0:.0f}s)")
    print(f"\n{runs - failures}/{runs} HTTP fuzz runs passed (seed {args.seed})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
