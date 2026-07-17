"""Accept: f-string formatting parity across the Tier-0 format specs (divergence D6)."""


def main() -> None:
    x: float = 3.14159
    n: int = 42
    s: str = "serp"
    print(f"{s} {n} {x:.2f}")
    print(f"{s!r}")
    print(f"{n:>6}|{n:<6}|{n:^6}|")
    print(f"{n:d}")


if __name__ == "__main__":
    main()
