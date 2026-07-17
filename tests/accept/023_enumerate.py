"""Accept: enumerate borrows the container like a plain for (SPEC section 5.4)."""


def main() -> None:
    names: list[str] = ["ada", "alan", "grace"]
    for i, name in enumerate(names):
        print(i, name)


if __name__ == "__main__":
    main()
