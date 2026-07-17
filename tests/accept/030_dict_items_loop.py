"""Accept: iterating keys, values, items — all Ref borrows of the dict (SPEC 5.4)."""


def main() -> None:
    ages: dict[str, int] = {"ada": 36, "alan": 41}
    for name in ages.keys():
        print(name)
    for age in ages.values():
        print(age)
    for name2, age2 in ages.items():
        print(name2, age2)


if __name__ == "__main__":
    main()
