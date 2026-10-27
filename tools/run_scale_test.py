"""Compiler scale test: generate a large multi-module program and measure check/build cost.

Generates N modules of realistic Serpentine (dataclasses with methods, loops over lists and
dicts, string formatting, exceptions, cross-module calls) plus a main that exercises all of
them, then times `serp check` and `serp build` for both backends and samples the compiler's
peak memory. The built binary's output is compared against CPython.

Usage: python tools/run_scale_test.py [--loc 20000] [--keep DIR]
"""
import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODULE = '''from __future__ import annotations
from serpentine import Mut, Ref, dataclass, move


class Error{m}(Exception):
    pass


@dataclass
class Item{m}:
    name: str
    qty: int
    price: float
    tags: list[str] = []

    def total(self: Ref[Item{m}]) -> float:
        return self.qty * self.price

    def label(self: Ref[Item{m}]) -> str:
        return f"{{self.name}}x{{self.qty}}"

    def bump(self: Mut[Item{m}], n: int) -> None:
        self.qty += n
'''

FUNC = '''

def f{m}_{k}(xs: Ref[list[int]], seed: int) -> int:
    """Generated workload {m}.{k}."""
    acc: int = seed
    counts: dict[str, int] = {{}}
    for i in range(len(xs)):
        v: int = xs[i]
        if v % 3 == 0:
            acc += v * {k1}
        elif v % 3 == 1:
            acc -= v // 2
        else:
            acc = (acc * 7 + v) % 100003
        key: str = "k" + str(v % 5)
        if key in counts:
            counts[key] += 1
        else:
            counts[key] = 1
    items: list[Item{m}] = []
    j: int = 0
    while j < 4:
        items.append(Item{m}("it" + str(j), j + {k}, 1.5 * j))
        j += 1
    for it in items:
        acc += int(it.total()) + len(it.label())
    items[0].bump(2)
    try:
        if acc < 0:
            raise Error{m}("negative " + str(acc))
    except Error{m} as e:
        acc = -acc + len(str(e))
    return (acc + len(counts)) % 1000003
'''


def generate(target_loc: int, out: Path) -> tuple[int, int]:
    """Write modules until the target line count is reached; returns (modules, lines)."""
    out.mkdir(parents=True, exist_ok=True)
    fn_per_mod = 20
    lines = 0
    mods = 0
    calls = []
    while lines < target_loc:
        parts = [MODULE.format(m=mods)]
        for k in range(fn_per_mod):
            parts.append(FUNC.format(m=mods, k=k, k1=k + 1))
            calls.append((mods, k))
        text = "".join(parts)
        (out / f"mod{mods}.py").write_text(text, encoding="utf-8")
        lines += text.count("\n")
        mods += 1
    main = ["from __future__ import annotations"]
    for m in range(mods):
        names = ", ".join(f"f{m}_{k}" for k in range(fn_per_mod))
        main.append(f"from mod{m} import {names}")
    main += ["", "", "def main() -> None:", "    xs: list[int] = []", "    i: int = 0",
             "    while i < 200:", "        xs.append((i * 37) % 101)", "        i += 1",
             "    total: int = 0"]
    for m, k in calls:
        main.append(f"    total = (total + f{m}_{k}(xs, {m + k})) % 1000003")
    main += ["    print(total)", "", "", 'if __name__ == "__main__":', "    main()", ""]
    text = "\n".join(main)
    (out / "main.py").write_text(text, encoding="utf-8")
    lines += text.count("\n")
    return mods + 1, lines


