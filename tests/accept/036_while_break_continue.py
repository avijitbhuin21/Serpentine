"""Accept: while True with break and continue."""


def main() -> None:
    i: int = 0
    total: int = 0
    while True:
        i += 1
        if i > 10:
            break
        if i % 2 == 0:
            continue
        total += i
    print(total)


if __name__ == "__main__":
    main()
