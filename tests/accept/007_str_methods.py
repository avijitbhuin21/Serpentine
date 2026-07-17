"""Accept: str methods — strip, upper, lower, split, join, startswith, endswith."""


def main() -> None:
    s: str = "  Serpentine Compiles Python  "
    t: str = s.strip()
    print(t.upper())
    print(t.lower())
    parts: list[str] = t.split(" ")
    print(len(parts))
    print("-".join(parts))
    print(t.startswith("Serp"), t.endswith("hon"))


if __name__ == "__main__":
    main()
