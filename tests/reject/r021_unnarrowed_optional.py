# serp-reject: SE210 unnarrowed-optional
"""Reject: using a T | None value as T without an is-None narrowing test (SPEC 6)."""


def main() -> None:
    ages: dict[str, int] = {"ada": 36}
    a: int | None = ages.get("bob")
    print(a + 1)  # E: SE210


if __name__ == "__main__":
    main()