def peak_rss_mib(proc: subprocess.Popen) -> float:
    """Poll a child's resident memory until it exits; returns the peak in MiB."""
    peak = 0.0
    while proc.poll() is None:
        try:
            if sys.platform == "win32":
                import ctypes
                k32 = ctypes.WinDLL("kernel32")
                psapi = ctypes.WinDLL("psapi")

                class PMC(ctypes.Structure):
                    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                                ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t),
                                ("d", ctypes.c_size_t), ("e", ctypes.c_size_t), ("f", ctypes.c_size_t)]
                h = k32.OpenProcess(0x0400 | 0x0010, False, proc.pid)
                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    peak = max(peak, pmc.PeakWorkingSetSize / 2**20)
                k32.CloseHandle(h)
            else:
                for line in Path(f"/proc/{proc.pid}/status").read_text().splitlines():
                    if line.startswith("VmHWM:"):
                        peak = max(peak, int(line.split()[1]) / 1024)
        except OSError:
            pass
        time.sleep(0.05)
    return peak


PEAK_WRAPPER = r'''
import sys, runpy, atexit
def _report():
    peak = 0.0
    try:
        if sys.platform == "win32":
            import ctypes
            class PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                            ("PeakWorkingSetSize", ctypes.c_size_t)] + [(f"x{i}", ctypes.c_size_t) for i in range(7)]
            pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
            k32 = ctypes.WinDLL("kernel32"); k32.GetCurrentProcess.restype = ctypes.c_void_p
            ps = ctypes.WinDLL("psapi"); ps.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
            ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
            peak = pmc.PeakWorkingSetSize / 2**20
        else:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 if sys.platform != "darwin" else 2**20)
    except Exception:
        pass
    sys.stderr.write(f"\nSERP_PEAK_MIB={peak:.1f}\n")
atexit.register(_report)
sys.argv = ["serp"] + sys.argv[1:]
runpy.run_module("serpentine_lang.cli", run_name="__main__")
'''


def timed(cmd: list[str], cwd: Path) -> tuple[float, float, subprocess.CompletedProcess]:
    """Run a compiler command through PEAK_WRAPPER; (seconds, compiler peak MiB, result)."""
    t0 = time.time()
    full = [cmd[0], "-c", PEAK_WRAPPER] + cmd[3:]
    r = subprocess.run(full, cwd=str(cwd), capture_output=True)
    peak = 0.0
    for line in r.stderr.decode(errors="replace").splitlines():
        if line.startswith("SERP_PEAK_MIB="):
            peak = float(line.split("=")[1])
    return time.time() - t0, peak, r


def main() -> int:
    """Generate, check, build both backends, run, and report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--loc", type=int, default=20000)
    ap.add_argument("--keep", default="")
    args = ap.parse_args()
    work = (Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="serp_scale_"))).resolve()
    mods, lines = generate(args.loc, work)
    print(f"generated {lines} lines in {mods} modules under {work}")
    py = sys.executable
    exp = subprocess.run([py, "main.py"], cwd=str(work), capture_output=True,
                         env=dict(os.environ, PYTHONPATH=str(ROOT / "shim" / "src"))).stdout.strip()
    ok = True
    secs, peak, r = timed([py, "-m", "serpentine_lang.cli", "check", "main.py"], work)
    print(f"check: {secs:6.1f}s  peak {peak:6.0f} MiB  exit {r.returncode}")
    ok &= r.returncode == 0
    for backend in ("rust", "llvm"):
        exe = work / (f"app_{backend}" + (".exe" if sys.platform == "win32" else ""))
        secs, peak, r = timed([py, "-m", "serpentine_lang.cli", "build", "main.py", "-o", str(exe),
                               "--backend", backend], work)
        if r.returncode != 0:
            print(f"build {backend}: FAIL\n{(r.stderr or r.stdout).decode(errors='replace')[-2000:]}")
            ok = False
            continue
        got = subprocess.run([str(exe)], capture_output=True).stdout.strip()
        same = got == exp
        ok &= same
        size = exe.stat().st_size / 2**20
        print(f"build {backend:4}: {secs:6.1f}s  peak {peak:6.0f} MiB (Python compiler; rustc/LLVM separate)  "
              f"binary {size:5.1f} MiB  output {'matches' if same else 'DIFFERS from'} CPython ({got.decode()!s})")
    print(f"\nscale test ({lines} LOC): {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
