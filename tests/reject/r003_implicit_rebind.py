# serp-reject: SE003 implicit-transfer
"""Reject: plain rebinding of a live non-Copy value — transfers must be spelled out (J3)."""

from serpentine import Owned


def main() -> None:
    a: Owned[list[int]] = [1, 2, 3]
    b = a  # E: SE003
    b.append(4)
    print(a)


if __name__ == "__main__":
    main()
