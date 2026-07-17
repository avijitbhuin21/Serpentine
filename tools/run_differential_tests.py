"""Differential harness: every accept test runs under CPython AND as a native
binary built by `serp build`; stdout and exit codes are byte-compared (SPEC 1.1).

Usage: python tools/run_differential_tests.py [--check-only] [pattern]
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPT = ROOT / "tests" / "accept"


def collect(pattern: str) -> list[Path]:
    """Collect accept-test entry points, single-file and multi-module."""
    tests = sorted(ACCEPT.glob("*.py"))
    tests += sorted(d / "main.py" for d in ACCEPT.iterdir() if d.is_dir() and (d / "main.py").exists())
    if pattern:
        tests = [t for t in tests if pattern in str(t)]
    return tests


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a command capturing output with a timeout."""
    return subprocess.run(cmd, capture_output=True, timeout=120, cwd=str(cwd))


def main() -> int:
    """Execute the differential suite and report per-test verdicts."""
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="?", default="")
    ap.add_argument("--check-only", action="store_true", help="run serp check only, skip builds")
    args = ap.parse_args()

    tests = collect(args.pattern)
    bindir = Path(tempfile.mkdtemp(prefix="serp_diff_"))
    failures = []
    for test in tests:
        rel = test.relative_to(ROOT)
        chk = run([sys.executable, "-m", "serpentine_lang.cli", "check", str(test)], test.parent)
        if chk.returncode != 0:
            failures.append(rel)
            print(f"FAIL {rel}: serp check rejected an accept test")
            print(chk.stderr.decode(errors="replace").strip()[:2000])
            continue
        if args.check_only:
            print(f"ok   {rel} (check)")
            continue
        exe = bindir / (test.parent.name + "_" + test.stem + (".exe" if sys.platform == "win32" else ""))
        bld = run([sys.executable, "-m", "serpentine_lang.cli", "build", str(test),
                   "-o", str(exe), "--debug"], test.parent)
        if bld.returncode != 0:
            failures.append(rel)
            print(f"FAIL {rel}: serp build failed")
            print((bld.stderr or bld.stdout).decode(errors="replace").strip()[:3000])
            continue
        py = run([sys.executable, str(test)], test.parent)
        nat = run([str(exe)], test.parent)
        py_out = py.stdout.replace(b"\r\n", b"\n")
        nat_out = nat.stdout.replace(b"\r\n", b"\n")
        if py_out != nat_out or py.returncode != nat.returncode:
            failures.append(rel)
            print(f"FAIL {rel}: outputs differ (py exit {py.returncode}, native exit {nat.returncode})")
            print(f"  cpython: {py_out[:400]!r}")
            print(f"  native : {nat_out[:400]!r}")
            continue
        print(f"ok   {rel} (dual-run identical, {len(py_out)} bytes)")

    print(f"\n{len(tests) - len(failures)}/{len(tests)} differential tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
