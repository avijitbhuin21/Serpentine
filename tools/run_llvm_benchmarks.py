"""Runtime benchmark (Phase 5.3): Backend A (rust, opt-level=2) vs Backend B
(direct LLVM, release) on the benchmarks/ suite. Outputs must match; Backend B
must be within 5% of Backend A (ratio B/A <= 1.05) across the suite.

Usage: python tools/run_llvm_benchmarks.py [pattern]
"""

import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
RUNS = 5

# Workloads scaled up so runtimes dominate process startup (ratio stability).
SCALE = {
    "bench_fib.py": ("fib(32)", "fib(38)"),
    "bench_floats.py": ("leibniz(10000000)", "leibniz(200000000)"),
    "bench_strings.py": ("process(300000)", "process(2000000)"),
    "bench_alloc.py": ("step(300000)", "step(3000000)"),
}


def timed(cmd: list[str], cwd: Path) -> tuple[float, bytes]:
    """Best-of-RUNS wall-clock seconds (less noise than median for short runs)."""
    times = []
    out = b""
    for _ in range(RUNS):
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, timeout=1200, cwd=str(cwd))
        times.append(time.perf_counter() - t0)
        if proc.returncode != 0:
            raise RuntimeError(f"{cmd} failed: {proc.stderr.decode(errors='replace')[:400]}")
        out = proc.stdout
    return min(times), out


def build(backend: str, src: Path, out: Path) -> None:
    cmd = [sys.executable, "-m", "serpentine_lang.cli", "build", str(src), "-o", str(out)]
    if backend == "llvm":
        cmd += ["--backend", "llvm"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600, cwd=str(BENCH))
    if proc.returncode != 0:
        raise RuntimeError(f"{backend} build of {src.name} failed:\n"
                           f"{(proc.stderr or proc.stdout).decode(errors='replace')[:600]}")


def main() -> int:
    """Build with both backends, compare outputs and times."""
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    tmp = Path(tempfile.mkdtemp(prefix="serp_llvm_bench_"))
    rows = []
    worst = 0.0
    for bench in sorted(BENCH.glob("bench_*.py")):
        if pattern and pattern not in bench.name:
            continue
        src = bench
        if bench.name in SCALE:
            old, new = SCALE[bench.name]
            scaled = tmp / bench.name
            scaled.write_text(bench.read_text(encoding="utf-8").replace(old, new),
                              encoding="utf-8")
            src = scaled
        exe_a = tmp / (bench.stem + "_a.exe")
        exe_b = tmp / (bench.stem + "_b.exe")
        build("rust", src, exe_a)
        build("llvm", src, exe_b)
        t_a, out_a = timed([str(exe_a)], BENCH)
        t_b, out_b = timed([str(exe_b)], BENCH)
        if out_a.replace(b"\r\n", b"\n") != out_b.replace(b"\r\n", b"\n"):
            print(f"OUTPUT MISMATCH {bench.name}")
            print(f"  A: {out_a[:200]!r}\n  B: {out_b[:200]!r}")
            return 1
        ratio = t_b / t_a
        worst = max(worst, ratio)
        rows.append((bench.name, t_a, t_b, ratio))
    print(f"\n{'benchmark':<22}{'A (rust)':>10}{'B (llvm)':>10}{'B/A':>8}")
    for name, t_a, t_b, ratio in rows:
        flag = "" if ratio <= 1.05 else "  <-- over 5%"
        print(f"{name:<22}{t_a:>9.3f}s{t_b:>9.3f}s{ratio:>7.2f}x{flag}")
    print(f"\nworst B/A ratio: {worst:.3f} (bar: 1.05)")
    return 0 if worst <= 1.05 else 1


if __name__ == "__main__":
    sys.exit(main())
