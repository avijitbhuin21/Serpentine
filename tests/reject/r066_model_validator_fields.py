# serp-reject: SE201 unsupported-feature
"""Reject: @model_validator takes no field names."""

from serpentine import PyVal, dataclass, model_validator


@dataclass
class Account:
    name: str

    @model_validator("name", mode="before")  # E: SE201
    @classmethod
    def prep(cls, data: PyVal) -> PyVal:
        return data


def main() -> None:
    a = Account(name="ada")
    print(a.name)


if __name__ == "__main__":
    main()
