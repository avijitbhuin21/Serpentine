"""Build-time benchmark (Phase 5.2), backend-only: time from CHECKED PROGRAM to
native binary. The Python front end (parse/typecheck/borrowck) is identical for
both backends and excluded; this isolates codegen + compile + link.

  Backend A debug/release: generate_rust + rustc (opt-level 0 / 2)
  Backend B debug/release: generate_llvm + emit_object + link (opt 0 / 3+LTO)

Usage: python tools/run_build_bench.py [--quick]
"""

import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compiler" / "src"))

ROOT = Path(__file__).resolve().parent.parent
ACCEPT = ROOT / "tests" / "accept"

SAMPLES = ["006_fib_iterative.py", "026_sort_reverse.py", "037_dataclass_basics.py",
           "051_comprehensions.py", "055_json_roundtrip.py"]


def synth_large(path: Path, n_funcs: int = 120) -> None:
    """Write a synthetic large program with n_funcs small functions."""
    parts = ["from serpentine import Ref\n"]
    for i in range(n_funcs):
        parts.append(f"""

def work_{i}(a: int, b: float) -> float:
    total: float = float(a) * b
    for j in range(10):
        if j % 2 == 0:
            total += float(j) * 1.5
        else:
            total -= 0.5
    parts: list[float] = [total, b, 1.0]
    return sum(parts)
""")
    calls = "\n    ".join(f"acc += work_{i}(i + {i}, 1.25)" for i in range(n_funcs))
    parts.append(f"""

def main() -> None:
    acc: float = 0.0
    i: int = 3
    {calls}
    print(acc)


if __name__ == "__main__":
    main()
""")
    path.write_text("".join(parts), encoding="utf-8")


def time_backend_a(tc, out: Path, debug: bool, tdir: Path) -> float:
    """Time Backend A: Rust codegen + rustc compile+link."""
    from serpentine_lang.rustgen import generate_rust
    rustc = shutil.which("rustc")
    t0 = time.perf_counter()
    rust_src = generate_rust(tc)
    rs = tdir / (out.stem + ".rs")
    rs.write_text(rust_src, encoding="utf-8")
    opt = "0" if debug else "2"
    proc = subprocess.run([rustc, "--edition", "2021", "-C", f"opt-level={opt}",
                           "-o", str(out), str(rs)], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace")[:400])
    return time.perf_counter() - t0


def time_backend_b(tc, out: Path, debug: bool) -> float:
    """Time Backend B: LLVM IR gen + object emission + link."""
    from serpentine_lang.llvmgen import build_llvm_native
    t0 = time.perf_counter()
    build_llvm_native(tc, out, debug=debug)
    return time.perf_counter() - t0


def main() -> int:
    """Compare backend-only build times; requires the debug geomean >= 2x."""
    from serpentine_lang.cli import run_check
    from serpentine_lang.diagnostics import Reporter
    from serpentine_lang.llvmbuild import ensure_runtime

    quick = "--quick" in sys.argv
    reps = 1 if quick else 3
    ensure_runtime(verbose=True)   # exclude the one-time runtime build
    with tempfile.TemporaryDirectory(prefix="serp_bench_build_") as td:
        tdir = Path(td)
        large = tdir / "synthetic_large.py"
        synth_large(large)
        srcs = [ACCEPT / s for s in SAMPLES] + [large]
        rows = []
        for src in srcs:
            tc = run_check(src, Reporter())
            row = {"name": src.name}
            for debug in (True, False):
                mode = "dbg" if debug else "rel"
                for kind in ("rust", "llvm"):
                    times = []
                    for r in range(reps):
                        out = tdir / f"{src.stem}_{kind}_{mode}_{r}.exe"
                        if kind == "rust":
                            times.append(time_backend_a(tc, out, debug, tdir))
                        else:
                            times.append(time_backend_b(tc, out, debug))
                    row[f"{kind}_{mode}"] = min(times)
            rows.append(row)
        print(f"\n{'program':28} {'A dbg':>7} {'B dbg':>7} {'speedup':>8} "
              f"{'A rel':>7} {'B rel':>7} {'speedup':>8}")
        dbg_ratios = []
        for r in rows:
            sd = r["rust_dbg"] / r["llvm_dbg"]
            sr = r["rust_rel"] / r["llvm_rel"]
            dbg_ratios.append(sd)
            print(f"{r['name']:28} {r['rust_dbg']:7.2f} {r['llvm_dbg']:7.2f} {sd:7.2f}x "
                  f"{r['rust_rel']:7.2f} {r['llvm_rel']:7.2f} {sr:7.2f}x")
        gm = statistics.geometric_mean(dbg_ratios)
        print(f"\nbackend-only debug-build geometric-mean speedup (B over A): {gm:.2f}x")
        return 0 if gm >= 2.0 else 1


if __name__ == "__main__":
    sys.exit(main())
