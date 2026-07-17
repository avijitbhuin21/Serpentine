"""Runtime no-op shim for the Serpentine ownership vocabulary.

Everything in this module is inert under CPython: the ownership wrappers are
``typing.Annotated`` aliases (invisible to type checkers and the runtime alike)
and ``move`` is the identity function. All semantics live in ``serp check``.
This API is part of the Serpentine language spec; treat changes as spec changes.
"""

from dataclasses import dataclass
from typing import Annotated, Callable, Generic, TypeVar

__version__ = "0.2.0"

__all__ = ["Owned", "Ref", "Mut", "Shared", "Weak", "move", "native",
           "dataclass", "TypeVar", "Generic", "share", "downgrade", "upgrade"]

T = TypeVar("T")

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
