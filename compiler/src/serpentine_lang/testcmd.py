"""The `serp test` subcommand: discover test_*.py files, build them natively,
run them, and report PASS/FAIL (a test passes when it exits 0).

Discovery: an explicit file or directory argument, else `tests/` next to
serp.toml (walking up from the current directory), else `tests/` in the
current directory. Pairs with the serp-test assertion library, but any
Serpentine program works as a test.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from .project import find_manifest


def _discover(arg: str | None) -> list[Path]:
    """Resolve the test target to a sorted list of test files."""
    if arg:
        p = Path(arg).resolve()
        if p.is_file():
            return [p]
        if p.is_dir():
            return sorted(p.rglob("test_*.py"))
        return []
    mpath = find_manifest(Path.cwd())
    base = mpath.parent if mpath else Path.cwd()
    tdir = base / "tests"
    if tdir.is_dir():
        return sorted(tdir.rglob("test_*.py"))
    return []


def cmd_test(args: argparse.Namespace) -> int:
    """serp test: build (debug, default backend) and run every discovered test."""
    from .diagnostics import Reporter, SerpError
    from .cli import run_check
    tests = _discover(args.path)
    if not tests:
        where = args.path or "tests/"
        print(f"serp: no test_*.py files found under {where}", file=sys.stderr)
        return 1
    from .llvmbuild import LLVMBuildError
    from .llvmgen import LLVMUnsupported, build_llvm_native
    out_dir = Path(tempfile.mkdtemp(prefix="serp_test_"))
    failed = []
    for test in tests:
        label = str(test.relative_to(Path.cwd())) if test.is_relative_to(Path.cwd()) else str(test)
        rep = Reporter()
        try:
            tc = run_check(test, rep)
        except SerpError:
            failed.append(label)
            print(f"FAIL {label} (check)")
            print(rep.render_all(), file=sys.stderr)
            continue
        exe = out_dir / (test.stem + (".exe" if sys.platform == "win32" else ""))
        try:
            build_llvm_native(tc, exe, debug=not args.release, debuginfo=False)
        except (LLVMUnsupported, LLVMBuildError) as exc:
            failed.append(label)
            print(f"FAIL {label} (build): {exc}")
            continue
        proc = subprocess.run([str(exe)], cwd=str(test.parent), capture_output=True)
        if proc.returncode != 0:
            failed.append(label)
            print(f"FAIL {label} (exit {proc.returncode})")
            tail = (proc.stderr or proc.stdout).decode("utf-8", errors="replace").strip()
            if tail:
                print("  " + "\n  ".join(tail.splitlines()[-10:]))
            continue
        print(f"PASS {label}")
    n = len(tests)
    print(f"\nserp: {n - len(failed)}/{n} test file(s) passed")
    return 1 if failed else 0


def register(sub) -> None:
    """Attach the test subcommand to the serp argument parser."""
    p_test = sub.add_parser("test", help="discover, build, and run test_*.py files")
    p_test.add_argument("path", nargs="?", default=None,
                        help="test file or directory (default: tests/ next to serp.toml)")
    p_test.add_argument("--release", action="store_true", help="optimized builds")
    p_test.set_defaults(func=cmd_test)
