"""Accept: locals assigned inside a try body and used after a diverging handler (no pre-initialization)."""
from serpentine import Ref


def parse(s: str) -> int:
    """Parse a non-negative int, raising ValueError on bad input."""
    if s == "":
        raise ValueError("empty")
    for ch in s:
        if ch < "0" or ch > "9":
            raise ValueError("bad: " + s)
    return int(s)


def sum_valid(items: Ref[list[str]]) -> int:
    """int local first assigned in the try, used after an except that continues."""
    total: int = 0
    for s in items:
        try:
            v: int = parse(s)
        except ValueError:
            continue
        total += v
    return total


def mean_until_bad(items: Ref[list[str]]) -> float:
    """float and bool locals assigned in the try, used after an except that breaks."""
    acc: float = 0.0
    n: int = 0
    for s in items:
        try:
            x: float = parse(s) / 2
            big: bool = x > 5.0
        except ValueError:
            break
        acc += x
        if big:
            n += 10
        n += 1
    return acc + n


def first_even(items: Ref[list[str]]) -> int | None:
    """Optional local assigned in the try."""
    for s in items:
        try:
            found: int | None = parse(s)
        except ValueError:
            continue
        if found is not None:
            if found % 2 == 0:
                return found
    return None


def main() -> None:
    print(sum_valid(["1", "x", "22", "", "333"]))
    print(mean_until_bad(["4", "20", "oops", "8"]))
    print(first_even(["q", "7", "12", "3"]))
    print(first_even(["q", "7"]))


if __name__ == "__main__":
    main()
