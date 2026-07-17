"""Accept: int/float/str/bool conversion builtins, incl. runtime-checked parses."""


def main() -> None:
    print(int("42") + 1)
    print(float("3.5") * 2.0)
    print(str(99) + "!")
    print(int(3.9), int(-3.9))
    print(bool(0), bool(3))


if __name__ == "__main__":
    main()
