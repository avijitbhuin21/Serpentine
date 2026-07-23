"""Library differential harness: every libs/*/tests/*.py runs under CPython
(with the library's src/ on PYTHONPATH) AND as native binaries built by both
backends; stdout and exit codes are byte-compared (SPEC 1.1).

Usage: python tools/run_lib_tests.py [--check-only] [pattern]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBS = ROOT / "libs"


def collect(pattern: str) -> list[tuple[Path, Path]]:
    """Collect (library dir, test file) pairs from libs/*/tests/*.py."""
    out = []
    for lib in sorted(LIBS.iterdir()):
        tdir = lib / "tests"
        if not tdir.is_dir():
            continue
        for test in sorted(tdir.glob("*.py")):
            if not pattern or pattern in str(test):
                out.append((lib, test))
    return out


def run(cmd: list[str], cwd: Path, extra_paths: list[Path] | None = None) -> subprocess.CompletedProcess:
    """Run a command capturing output; optionally prepend extra_paths to PYTHONPATH."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if extra_paths:
        prev = env.get("PYTHONPATH", "")
        joined = os.pathsep.join(str(p) for p in extra_paths)
        env["PYTHONPATH"] = joined + (os.pathsep + prev if prev else "")
    return subprocess.run(cmd, capture_output=True, timeout=120, cwd=str(cwd), env=env)


def main() -> int:
    """Execute the library suite and report per-test verdicts."""
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="?", default="")
    ap.add_argument("--check-only", action="store_true", help="run serp check only, skip builds")
    args = ap.parse_args()

    tests = collect(args.pattern)
    bindir = Path(tempfile.mkdtemp(prefix="serp_lib_"))
    failures = []
    for lib, test in tests:
        rel = test.relative_to(ROOT)
        src = lib / "src"
        chk = run([sys.executable, "-m", "serpentine_lang.cli", "check", str(test)], test.parent)
        if chk.returncode != 0:
            failures.append(rel)
            print(f"FAIL {rel}: serp check rejected a library test")
            print(chk.stderr.decode(errors="replace").strip()[:2000])
            continue
        if args.check_only:
            print(f"ok   {rel} (check)")
            continue
        outputs = {}
        build_failed = False
        for backend in ("rust", "llvm"):
            suffix = ".exe" if sys.platform == "win32" else ""
            exe = bindir / f"{lib.name}_{test.stem}_{backend}{suffix}"
            bld = run([sys.executable, "-m", "serpentine_lang.cli", "build", str(test),
                       "-o", str(exe), "--backend", backend, "--debug"], test.parent)
            if bld.returncode != 0:
                failures.append(rel)
                print(f"FAIL {rel}: serp build --backend {backend} failed")
                print((bld.stderr or bld.stdout).decode(errors="replace").strip()[:3000])
                build_failed = True
                break
            nat = run([str(exe)], test.parent)
            outputs[backend] = (nat.stdout.replace(b"\r\n", b"\n"), nat.returncode)
        if build_failed:
            continue
        py = run([sys.executable, str(test)], test.parent,
                 extra_paths=[src] + [d / "src" for d in sorted(LIBS.iterdir())
                                      if d != lib and (d / "src").is_dir()])
        py_out = (py.stdout.replace(b"\r\n", b"\n"), py.returncode)
        bad = [b for b in outputs if outputs[b] != py_out]
        if bad:
            failures.append(rel)
            print(f"FAIL {rel}: outputs differ (cpython exit {py_out[1]})")
            print(f"  cpython: {py_out[0][:400]!r}")
            for b in bad:
                print(f"  {b:7}: {outputs[b][0][:400]!r} (exit {outputs[b][1]})")
            continue
        print(f"ok   {rel} (cpython + rust + llvm identical, {len(py_out[0])} bytes)")

    print(f"\n{len(tests) - len(failures)}/{len(tests)} library tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
