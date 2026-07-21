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


def run_check(entry: Path, rep: Reporter, dump_sir: bool = False,
              overlay: dict[str, str] | None = None):
    """Run the full static pipeline; returns the TypeChecker on success."""
    program = load_program(entry, rep, overlay)
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
    """serp build: check, then compile natively (Rust backend or direct LLVM)."""
    rep = Reporter()
    try:
        tc = run_check(Path(args.file), rep)
    except SerpError:
        print(rep.render_all(), file=sys.stderr)
        return 1

    entry = Path(args.file).resolve()
    out = Path(args.output) if args.output else entry.with_suffix("")
    if sys.platform == "win32" and out.suffix != ".exe":
        out = out.with_suffix(".exe")

    if args.backend == "llvm":
        from .llvmbuild import LLVMBuildError
        from .llvmgen import LLVMUnsupported, build_llvm_native
        try:
            build_llvm_native(tc, out, debug=args.debug, debuginfo=args.debuginfo)
        except LLVMUnsupported as exc:
            print(f"serp: internal LLVM codegen error: {exc}", file=sys.stderr)
            return 2
        except LLVMBuildError as exc:
            print(f"serp: {exc}", file=sys.stderr)
            return 2
        print(f"serp: built {out} (llvm backend)")
        return 0

    try:
        rust_src = generate_rust(tc)
    except CodegenError as exc:
        print(f"serp: internal codegen error: {exc}", file=sys.stderr)
        return 2

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
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print("serp: rustc rejected the generated program (checker/oracle disagreement):",
              file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return 2
    print(f"serp: built {out}")
    return 0


def cmd_llvm(args: argparse.Namespace) -> int:
    """serp llvm: check, build via Backend B (LLVM), run — or dump the IR."""
    from .llvmbuild import LLVMBuildError
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
        return run_llvm(tc, debug=not args.release)
    except LLVMUnsupported as exc:
        print(f"serp: program is outside the LLVM backend's coverage ({exc}) — "
              f"use `serp build` (Rust backend)", file=sys.stderr)
        return 3
    except LLVMBuildError as exc:
        print(f"serp: {exc}", file=sys.stderr)
        return 2


def cmd_lsp(args: argparse.Namespace) -> int:
    """serp lsp: run the Language Server Protocol server on stdio."""
    from .lsp import serve_stdio
    return serve_stdio()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="serp", description="Serpentine compiler")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="type- and borrow-check a program")
    p_check.add_argument("file")
    p_check.add_argument("--dump-sir", action="store_true", help="print the SIR after checking")
    p_check.set_defaults(func=cmd_check)

    p_build = sub.add_parser("build", help="compile to a native binary")
    p_build.add_argument("file")
    p_build.add_argument("-o", "--output", default=None)
    p_build.add_argument("--backend", choices=["rust", "llvm"], default="rust",
                         help="code generator: rust (default, oracle-checked) or llvm (direct)")
    p_build.add_argument("--keep-rust", action="store_true", help="write the generated .rs next to the source")
    p_build.add_argument("--debug", action="store_true", help="fast unoptimized build")
    p_build.add_argument("--debuginfo", action="store_true",
                         help="emit source-line debug info (PDB/DWARF) — llvm backend")
    p_build.set_defaults(func=cmd_build)

    p_llvm = sub.add_parser("llvm", help="build via the LLVM backend and run")
    p_llvm.add_argument("file")
    p_llvm.add_argument("--emit-ir", action="store_true", help="print LLVM IR instead of running")
    p_llvm.add_argument("--release", action="store_true",
                        help="full optimization pipeline (default: fast debug build)")
    p_llvm.set_defaults(func=cmd_llvm)

    p_lsp = sub.add_parser("lsp", help="run the LSP server on stdio (editor diagnostics)")
    p_lsp.set_defaults(func=cmd_lsp)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
