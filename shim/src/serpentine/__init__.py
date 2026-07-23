"""Runtime no-op shim for the Serpentine ownership vocabulary.

Everything in this module is inert under CPython: the ownership wrappers are
``typing.Annotated`` aliases (invisible to type checkers and the runtime alike)
and ``move`` is the identity function. All semantics live in ``serp check``.
This API is part of the Serpentine language spec; treat changes as spec changes.
"""

import dataclasses as _dataclasses
from typing import Annotated, Callable, Generic, Protocol, TypeVar

__version__ = "0.5.0"

__all__ = ["Owned", "Ref", "Mut", "Shared", "Weak", "move", "native", "Callable",
           "dataclass", "TypeVar", "Generic", "Protocol", "share", "downgrade", "upgrade",
           "PyVal", "pyval_kind"]

T = TypeVar("T")


def dataclass(cls=None, /, **kwargs):
    """Stdlib dataclass, plus empty list/dict field defaults become per-instance factories."""
    def wrap(c):
        for fname in getattr(c, "__annotations__", {}):
            val = c.__dict__.get(fname)
            if isinstance(val, (list, dict)) and not val:
                setattr(c, fname, _dataclasses.field(default_factory=type(val)))
        return _dataclasses.dataclass(c, **kwargs)
    return wrap if cls is None else wrap(cls)


Owned = Annotated[T, "serpentine:owned"]
Ref = Annotated[T, "serpentine:ref"]
Mut = Annotated[T, "serpentine:mut"]
Shared = Annotated[T, "serpentine:shared"]
Weak = Annotated[T, "serpentine:weak"]


def move(x: T) -> T:
    """Mark an ownership transfer; at runtime, return the value unchanged."""
    return x


def native(f: Callable[..., T]) -> Callable[..., T]:
    """Mark a function for native compilation; at runtime, an identity decorator."""
    return f


def share(x: T) -> T:
    """Wrap a value in a refcounted Shared handle; at runtime, identity."""
    return x


def downgrade(x: T) -> T:
    """Create a Weak handle from a Shared one; at runtime, identity."""
    return x


def upgrade(x: T) -> T:
    """Recover a Shared handle from a Weak one (None if dropped); at runtime, identity.

    Under CPython the referent is always alive (the handle keeps it alive), so this
    never returns None — observing the difference means relying on destruction
    timing, which is documented divergence D2.
    """
    return x


PyVal = object
"""Boxed dynamic value annotation; under CPython, values are the real objects."""


def pyval_kind(x) -> str:
    """Kind tag of a dynamic value: the Python type name ('int', 'str', 'list', ...)."""
    return type(x).__name__
