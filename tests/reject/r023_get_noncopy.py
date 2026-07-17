# serp-reject: SE212 get-non-copy
"""Reject: dict.get on non-Copy values — it would copy out of the container (7.1)."""


def main() -> None:
    d: dict[str, list[int]] = {"a": [1, 2]}
    v: list[int] | None = d.get("a")  # E: SE212
    print(v)


if __name__ == "__main__":
    main()
