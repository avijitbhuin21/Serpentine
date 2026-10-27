"""Run the accept corpus through Backend A built with AddressSanitizer (nightly rustc).

Usage: python tools/run_asan.py [test-substring ...]
Requires: rustup nightly. On Windows the MSVC ASan runtime DLL is located automatically.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ROOT / "tests" / "accept"


def asan_env() -> dict:
    """Environment for nightly + ASan builds (and the runtime DLL path on Windows)."""
    env = dict(os.environ)
    env["RUSTUP_TOOLCHAIN"] = "nightly"
    env["SERP_RUSTC_FLAGS"] = "-Zsanitizer=address -Cdebuginfo=1"
    env["PYTHONIOENCODING"] = "utf-8"
    if sys.platform == "win32":
        for base in (Path(r"C:\Program Files\Microsoft Visual Studio"),
                     Path(r"C:\Program Files (x86)\Microsoft Visual Studio")):
            hits = sorted(base.glob("*/*/VC/Tools/MSVC/*/bin/Hostx64/x64/clang_rt.asan_dynamic-x86_64.dll"))
            if hits:
                env["PATH"] = str(hits[-1].parent) + os.pathsep + env["PATH"]
                break
    else:
        env["ASAN_OPTIONS"] = "detect_leaks=0"
    return env


def main() -> int:
    """Build + run each selected accept test under ASan and compare with CPython.

    `--backend llvm` sanitizes Backend B: the Rust runtime (all `unsafe` code) and the
    stub are ASan-instrumented; the LLVM-emitted program code itself is not
    (llvmlite has no sanitizer passes), so this covers runtime memory errors only."""
    args = sys.argv[1:]
    backend = "rust"
    if "--backend" in args:
        i = args.index("--backend")
        backend = args[i + 1]
        del args[i:i + 2]
    picks = args
    tests = [p for p in sorted(ACCEPT.glob("*.py")) if not picks or any(s in p.name for s in picks)]
    env = asan_env()
    tmp = Path(tempfile.mkdtemp(prefix="serp_asan_"))
    failures = 0
    for src in tests:
        exe = tmp / (src.stem + (".exe" if sys.platform == "win32" else ""))
        b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(src), "-o", str(exe),
                            "--backend", backend, "--debug"], capture_output=True, text=True, cwd=ACCEPT, env=env)
        if b.returncode != 0:
            failures += 1
            print(f"FAIL {src.name}: asan build failed {(b.stderr or b.stdout)[-600:]}")
            continue
        py = subprocess.run([sys.executable, str(src)], capture_output=True, text=True, cwd=ACCEPT, env=env,
                            encoding="utf-8", errors="replace")
        r = subprocess.run([str(exe)], capture_output=True, text=True, cwd=ACCEPT, env=env, timeout=600,
                           encoding="utf-8", errors="replace")
        report = "AddressSanitizer" in r.stderr
        same = r.stdout.replace("\r\n", "\n") == py.stdout.replace("\r\n", "\n") and r.returncode == py.returncode
        if report or not same:
            failures += 1
            print(f"FAIL {src.name}: asan_report={report} exit {r.returncode} (cpython {py.returncode}) same={same}")
            print("   " + r.stderr.strip()[-2000:].replace("\n", "\n   "))
        else:
            print(f"ok   {src.name}")
    print(f"asan ({backend}): {len(tests) - failures}/{len(tests)} clean")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
