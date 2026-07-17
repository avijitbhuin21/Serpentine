# serp-reject: SE201 unsupported-feature
"""Reject: default parameter values are not in the Tier-0 grammar (3.2)."""


def greet(name: str = "world") -> None:  # E: SE201
    print(name)


def main() -> None:
    greet()


if __name__ == "__main__":
    main()
