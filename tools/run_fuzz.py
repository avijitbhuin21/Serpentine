"""Differential parser fuzzer: mutated inputs run through tools/fuzz/driver.py under CPython and natively.

Reports native crashes (with the minimal failing case) and verdict divergences. Usage:
  python tools/run_fuzz.py [--seed N] [--per-kind N] [--backend llvm|rust]
"""
import argparse
import random
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUZZ = ROOT / "tools" / "fuzz"
DRIVER = FUZZ / "driver.py"
SPECIAL = b'\x00\xff"\\{}[]()<>:,=#%&?*+|^$.-\n\r\t 0123456789aeEuU'


def raw_deflate(data: bytes) -> bytes:
    """Raw DEFLATE stream (no zlib header)."""
    co = zlib.compressobj(6, zlib.DEFLATED, -15)
    return co.compress(data) + co.flush()


SEEDS = {
    "json": [b'{"a": [1, 2.5, "x", null, true, false], "b": {"c": -1e10}}', b'[]', b'"\\u00e9\\n"',
             b'[[[[1]]], {"k": ""}]', b'123.5e-3'],
    "toml": [b'a = 1\n[t]\nb = "x"\nc = [1, 2]\n', b'x = { y = 2, z = "q" }\n',
             b'[[arr]]\nn = 1\n[[arr]]\nn = 2\n', b"s = '''multi\nline'''\nd = 1979-05-27\n"],
    "url": [b'https://user:pw@example.com:8080/p/a%20b?q=1&r=%20x&q=2#frag', b'http://[::1]:80/',
            b'mailto:x@y.z', b'//host/path?a'],
    "b64": [b'aGVsbG8gd29ybGQ=', b'YQ==', b'', b'AAECAwQFBgcICQ=='],
    "re": [b'(a|b)*c', b'[a-z]+\\d{2,3}', b'^x.*y$', b'(?P<n>a+)_(b*)', b'\\w+\\s\\d+', b'a{2,}?'],
    "zlib": [raw_deflate(b'hello world ' * 20), raw_deflate(bytes(range(256))), raw_deflate(b'')],
    "zlibw": [zlib.compress(b'abcabcabc' * 30), zlib.compress(b'x')],
    "gzip": [__import__("gzip").compress(b'hello gzip ' * 10, mtime=0),
             __import__("gzip").compress(b'a', mtime=0) * 2, b''],
    "csv": [b'a,b,"c,d"\n1,2,3\n', b'"q""uote",x\n\n,,\n', b'one\n"two\nlines",3\n'],
}


def mutate(rng: random.Random, data: bytes, pool: list[bytes]) -> bytes:
    """Apply 1-4 random structural mutations."""
    b = bytearray(data)
    for _ in range(rng.randint(1, 4)):
        op = rng.randrange(7)
        if op == 0 and b:
            b[rng.randrange(len(b))] ^= 1 << rng.randrange(8)
        elif op == 1:
            b.insert(rng.randrange(len(b) + 1), SPECIAL[rng.randrange(len(SPECIAL))])
        elif op == 2 and b:
            i = rng.randrange(len(b))
            del b[i:i + rng.randint(1, 8)]
        elif op == 3 and b:
            i = rng.randrange(len(b))
            j = min(len(b), i + rng.randint(1, 16))
            b[i:i] = b[i:j] * rng.randint(1, 4)
        elif op == 4 and b:
            del b[rng.randrange(len(b)):]
        elif op == 5:
            other = rng.choice(pool)
            cut = rng.randrange(len(other) + 1)
            b[rng.randrange(len(b) + 1):] = other[cut:]
        else:
            b[rng.randrange(len(b) + 1):rng.randrange(len(b) + 1)] = bytes(rng.randrange(256)
                                                                          for _ in range(rng.randint(1, 6)))
    return bytes(b[:4096])


