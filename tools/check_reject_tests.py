"""Validate tests/reject/: parseable Python, well-formed error annotations."""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REJECT = ROOT / "tests" / "reject"

HEADER = re.compile(r"^# serp-reject: (SE\d{3}) [a-z][a-z0-9-]*$")
INLINE = re.compile(r"# E: (SE\d{3})\s*$")

KNOWN_CODES = {
    "SE001", "SE002", "SE003", "SE004", "SE005", "SE006", "SE007", "SE008",
    "SE201", "SE202", "SE203", "SE204", "SE205", "SE206", "SE207",
    "SE208", "SE209", "SE210", "SE211", "SE212", "SE213", "SE214", "SE215",
}


def check(path: Path) -> list[str]:
    """Return the list of annotation/parse problems for one reject test."""
    problems = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    m = HEADER.match(lines[0]) if lines else None
    if not m:
        problems.append("line 1 must be '# serp-reject: <CODE> <error-name>'")
        header_code = None
    else:
        header_code = m.group(1)
        if header_code not in KNOWN_CODES:
            problems.append(f"unknown error code {header_code}")
    inline_codes = [mm.group(1) for line in lines if (mm := INLINE.search(line))]
    if not inline_codes:
        problems.append("no inline '# E: <CODE>' marker on the offending line")
    elif header_code and header_code not in inline_codes:
        problems.append(f"inline markers {inline_codes} do not include header code {header_code}")
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        problems.append(f"does not parse: {exc}")
    return problems


def main() -> int:
    """Validate every reject test; report problems and return a CI exit code."""
    tests = sorted(REJECT.glob("*.py"))
    if len(tests) < 30:
        print(f"FAIL: expected >= 30 reject tests, found {len(tests)}")
        return 1
    bad = 0
    for test in tests:
        problems = check(test)
        rel = test.relative_to(ROOT)
        if problems:
            bad += 1
            print(f"FAIL {rel}")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"ok   {rel}")
    print(f"\n{len(tests) - bad}/{len(tests)} reject tests well-formed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
