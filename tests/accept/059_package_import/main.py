"""Accept: package imports — dotted modules resolved through the entry tree + serp.toml."""

from util.text import shout, titled
from util.fmt import rule as hr


def main() -> None:
    print(shout("serpentine packages"))
    print(titled("hello"))
    print(hr(12))


if __name__ == "__main__":
    main()
