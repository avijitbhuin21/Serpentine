"""LLVM-backend differential harness (Phase 5.3): EVERY accept test is compiled
natively via Backend B (`serp llvm` = check -> LLVM object -> link) and executed;
stdout and exit code are byte-compared against CPython. Same bar as Backend A.

Usage: python tools/run_llvm_differential.py [pattern]
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPT = ROOT / "tests" / "accept"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def main() -> int:
    """Run the LLVM differential suite over the entire accept corpus."""
    args = [a for a in sys.argv[1:] if a != "--release"]
    release = "--release" in sys.argv[1:]
    pattern = args[0] if args else ""
    extra = ["--release"] if release else []
    tests = sorted(ACCEPT.glob("*.py"))
    tests += sorted(d / "main.py" for d in ACCEPT.iterdir() if d.is_dir() and (d / "main.py").exists())
    if pattern:
        tests = [t for t in tests if pattern in str(t)]
    passed = failed = 0
    for test in tests:
        rel = test.relative_to(ROOT)
        native = subprocess.run(
            [sys.executable, "-m", "serpentine_lang.cli", "llvm", str(test)] + extra,
            capture_output=True, timeout=300, cwd=str(test.parent), env=ENV)
        py = subprocess.run([sys.executable, str(test)], capture_output=True,
                            timeout=120, cwd=str(test.parent), env=ENV)
        n_out = native.stdout.replace(b"\r\n", b"\n")
        py_out = py.stdout.replace(b"\r\n", b"\n")
        if n_out != py_out or native.returncode != py.returncode:
            failed += 1
            print(f"FAIL {rel}: outputs differ (py exit {py.returncode}, "
                  f"llvm exit {native.returncode})")
            print(f"  cpython: {py_out[:300]!r}")
            print(f"  llvm   : {n_out[:300]!r}")
            print(f"  stderr : {native.stderr[-400:]!r}")
            continue
        passed += 1
        print(f"ok   {rel} (LLVM native identical, {len(py_out)} bytes)")
    print(f"\nLLVM backend: {passed} identical, {failed} failed")
    return 1 if failed or passed == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
