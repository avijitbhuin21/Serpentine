# serp-reject: SE201 unsupported-feature
"""Reject: @field_validator needs at least one field name."""

from serpentine import PyVal, dataclass, field_validator


@dataclass
class Account:
    name: str

    @field_validator()  # E: SE201
    @classmethod
    def trim(cls, v: PyVal) -> PyVal:
        return str(v).strip()


def main() -> None:
    a = Account(name="ada")
    print(a.name)


if __name__ == "__main__":
    main()
