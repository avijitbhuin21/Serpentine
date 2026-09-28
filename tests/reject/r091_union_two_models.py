# serp-reject: SE201 unsupported-feature
"""Reject: a union field with two model members cannot be dispatched by runtime kind."""
from __future__ import annotations
from serpentine import dataclass, fields_json


@dataclass
class Cat:
    kind: str


@dataclass
class Dog:
    kind: str


@dataclass
class Home:
    pet: Cat | Dog


def main() -> None:
    print(fields_json(Home))  # E: SE201


if __name__ == "__main__":
    main()
