# serp-reject: SE213 foreign-import
"""Reject: bin-3 import — stdlib/site-packages are outside Tier 0 (SPEC 9)."""

import os  # E: SE213


def main() -> None:
    print(os.getcwd())


if __name__ == "__main__":
    main()
