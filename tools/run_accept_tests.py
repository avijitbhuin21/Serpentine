"""Run every tests/accept/ program under CPython and require exit 0."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPT = ROOT / "tests" / "accept"


def collect() -> list[Path]:
    """Collect single-file tests and multi-module main.py entry points, sorted."""
    tests = sorted(ACCEPT.glob("*.py"))
    tests += sorted(d / "main.py" for d in ACCEPT.iterdir() if d.is_dir() and (d / "main.py").exists())
    return tests


def main() -> int:
    """Execute each accept test; report failures and return a CI exit code."""
    tests = collect()
    if len(tests) < 30:
        print(f"FAIL: expected >= 30 accept tests, found {len(tests)}")
        return 1
    failures = []
    for test in tests:
        proc = subprocess.run(
            [sys.executable, str(test)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(test.parent),
        )
        rel = test.relative_to(ROOT)
        if proc.returncode != 0:
            failures.append(rel)
            print(f"FAIL {rel} (exit {proc.returncode})")
            if proc.stderr:
                print(proc.stderr.rstrip())
        else:
            print(f"ok   {rel}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} accept tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
