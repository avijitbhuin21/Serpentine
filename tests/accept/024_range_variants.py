"""Accept: range with one, two, and three arguments."""


def main() -> None:
    for i in range(3):
        print(i)
    for j in range(2, 5):
        print(j)
    for k in range(10, 0, -3):
        print(k)


if __name__ == "__main__":
    main()
