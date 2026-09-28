"""A tiny model base whose classmethods are inherited across modules."""

from __future__ import annotations

from typing import Self

from serpentine import (PyVal, Ref, dataclass, fields_build, fields_json, fields_of,
                        pyval_kind)


class BadPayload(Exception):
    pass


@dataclass
class Model:
    def to_dict(self: Ref[Model]) -> dict[str, PyVal]:
        """Every field of this model as a plain dict."""
        return fields_of(self)

    @classmethod
    def from_dict(cls, data: PyVal) -> Self:
        """Build an instance of the receiving class out of a PyVal mapping."""
        if pyval_kind(data) != "dict":
            raise BadPayload("expected an object, got " + pyval_kind(data))
        return fields_build(cls, data)

    @classmethod
    def schema(cls) -> str:
        """The build-time field table of the receiving class as JSON."""
        return fields_json(cls)

    @staticmethod
    def kind() -> str:
        """A constant tag shared by every model."""
        return "model"
