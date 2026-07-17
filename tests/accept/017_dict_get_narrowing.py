"""Accept: dict.get returns V | None; narrowed by is/is not None (SPEC section 6)."""


def main() -> None:
    ages: dict[str, int] = {"ada": 36}
    a: int | None = ages.get("ada")
    if a is not None:
        print(a + 1)
    b: int | None = ages.get("bob")
    if b is None:
        print("missing")


if __name__ == "__main__":
    main()
