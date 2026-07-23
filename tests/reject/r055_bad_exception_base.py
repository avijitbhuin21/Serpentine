# serp-reject: SE214 type-mismatch
"""Reject: exception class with an unknown base class."""


class MyError(Banana):  # E: SE214
    pass


def main() -> None:
    try:
        print(1)
    except MyError:
        print("caught")


if __name__ == "__main__":
    main()
