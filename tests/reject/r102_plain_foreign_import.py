# serp-reject: SE213 foreign-import
"""Reject: a plain `import` of a non-Serpentine package, even when no member is used
(CPython would still raise ImportError at startup when the package is missing)."""
import requests  # E: SE213


def main() -> None:
    print("hi")


if __name__ == "__main__":
    main()
