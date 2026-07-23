"""Benchmark harness: CPython vs serp-native (Backend A, opt-level=2) vs
handwritten Rust references (§5.11). Prints a table; results are recorded in
docs/guides/benchmarks.md.

Codon and mypyc are not runnable on this Windows host (Codon has no Windows
support; mypyc needs MSVC cl.exe) — documented in docs/guides/benchmarks.md.

Usage: python tools/run_benchmarks.py [pattern]
"""

import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
RUNS = 3

RUST_REFS = {"bench_fib.py": "fib.rs", "bench_alloc.py": "alloc.rs"}


def timed(cmd: list[str], cwd: Path) -> tuple[float, bytes]:
    """Median wall-clock seconds over RUNS runs; also returns stdout of the last run."""
    times = []
    out = b""
    for _ in range(RUNS):
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, timeout=1200, cwd=str(cwd))
        times.append(time.perf_counter() - t0)
        if proc.returncode != 0:
            raise RuntimeError(f"{cmd} failed: {proc.stderr.decode(errors='replace')[:400]}")
        out = proc.stdout
    return statistics.median(times), out


def main() -> int:
    """Build and time every benchmark; verify outputs agree across runners."""
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    rustc = shutil.which("rustc")
    tmp = Path(tempfile.mkdtemp(prefix="serp_bench_"))
    rows = []
    for bench in sorted(BENCH.glob("bench_*.py")):
        if pattern and pattern not in bench.name:
            continue
        exe = tmp / (bench.stem + ".exe")
        bld = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build",
                              str(bench), "-o", str(exe), "--backend", "rust"],
                             capture_output=True, timeout=600, cwd=str(BENCH))
        if bld.returncode != 0:
            print(f"BUILD FAIL {bench.name}: {(bld.stderr or bld.stdout).decode()[:400]}")
            return 1
        t_py, out_py = timed([sys.executable, str(bench)], BENCH)
        t_serp, out_serp = timed([str(exe)], BENCH)
        if out_py.replace(b"\r\n", b"\n") != out_serp.replace(b"\r\n", b"\n"):
            print(f"OUTPUT MISMATCH {bench.name}")
            print(f"  cpython: {out_py[:200]!r}")
            print(f"  serp   : {out_serp[:200]!r}")
            return 1
        t_rust = None
        ref = RUST_REFS.get(bench.name)
        if ref and rustc:
            rs = BENCH / "rust" / ref
            rexe = tmp / (ref.replace(".rs", "_rust.exe"))
            rb = subprocess.run([rustc, "--edition", "2021", "-C", "opt-level=2",
                                 "-o", str(rexe), str(rs)],
                                capture_output=True, timeout=600)
            if rb.returncode == 0:
                t_rust, out_rust = timed([str(rexe)], BENCH)
                if out_rust.replace(b"\r\n", b"\n") != out_py.replace(b"\r\n", b"\n"):
                    print(f"RUST OUTPUT MISMATCH {bench.name}: {out_rust[:120]!r}")
                    return 1
        rows.append((bench.name, t_py, t_serp, t_rust))

    print(f"\n{'benchmark':<22}{'CPython':>10}{'serp':>10}{'speedup':>9}{'rust':>10}")
    for name, t_py, t_serp, t_rust in rows:
        rust = f"{t_rust:>9.3f}s" if t_rust is not None else "        —"
        print(f"{name:<22}{t_py:>9.3f}s{t_serp:>9.3f}s{t_py / t_serp:>8.1f}x{rust}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
