"""The serp CLI: check and build subcommands."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .borrowck import check_program
from .diagnostics import Reporter, SerpError
from .frontend import load_program
from .rustgen import CodegenError, generate_rust
from .sir import lower_program
from .typecheck import TypeChecker


def run_check(entry: Path, rep: Reporter, dump_sir: bool = False):
    """Run the full static pipeline; returns the TypeChecker on success."""
    program = load_program(entry, rep)
    tc = TypeChecker(program, rep)
    tc.run()
    sirs = lower_program(tc)
    files = {m.name: str(m.path) for m in program.modules.values()}
    check_program(sirs, rep, files)
    if rep.diags:
        raise SerpError(rep.diags)
    if dump_sir:
        for sir in sirs.values():
            print(sir.dump())
    return tc


def cmd_check(args: argparse.Namespace) -> int:
    """serp check: report diagnostics, exit 0/1."""
    rep = Reporter()
    try:
        run_check(Path(args.file), rep, dump_sir=args.dump_sir)
    except SerpError:
        print(rep.render_all(), file=sys.stderr)
        n = len({(d.code, d.span.line, d.span.col) for d in rep.diags})
        print(f"\nserp: {n} error(s)", file=sys.stderr)
        return 1
    print(f"serp: OK ({args.file})")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """serp build: check, transpile to Rust, invoke rustc."""
    rep = Reporter()
    try:
        tc = run_check(Path(args.file), rep)
    except SerpError:
        print(rep.render_all(), file=sys.stderr)
        return 1
    try:
        rust_src = generate_rust(tc)
    except CodegenError as exc:
        print(f"serp: internal codegen error: {exc}", file=sys.stderr)
        return 2

    entry = Path(args.file).resolve()
    out = Path(args.output) if args.output else entry.with_suffix("")
    if sys.platform == "win32" and out.suffix != ".exe":
        out = out.with_suffix(".exe")

    rustc = shutil.which("rustc")
    if rustc is None:
        print("serp: rustc not found on PATH — install Rust to use `serp build`", file=sys.stderr)
        return 2

    rs_dir = Path(tempfile.mkdtemp(prefix="serp_build_"))
    rs_file = rs_dir / f"{entry.stem}.rs"
    rs_file.write_text(rust_src, encoding="utf-8")
    if args.keep_rust:
        keep = entry.with_suffix(".rs")
        keep.write_text(rust_src, encoding="utf-8")
        print(f"serp: rust source kept at {keep}")

    opt = "0" if args.debug else "2"
    proc = subprocess.run(
        [rustc, "--edition", "2021", "-C", f"opt-level={opt}", "-o", str(out), str(rs_file)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print("serp: rustc rejected the generated program (checker/oracle disagreement):",
              file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return 2
    print(f"serp: built {out}")
    return 0


def cmd_llvm(args: argparse.Namespace) -> int:
    """serp llvm: check, lower to LLVM IR (Backend B numeric core), JIT-run or dump IR."""
    from .llvmgen import LLVMUnsupported, generate_llvm, run_llvm
    rep = Reporter()
    try:
        tc = run_check(Path(args.file), rep)
    except SerpError:
        print(rep.render_all(), file=sys.stderr)
        return 1
    try:
        if args.emit_ir:
            print(generate_llvm(tc))
            return 0
        return run_llvm(tc)
    except LLVMUnsupported as exc:
        print(f"serp: program is outside the LLVM numeric core ({exc}) — "
              f"use `serp build` (Rust backend)", file=sys.stderr)
        return 3


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="serp", description="Serpentine compiler")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="type- and borrow-check a program")
    p_check.add_argument("file")
    p_check.add_argument("--dump-sir", action="store_true", help="print the SIR after checking")
    p_check.set_defaults(func=cmd_check)

    p_build = sub.add_parser("build", help="compile to a native binary via Rust")
    p_build.add_argument("file")
    p_build.add_argument("-o", "--output", default=None)
    p_build.add_argument("--keep-rust", action="store_true", help="write the generated .rs next to the source")
    p_build.add_argument("--debug", action="store_true", help="opt-level=0 for faster builds")
    p_build.set_defaults(func=cmd_build)

    p_llvm = sub.add_parser("llvm", help="run via the LLVM backend (numeric core, JIT)")
    p_llvm.add_argument("file")
    p_llvm.add_argument("--emit-ir", action="store_true", help="print LLVM IR instead of running")
    p_llvm.set_defaults(func=cmd_llvm)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
