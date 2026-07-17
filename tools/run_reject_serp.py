"""Run serp check on every tests/reject/ program and compare the emitted error
code against the file's `# serp-reject: <CODE>` annotation.

Full catch-rate is the Phase-2 milestone; this tool records the current state.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REJECT = ROOT / "tests" / "reject"
HEADER = re.compile(r"^# serp-reject: (SE\d{3})")


def main() -> int:
    """Report per-test verdicts: caught-right, caught-wrong-code, or missed."""
    right = wrong = missed = 0
    for test in sorted(REJECT.glob("*.py")):
        expected = HEADER.match(test.read_text(encoding="utf-8"))
        assert expected is not None
        code = expected.group(1)
        proc = subprocess.run(
            [sys.executable, "-m", "serpentine_lang.cli", "check", str(test)],
            capture_output=True, text=True, timeout=60, cwd=str(test.parent),
        )
        rel = test.relative_to(ROOT)
        if proc.returncode == 0:
            missed += 1
            print(f"MISS  {rel}: accepted (expected {code})")
        elif f"error[{code}]" in proc.stderr:
            right += 1
            print(f"ok    {rel}: rejected with {code}")
        else:
            wrong += 1
            got = re.findall(r"error\[(SE\d{3})\]", proc.stderr)
            print(f"WRONG {rel}: expected {code}, got {sorted(set(got))}")
    total = right + wrong + missed
    print(f"\ncaught with correct code: {right}/{total}  "
          f"(wrong code: {wrong}, missed: {missed})")
    return 0 if missed == 0 and wrong == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
