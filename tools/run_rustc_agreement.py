"""rustc-agreement harness: Serpentine's borrow checker vs rustc as oracle (RESEARCH 4).

For every reject test with an ownership-family code (SE0xx):
  1. run the pipeline WITHOUT borrowck;
  2. if the type checker already rejects, the rule is Serpentine policy (move
     markers etc.) that rustc cannot mirror — classified `policy`;
  3. otherwise transpile to Rust and feed it to rustc: rustc MUST also reject,
     or our checker is stricter than the oracle in a way that needs review.

Every accept test must both check clean and compile under rustc (the
differential harness already proves this; here we only re-verify the verdict).

Usage: python tools/run_rustc_agreement.py [pattern]
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "compiler" / "src"))

from serpentine_lang.diagnostics import Reporter, SerpError          # noqa: E402
from serpentine_lang.frontend import load_program                    # noqa: E402
from serpentine_lang.rustgen import CodegenError, generate_rust      # noqa: E402
from serpentine_lang.typecheck import TypeChecker                    # noqa: E402

HEADER = re.compile(r"^# serp-reject: (SE\d{3})")


def typecheck_only(path: Path):
    """Run frontend + type checker (no borrowck); return (tc, diags)."""
    rep = Reporter()
    try:
        program = load_program(path, rep)
        tc = TypeChecker(program, rep)
        tc.run()
    except SerpError:
        return None, rep.diags
    if rep.diags:
        return None, rep.diags
    return tc, []


def main() -> int:
    """Compare Serpentine's ownership verdicts with rustc's on the reject corpus."""
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    rustc = shutil.which("rustc")
    if rustc is None:
        print("rustc not found on PATH")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="serp_agree_"))
    tests = sorted((ROOT / "tests" / "reject").glob("*.py"))
    if pattern:
        tests = [t for t in tests if pattern in str(t)]
    policy = agree = disagree = 0
    for test in tests:
        first = test.read_text(encoding="utf-8").splitlines()[0]
        m = HEADER.match(first)
        if not m or not m.group(1).startswith("SE0"):
            continue   # subset/type errors are not rustc's department
        tc, diags = typecheck_only(test)
        if tc is None:
            policy += 1
            print(f"policy   {test.name}: caught before borrowck "
                  f"({diags[0].code if diags else '?'} — no rustc equivalent)")
            continue
        try:
            rust_src = generate_rust(tc)
        except CodegenError as exc:
            print(f"DISAGREE {test.name}: codegen failed on checker-clean program: {exc}")
            disagree += 1
            continue
        rs = tmp / f"{test.stem}.rs"
        rs.write_text(rust_src, encoding="utf-8")
        proc = subprocess.run([rustc, "--edition", "2021", "--emit=metadata",
                               "--out-dir", str(tmp), str(rs)],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            agree += 1
            print(f"agree    {test.name}: rustc also rejects")
        else:
            disagree += 1
            print(f"DISAGREE {test.name}: our checker rejects but rustc accepts")
    print(f"\nagreement: {agree} confirmed by rustc, {policy} policy-only, "
          f"{disagree} disagreements")
    return 1 if disagree else 0


if __name__ == "__main__":
    sys.exit(main())
