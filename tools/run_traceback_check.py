"""Traceback harness: native binaries must report the same (line, function) frames as CPython on a crash."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "traceback" / "probe.py"
FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')


def frames(text: str) -> list[tuple[int, str]]:
    """(line, function) frames from a traceback, excluding CPython's <module> frame."""
    out = []
    for m in FRAME.finditer(text):
        if m.group("func") != "<module>" and Path(m.group("file")).name == PROBE.name:
            out.append((int(m.group("line")), m.group("func")))
    return out


def main() -> int:
    """Build the probe with each backend and compare its crash traceback with CPython's."""
    py = subprocess.run([sys.executable, str(PROBE)], capture_output=True, text=True)
    want = frames(py.stderr)
    last = py.stderr.strip().splitlines()[-1]
    print("cpython frames:", want, "|", last)
    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="serp_tb_"))
    for name, flags in (("llvm-debug", ["--backend", "llvm", "--debug"]),
                        ("llvm-release", ["--backend", "llvm"]),
                        ("rust", ["--backend", "rust"])):
        exe = tmp / (f"probe_{name}" + (".exe" if sys.platform == "win32" else ""))
        b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(PROBE), "-o", str(exe), *flags],
                           capture_output=True, text=True)
        if b.returncode != 0:
            print(f"FAIL {name}: build failed\n{(b.stderr or b.stdout)[-2000:]}")
            failures += 1
            continue
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        got = frames(r.stderr)
        tail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
        ok = (got == want and tail == last and r.returncode == 1 and r.stdout == py.stdout
              and "Traceback (most recent call last):" in r.stderr)
        print(("ok  " if ok else "FAIL"), name, got, "|", tail)
        if not ok:
            print(r.stderr)
            failures += 1
    print(f"traceback check: {3 - failures}/3 backends match CPython")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
