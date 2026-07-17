"""LLVM-backend differential harness: numeric-core accept tests run under CPython
AND via `serp llvm` (Backend B, JIT); stdout is byte-compared. Tests outside the
numeric core are skipped (exit code 3 from the CLI).

Usage: python tools/run_llvm_differential.py [pattern]
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPT = ROOT / "tests" / "accept"


def main() -> int:
    """Run the LLVM differential suite; at least the numeric corpus must pass."""
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    tests = sorted(ACCEPT.glob("*.py"))
    if pattern:
        tests = [t for t in tests if pattern in str(t)]
    passed = skipped = failed = 0
    for test in tests:
        rel = test.relative_to(ROOT)
        jit = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "llvm", str(test)],
                             capture_output=True, timeout=120, cwd=str(test.parent))
        if jit.returncode == 3:
            skipped += 1
            print(f"skip {rel}: outside the numeric core")
            continue
        py = subprocess.run([sys.executable, str(test)], capture_output=True,
                            timeout=120, cwd=str(test.parent))
        jit_out = jit.stdout.replace(b"\r\n", b"\n")
        py_out = py.stdout.replace(b"\r\n", b"\n")
        if jit_out != py_out or jit.returncode != py.returncode:
            failed += 1
            print(f"FAIL {rel}: outputs differ (py exit {py.returncode}, "
                  f"llvm exit {jit.returncode})")
            print(f"  cpython: {py_out[:300]!r}")
            print(f"  llvm   : {jit_out[:300]!r}")
            print(f"  stderr : {jit.stderr[:300]!r}")
            continue
        passed += 1
        print(f"ok   {rel} (LLVM JIT identical, {len(py_out)} bytes)")
    print(f"\nLLVM backend: {passed} identical, {skipped} outside core, {failed} failed")
    return 1 if failed or passed == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
