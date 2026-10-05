"""Run Backend-A output for FFI-free accept tests under Miri (UB detector for the prelude's unsafe code).

Usage: python tools/run_miri.py [test-substring ...]
Requires: rustup nightly with the miri + rust-src components.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ROOT / "tests" / "accept"
DEFAULT = ["007_str_methods", "009_list_basics", "016_dict_basics", "020_nested_list", "037_dataclass_basics",
           "041_shared_weak", "047_shared_node_graph", "050_tier2_strings", "051_comprehensions", "057_elem_borrow",
           "062_operator_overloading", "063_bytes", "067_pyval", "082_sets", "086_unions", "100_tuple_slice_keys",
           "104_continue_in_except", "105_finally_loop_jumps", "106_try_assigned_locals"]


def main() -> int:
    """Emit Rust for each test, run it under Miri, and compare stdout with CPython."""
    picks = sys.argv[1:] or DEFAULT
    tmp = Path(tempfile.mkdtemp(prefix="serp_miri_"))
    proj = tmp / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "Cargo.toml").write_text('[package]\nname = "p"\nversion = "0.0.0"\nedition = "2021"\n\n[dependencies]\n',
                                     encoding="utf-8")
    env = dict(os.environ)
    env["MIRIFLAGS"] = "-Zmiri-disable-isolation"
    failures = 0
    for name in picks:
        src = ACCEPT / f"{name}.py"
        work = tmp / name
        work.mkdir()
        shutil.copy(src, work / src.name)
        b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(work / src.name), "-o",
                            str(work / "a.exe"), "--backend", "rust", "--debug", "--keep-rust"],
                           capture_output=True, text=True, cwd=work)
        rs = work / f"{name}.rs"
        if b.returncode != 0 or not rs.exists():
            print(f"FAIL {name}: rust emission failed {(b.stderr or b.stdout)[-800:]}")
            failures += 1
            continue
        shutil.copy(rs, proj / "src" / "main.rs")
        py = subprocess.run([sys.executable, str(src)], capture_output=True, text=True, cwd=work,
                            encoding="utf-8", env={**env, "PYTHONIOENCODING": "utf-8"})
        m = subprocess.run(["cargo", "+nightly", "miri", "run", "-q"], capture_output=True, text=True,
                           cwd=proj, env=env, timeout=1800, encoding="utf-8", errors="replace")
        ub = "Undefined Behavior" in m.stderr or "error: unsupported operation" in m.stderr
        same = m.stdout.replace("\r\n", "\n") == py.stdout.replace("\r\n", "\n")
        if m.returncode != py.returncode or not same or ub:
            failures += 1
            print(f"FAIL {name}: exit {m.returncode} (cpython {py.returncode}) same_stdout={same} ub={ub}")
            a = py.stdout.replace("\r\n", "\n").splitlines()
            c = m.stdout.replace("\r\n", "\n").splitlines()
            for k in range(max(len(a), len(c))):
                pa = a[k] if k < len(a) else "<none>"
                pc = c[k] if k < len(c) else "<none>"
                if pa != pc:
                    print(f"   first diff line {k}: cpython={pa!r} miri={pc!r}")
                    break
            print("   " + m.stderr.strip()[-1500:].replace("\n", "\n   "))
        else:
            print(f"ok   {name} (miri clean, stdout identical)")
    print(f"miri: {len(picks) - failures}/{len(picks)} clean")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
