"""Project management commands: serp init/new/run (scaffolding + project-aware run).

`serp init` scaffolds a Serpentine project: serp.toml, main.py, .gitignore, a
virtual environment with the shim installed (uv when available, stdlib venv +
pip otherwise), and optionally a git repository. `serp new` does the same in a
fresh directory. `serp run` builds the project entry to a temporary binary via
the default backend (debug mode) and runs it, forwarding arguments.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .project import find_manifest

MAIN_TEMPLATE = '''\
"""{name} — a Serpentine program: runs under CPython, compiles to a native binary."""


def main() -> None:
    print("Hello from {name}!")


if __name__ == "__main__":
    main()
'''

MANIFEST_TEMPLATE = """\
[project]
name = "{name}"
version = "0.1.0"

[dependencies]
"""

GITIGNORE_TEMPLATE = """\
.venv/
__pycache__/
*.exe
*.pdb
"""


def _project_name(raw: str) -> str:
    """Derive a valid project/module name from a directory name."""
    name = re.sub(r"[^0-9A-Za-z_]", "_", raw.strip().lower().replace("-", "_"))
    if not name or name[0].isdigit():
        name = "app_" + name
    return name


def _venv_python(venv: Path) -> Path:
    """Path to the venv's python executable on this platform."""
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _run(cmd: list[str], cwd: Path) -> bool:
    """Run a tool quietly; report stderr and return False on failure."""
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(f"serp: `{' '.join(cmd)}` failed:\n{proc.stderr.strip()}", file=sys.stderr)
        return False
    return True


def _create_venv(root: Path) -> bool:
    """Create .venv and install the shim, preferring uv over stdlib venv + pip."""
    venv = root / ".venv"
    uv = shutil.which("uv")
    if uv is not None:
        if not _run([uv, "venv", str(venv)], root):
            return False
        py = _venv_python(venv)
        return _run([uv, "pip", "install", "--python", str(py), "serpentine-shim"], root)
    if not _run([sys.executable, "-m", "venv", str(venv)], root):
        return False
    py = _venv_python(venv)
    return _run([str(py), "-m", "pip", "install", "--quiet", "serpentine-shim"], root)


def _scaffold(root: Path, name: str, git: bool, no_venv: bool) -> int:
    """Write the project skeleton into root; returns a process exit code."""
    manifest = root / "serp.toml"
    if manifest.exists():
        print(f"serp: {manifest} already exists — refusing to overwrite", file=sys.stderr)
        return 1
    root.mkdir(parents=True, exist_ok=True)
    manifest.write_text(MANIFEST_TEMPLATE.format(name=name), encoding="utf-8")
    main_py = root / "main.py"
    if not main_py.exists():
        main_py.write_text(MAIN_TEMPLATE.format(name=name), encoding="utf-8")
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
    print(f"serp: created project '{name}' at {root}")
    if not no_venv:
        if _create_venv(root):
            print("serp: created .venv with serpentine-shim installed")
        else:
            print("serp: venv setup failed — create one manually and "
                  "`pip install serpentine-shim`", file=sys.stderr)
    if git and not (root / ".git").exists():
        if shutil.which("git") is None:
            print("serp: git not found on PATH — skipped `git init`", file=sys.stderr)
        elif _run(["git", "init"], root):
            print("serp: initialized git repository")
    print(f"serp: get started with `serp run` (or `python main.py`) in {root}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """serp init: scaffold a Serpentine project in the current (or given) directory."""
    root = Path(args.path).resolve()
    name = _project_name(args.name or root.name)
    return _scaffold(root, name, git=args.git, no_venv=args.no_venv)


def cmd_new(args: argparse.Namespace) -> int:
    """serp new: scaffold a Serpentine project in a fresh directory."""
    root = (Path.cwd() / args.name).resolve()
    if root.exists() and any(root.iterdir()):
        print(f"serp: directory {root} already exists and is not empty", file=sys.stderr)
        return 1
    name = _project_name(args.name)
    return _scaffold(root, name, git=args.git, no_venv=args.no_venv)


def cmd_run(args: argparse.Namespace) -> int:
    """serp run: build the project entry (debug, default backend) and run it."""
    from .diagnostics import Reporter, SerpError
    from .cli import run_check
    if args.file:
        entry = Path(args.file).resolve()
    else:
        mpath = find_manifest(Path.cwd())
        base = mpath.parent if mpath else Path.cwd()
        entry = base / "main.py"
    if not entry.is_file():
        print(f"serp: no entry file found ({entry}) — pass one explicitly: "
              f"`serp run path/to/file.py`", file=sys.stderr)
        return 1
    rep = Reporter()
    try:
        tc = run_check(entry, rep)
    except SerpError:
        print(rep.render_all(), file=sys.stderr)
        return 1
    from .llvmbuild import LLVMBuildError, llvmlite_missing
    missing = llvmlite_missing()
    if missing:
        print(missing, file=sys.stderr)
        return 2
    from .llvmgen import LLVMUnsupported, build_llvm_native
    out_dir = Path(tempfile.mkdtemp(prefix="serp_run_"))
    out = out_dir / (entry.stem + (".exe" if sys.platform == "win32" else ""))
    try:
        build_llvm_native(tc, out, debug=not args.release, debuginfo=False)
    except LLVMUnsupported as exc:
        print(f"serp: internal LLVM codegen error: {exc}", file=sys.stderr)
        return 2
    except LLVMBuildError as exc:
        print(f"serp: {exc}", file=sys.stderr)
        return 2
    proc = subprocess.run([str(out), *args.args])
    return proc.returncode


def register(sub) -> None:
    """Attach the project-management subcommands to the serp argument parser."""
    p_init = sub.add_parser("init", help="scaffold a Serpentine project in this directory")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.add_argument("--name", default=None, help="project name (default: directory name)")
    p_init.add_argument("--git", action="store_true", help="also initialize a git repository")
    p_init.add_argument("--no-venv", action="store_true", help="skip venv creation")
    p_init.set_defaults(func=cmd_init)

    p_new = sub.add_parser("new", help="scaffold a Serpentine project in a new directory")
    p_new.add_argument("name")
    p_new.add_argument("--git", action="store_true", help="also initialize a git repository")
    p_new.add_argument("--no-venv", action="store_true", help="skip venv creation")
    p_new.set_defaults(func=cmd_new)

    p_run = sub.add_parser("run", help="build (debug) and run the project entry")
    p_run.add_argument("file", nargs="?", default=None,
                       help="entry file (default: main.py next to serp.toml)")
    p_run.add_argument("--release", action="store_true", help="optimized build")
    p_run.add_argument("args", nargs=argparse.REMAINDER,
                       help="arguments forwarded to the program")
    p_run.set_defaults(func=cmd_run)