def run(cmd: list[str], cases: Path, lo: int, hi: int) -> subprocess.CompletedProcess:
    """Run the driver over cases [lo, hi)."""
    import os
    env = dict(os.environ)
    paths = [str(ROOT / "shim" / "src")] + [str(d / "src") for d in sorted((ROOT / "libs").iterdir())
                                            if (d / "src").is_dir()]
    env["PYTHONPATH"] = os.pathsep.join(paths + [env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd + [str(cases), str(lo), str(hi)], capture_output=True, text=True,
                          cwd=FUZZ, timeout=900, encoding="utf-8", errors="replace", env=env)


def verdicts(stdout: str) -> dict[int, str]:
    """Case index -> verdict text."""
    out = {}
    for line in stdout.splitlines():
        idx, _, rest = line.partition(" ")
        if idx.isdigit():
            out[int(idx)] = rest
    return out


def find_crash(exe: list[str], cases: Path, lo: int, hi: int) -> int:
    """Smallest single case index in [lo, hi) that makes the native driver crash."""
    for i in range(lo, hi):
        r = run(exe, cases, i, i + 1)
        if r.returncode != 0:
            return i
    return -1


def main() -> int:
    """Generate, run both worlds, compare, report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--per-kind", type=int, default=300)
    ap.add_argument("--backend", default="llvm")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    lines = []
    for kind, seeds in SEEDS.items():
        pool = [s for ss in SEEDS.values() for s in ss]
        for s in seeds:
            lines.append((kind, s))
        for _ in range(args.per_kind):
            lines.append((kind, mutate(rng, rng.choice(seeds), pool)))
    tmp = Path(tempfile.mkdtemp(prefix="serp_fuzz_"))
    cases = tmp / "cases.txt"
    cases.write_bytes("\n".join(f"{k} {d.hex()}" for k, d in lines).encode("ascii"))
    exe = tmp / ("driver" + (".exe" if sys.platform == "win32" else ""))
    b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(DRIVER), "-o", str(exe),
                        "--backend", args.backend], capture_output=True, text=True, cwd=FUZZ)
    if b.returncode != 0:
        print("FAIL build\n" + (b.stderr or b.stdout)[-3000:])
        return 1
    n = len(lines)
    t0 = time.time()
    py = run([sys.executable, str(DRIVER)], cases, 0, n)
    t1 = time.time()
    nat = run([str(exe)], cases, 0, n)
    t2 = time.time()
    problems = 0
    if py.returncode != 0:
        print("CPython driver failed:", py.stderr[-2000:])
        return 1
    want = verdicts(py.stdout)
    if nat.returncode != 0:
        bad = find_crash([str(exe)], cases, 0, n)
        print(f"CRASH native exit {nat.returncode & 0xFFFFFFFF:#x}; first crashing case {bad}: "
              f"{lines[bad][0]} {lines[bad][1][:120]!r}" if bad >= 0 else "CRASH (not reproducible per case)")
        problems += 1
    got = verdicts(nat.stdout)
    diverged = [i for i in want if i in got and want[i] != got[i]]
    known = [i for i in diverged if "invalid literal for int()" in got[i] or "overflowed 64 bits" in got[i]]
    diverged = [i for i in diverged if i not in known]
    if known:
        print(f"known int64-vs-bignum divergences (docs/language/divergences.md): {len(known)}")
    for i in diverged[:15]:
        print(f"DIVERGE case {i} [{lines[i][0]}] {lines[i][1][:80]!r}\n  cpython: {want[i]}\n  native : {got[i]}")
    problems += len(diverged)
    kinds = {}
    for i, (k, _) in enumerate(lines):
        v = want.get(i, "")
        kinds.setdefault(k, [0, 0])[0 if v.startswith("ok") else 1] += 1
    print("per kind (ok/err):", {k: tuple(v) for k, v in kinds.items()})
    print(f"fuzz: {n} cases, {len(diverged)} divergences, crashes={'yes' if nat.returncode else 'no'}; "
          f"cpython {t1 - t0:.1f}s native {t2 - t1:.1f}s (seed {args.seed})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
