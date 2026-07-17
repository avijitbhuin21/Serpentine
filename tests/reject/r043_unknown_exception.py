# serp-reject: SE214 type-mismatch
"""Reject: unknown exception class — user exception classes are Tier 2."""


def main() -> None:
    try:
        print(1)
    except BananaError:  # E: SE214
        print("caught")


if __name__ == "__main__":
    main()
