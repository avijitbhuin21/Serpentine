"""Tier-2 comprehensions: list/dict, condition, several iterator kinds."""


def main() -> None:
    xs: list[int] = [5, 3, 8, 1]
    sq: list[int] = [x * x for x in xs]
    print(sq)
    evens: list[int] = [n for n in range(10) if n % 2 == 0]
    print(evens)
    words: list[str] = ["alpha", "beta", "gamma"]
    ups: list[str] = [w.upper() for w in words if len(w) > 4]
    print(ups)
    lens: dict[str, int] = {w: len(w) for w in words}
    print(lens)
    flipped: dict[int, str] = {v: k for k, v in lens.items()}
    print(flipped)
    idx: list[str] = [f"{i}:{w}" for i, w in enumerate(words)]
    print(idx)
    letters: list[str] = [c for c in "serp"]
    print(letters)
    print(len(xs), len(words))


if __name__ == "__main__":
    main()
