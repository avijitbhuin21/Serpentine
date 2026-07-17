"""Accept: Optional parameter narrowed by early return (SPEC section 6)."""


def describe(n: int | None) -> str:
    if n is None:
        return "nothing"
    return str(n * 2)


def main() -> None:
    print(describe(21))
    print(describe(None))


if __name__ == "__main__":
    main()
