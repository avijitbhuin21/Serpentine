# serp-reject: SE207 identity-comparison
"""Reject: is/is not against anything but None — no stable identity natively (D3)."""


def main() -> None:
    a: list[int] = [1]
    b: list[int] = [1]
    print(a is b)  # E: SE207


if __name__ == "__main__":
    main()
