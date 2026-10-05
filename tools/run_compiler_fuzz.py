"""Compiler differential fuzzer: random well-typed programs, CPython vs Backend A vs Backend B.

Usage: python tools/run_compiler_fuzz.py [--seed N] [--count N]
Failing programs are kept under the printed temp dir for reproduction.
"""
import argparse
import random
import subprocess
import sys
import tempfile
from pathlib import Path

INTS = ["a", "b", "c", "d"]
STRS = ["s", "t"]
MOD = 10007


class Gen:
    """Random program generator over a small typed subset."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.lines: list[str] = []
        self.loops = 0

    def int_expr(self, depth: int = 0) -> str:
        """An int-typed expression whose magnitude stays far from int64 limits."""
        r = self.rng.random()
        if depth > 2 or r < 0.3:
            return self.rng.choice(INTS + [str(self.rng.randint(-50, 50))])
        op = self.rng.choice(["+", "-", "*", "//", "%", "min", "max", "abs", "len", "tern", "call", "idx"])
        x, y = self.int_expr(depth + 1), self.int_expr(depth + 1)
        if op == "*":
            return f"(({x}) * ({y})) % {MOD}"
        if op in ("//", "%"):
            return f"(({x}) {op} ((({y}) % 7) + 1))"
        if op in ("min", "max"):
            return f"{op}({x}, {y})"
        if op == "abs":
            return f"abs({x})"
        if op == "len":
            return f"len({self.rng.choice(STRS + ['xs'])})"
        if op == "tern":
            return f"({x} if {self.cond(depth + 1)} else {y})"
        if op == "call":
            return f"f{self.rng.randint(0, 1)}({x}, {y})"
        if op == "idx":
            return f"(xs[({x}) % len(xs)] if len(xs) > 0 else 0)"
        return f"(({x}) {op} ({y}))"

    def str_expr(self, depth: int = 0) -> str:
        """A str-typed expression."""
        r = self.rng.random()
        if depth > 2 or r < 0.35:
            return self.rng.choice(STRS + [repr(self.rng.choice(["", "ab", "Zq", "x-y", "  pad "]))])
        op = self.rng.choice(["cat", "slice", "upper", "strint", "strip", "tern"])
        x = self.str_expr(depth + 1)
        if op == "cat":
            return f"({x} + {self.str_expr(depth + 1)})"
        if op == "slice":
            return f"{x}[{self.rng.randint(0, 3)}:{self.rng.randint(0, 6)}]"
        if op == "upper":
            return f"{x}.upper()"
        if op == "strip":
            return f"{x}.strip()"
        if op == "strint":
            return f"str({self.int_expr(depth + 1)})"
        return f"({x} if {self.cond(depth + 1)} else {self.str_expr(depth + 1)})"

    def cond(self, depth: int = 0) -> str:
        """A bool-typed expression."""
        r = self.rng.random()
        if r < 0.5 or depth > 2:
            return f"({self.int_expr(depth + 1)} {self.rng.choice(['<', '<=', '==', '!=', '>'])} {self.int_expr(depth + 1)})"
        if r < 0.7:
            return f"({self.str_expr(depth + 1)} == {self.str_expr(depth + 1)})"
        return f"({self.cond(depth + 1)} {self.rng.choice(['and', 'or'])} not {self.cond(depth + 1)})"

    def emit(self, ind: int, text: str) -> None:
        """Append one indented source line."""
        self.lines.append("    " * ind + text)

    def stmt(self, ind: int, depth: int) -> None:
        """One random statement (recursing into blocks up to a depth)."""
        r = self.rng.random()
        if r < 0.3:
            v = self.rng.choice(INTS)
            self.emit(ind, f"{v} = ({self.int_expr()}) % {MOD}")
        elif r < 0.45:
            self.emit(ind, f"{self.rng.choice(STRS)} = ({self.str_expr()})[0:40]")
        elif r < 0.55:
            self.emit(ind, f"print({self.int_expr()}, {self.str_expr()}, {self.cond()})")
        elif r < 0.62:
            self.emit(ind, f"xs.append({self.int_expr()})")
            self.emit(ind, "if len(xs) > 12:")
            self.emit(ind + 1, "xs.pop(0)")
        elif r < 0.72 and depth < 3:
            self.emit(ind, f"if {self.cond()}:")
            self.block(ind + 1, depth + 1)
            if self.rng.random() < 0.5:
                self.emit(ind, f"elif {self.cond()}:")
                self.block(ind + 1, depth + 1)
            self.emit(ind, "else:")
            self.block(ind + 1, depth + 1)
        elif r < 0.8 and depth < 3:
            self.emit(ind, f"for i{depth} in range({self.rng.randint(0, 5)}):")
            self.block(ind + 1, depth + 1)
        elif r < 0.86 and depth < 3:
            self.loops += 1
            k = f"k{self.loops}"
            self.emit(ind, f"{k}: int = 0")
            self.emit(ind, f"while {k} < {self.rng.randint(1, 6)}:")
            self.emit(ind + 1, f"{k} += 1")
            self.block(ind + 1, depth + 1)
            if self.rng.random() < 0.3:
                self.emit(ind + 1, f"if {self.cond()}:")
                self.emit(ind + 2, self.rng.choice(["break", "continue"]))
        elif r < 0.92 and depth < 3:
            self.emit(ind, f"for v{depth} in xs:")
            self.emit(ind + 1, f"a = (a + v{depth}) % {MOD}")
        else:
            self.emit(ind, "try:")
            self.emit(ind + 1, f"d = ({self.int_expr()}) // ({self.rng.choice(INTS)} % 3)")
            self.emit(ind, "except ZeroDivisionError:")
            self.emit(ind + 1, 'print("zde")')
            self.emit(ind + 1, "d = 1")

    def block(self, ind: int, depth: int) -> None:
        """1-3 statements."""
        for _ in range(self.rng.randint(1, 3)):
            self.stmt(ind, depth)

    def program(self) -> str:
        """A complete program with two helpers and a main."""
        head = ['"""Generated by tools/run_compiler_fuzz.py."""', "", ""]
        for n in range(2):
            self.lines = []
            self.emit(0, f"def f{n}(a: int, b: int) -> int:")
            self.emit(1, '"""Generated helper."""')
            self.emit(1, "c: int = (a * 3 + b) % 101")
            self.emit(1, "d: int = a - b")
            self.emit(1, "if c > d:")
            self.emit(2, f"return (c - d) % {MOD}")
            self.emit(1, f"return (a + b * 7) % {MOD}")
            head += self.lines + ["", ""]
        self.lines = []
        self.emit(0, "def main() -> None:")
        self.emit(1, '"""Generated entry point."""')
        for v in INTS:
            self.emit(1, f"{v}: int = {self.rng.randint(-20, 20)}")
        self.emit(1, 's: str = "seed"')
        self.emit(1, 't: str = "Tt"')
        self.emit(1, "xs: list[int] = [3, 1, 4]")
        for _ in range(self.rng.randint(6, 14)):
            self.stmt(1, 0)
        self.emit(1, 'print("end", a, b, c, d, s, t, xs)')
        return "\n".join(head + self.lines + ["", "", 'if __name__ == "__main__":', "    main()", ""])


def main() -> int:
    """Generate programs and compare CPython with both native backends."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=25)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    tmp = Path(tempfile.mkdtemp(prefix="serp_cfuzz_"))
    stats = {"ok": 0, "rejected": 0, "mismatch": 0}
    for n in range(args.count):
        src = tmp / f"p{n:03d}.py"
        src.write_text(Gen(rng).program(), encoding="utf-8")
        py = subprocess.run([sys.executable, str(src)], capture_output=True, text=True)
        chk = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "check", str(src)],
                             capture_output=True, text=True)
        if chk.returncode != 0:
            stats["rejected"] += 1
            first = (chk.stderr or chk.stdout).strip().splitlines()[:1]
            print(f"reject p{n:03d}: {first[0] if first else '?'}")
            continue
        bad = []
        for be, flags in (("llvm", ["--backend", "llvm", "--debug"]), ("rust", ["--backend", "rust", "--debug"])):
            exe = tmp / f"p{n:03d}_{be}.exe"
            b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(src), "-o", str(exe), *flags],
                               capture_output=True, text=True)
            if b.returncode != 0:
                bad.append(f"{be}: build failed: {(b.stderr or b.stdout).strip()[-400:]}")
                continue
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            if r.stdout != py.stdout or r.returncode != py.returncode:
                bad.append(f"{be}: exit {r.returncode} vs {py.returncode}; native {r.stdout[-200:]!r} "
                           f"cpython {py.stdout[-200:]!r} {r.stderr[-300:]}")
        if bad:
            stats["mismatch"] += 1
            print(f"MISMATCH {src}")
            for line in bad:
                print("   ", line)
        else:
            stats["ok"] += 1
    print(f"compiler fuzz (seed {args.seed}): {stats} -> programs in {tmp}")
    return 1 if stats["mismatch"] else 0


if __name__ == "__main__":
    sys.exit(main())
