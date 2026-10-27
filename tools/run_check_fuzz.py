"""Checker robustness fuzzer: `serp check` must never crash, whatever the input.

Mutates real programs (accept + reject corpora) line- and token-wise, adds
random-garbage files, and runs the checker in-process through the public API
(`serpentine_lang.api.check_source`). Every outcome must be a list of
diagnostics; any escaping Python exception (IndexError, AssertionError,
RecursionError, ...) is a crash. Crashing inputs are saved for reproduction.

Usage: python tools/run_check_fuzz.py [--seed N] [--count N] [--out DIR]
"""
import argparse
import random
import sys
import tempfile
import time
import traceback
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler" / "src"))

from serpentine_lang.api import check_source  # noqa: E402

TOKENS = ["move(", ")", "(", ":", "Ref[", "Mut[", "Owned[", "]", "None", "int", "str", "float",
          "list[int]", "dict[str, int]", "PyVal", "lambda x: x", "yield", "await", "async ",
          "self", "return", "raise", "try:", "except", "with", "for", "in", "if", "else",
          "class", "def", "@dataclass", "@property", "@staticmethod", ",", "=", "==", "+",
          "*", "**", "[", "{", "}", "'", '"', "\\", "#", "0", "-1", "1e999", "b''",
          "f'{x}'", "...", "global", "nonlocal", "del", "assert", "import", "from"]


def corpus() -> list[str]:
    """Source texts to mutate."""
    out = []
    for d in ("accept", "reject"):
        for p in sorted((ROOT / "tests" / d).rglob("*.py")):
            try:
                out.append(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
    return out


def mutate(rng: random.Random, text: str, donors: list[str]) -> str:
    """Apply 1-4 random structural or token mutations."""
    lines = text.split("\n")
    for _ in range(rng.randint(1, 4)):
        if not lines:
            lines = [""]
        op = rng.randrange(10)
        i = rng.randrange(len(lines))
        if op == 0:
            del lines[i]
        elif op == 1:
            lines.insert(i, lines[rng.randrange(len(lines))])
        elif op == 2:
            j = rng.randrange(len(lines))
            lines[i], lines[j] = lines[j], lines[i]
        elif op == 3:
            ln = lines[i]
            k = rng.randrange(len(ln) + 1)
            lines[i] = ln[:k] + rng.choice(TOKENS) + ln[k:]
        elif op == 4:
            words = lines[i].split(" ")
            if words:
                words[rng.randrange(len(words))] = rng.choice(TOKENS)
                lines[i] = " ".join(words)
        elif op == 5:
            lines = lines[:i]
        elif op == 6:
            lines[i] = (" " * rng.choice([1, 2, 3, 4, 8])) + lines[i].lstrip()
        elif op == 7:
            donor = rng.choice(donors).split("\n")
            a = rng.randrange(len(donor))
            lines[i:i] = donor[a:a + rng.randint(1, 6)]
        elif op == 8:
            ln = lines[i]
            if ln:
                k = rng.randrange(len(ln))
                lines[i] = ln[:k] + ln[k + 1:]
        else:
            for a, b in (("int", "str"), ("Ref[", "Mut["), ("Mut[", "Owned["), ("move(", "("),
                         ("str", "bytes"), ("list", "dict"), ("None", "0")):
                if a in lines[i] and rng.random() < 0.5:
                    lines[i] = lines[i].replace(a, b, 1)
    return "\n".join(lines)


def garbage(rng: random.Random) -> str:
    """Random token soup and random bytes decoded leniently."""
    if rng.random() < 0.5:
        return " ".join(rng.choice(TOKENS) for _ in range(rng.randint(1, 80)))
    return bytes(rng.randrange(256) for _ in range(rng.randint(0, 300))).decode("latin-1")


def main() -> int:
    """Run the fuzz loop and report crashes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=2000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    texts = corpus()
    work = Path(tempfile.mkdtemp(prefix="serp_checkfuzz_"))
    out = Path(args.out) if args.out else work / "crashes"
    entry = work / "case.py"
    entry.write_text("", encoding="utf-8")
    crashes: dict[str, int] = {}
    diag_cases = clean = 0
    t0 = time.time()
    sys.setrecursionlimit(10000)
    warnings.simplefilter("ignore")
    for n in range(args.count):
        src = garbage(rng) if rng.random() < 0.1 else mutate(rng, rng.choice(texts), texts)
        try:
            diags = check_source(entry, src)
            if diags:
                diag_cases += 1
            else:
                clean += 1
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            where = f"{type(e).__name__} at {Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else type(e).__name__
            crashes[where] = crashes.get(where, 0) + 1
            if crashes[where] == 1:
                out.mkdir(parents=True, exist_ok=True)
                case = out / f"crash_{len(crashes):03d}.py"
                case.write_text(src, encoding="utf-8")
                print(f"CRASH {where}: {e!s:.200} -> {case}")
    dt = time.time() - t0
    print(f"\ncheck fuzz: {args.count} cases in {dt:.0f}s (seed {args.seed}): {diag_cases} rejected with "
          f"diagnostics, {clean} accepted, {sum(crashes.values())} crashes in {len(crashes)} distinct sites")
    return 1 if crashes else 0


if __name__ == "__main__":
    sys.exit(main())
