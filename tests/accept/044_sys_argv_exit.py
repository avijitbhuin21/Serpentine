"""sys.argv and sys.exit: argument count and clean exit status."""
import sys


def main() -> None:
    args: list[str] = sys.argv
    print(len(args) - 1)
    if len(args) > 100:
        sys.exit(2)
    print("done")
    sys.exit(0)


if __name__ == "__main__":
    main()
