"""Accept: dict literals, insertion, membership, len, Copy-value indexing, ordering (D8)."""


def main() -> None:
    ages: dict[str, int] = {"ada": 36, "alan": 41}
    ages["grace"] = 85
    print(len(ages))
    print("ada" in ages, "bob" not in ages)
    print(ages["grace"])
    print(ages)


if __name__ == "__main__":
    main()
