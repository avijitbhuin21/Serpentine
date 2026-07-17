"""Runtime no-op shim for the Serpentine ownership vocabulary.

Everything in this module is inert under CPython: the ownership wrappers are
``typing.Annotated`` aliases (invisible to type checkers and the runtime alike)
and ``move`` is the identity function. All semantics live in ``serp check``.
This API is part of the Serpentine language spec; treat changes as spec changes.
"""

from typing import Annotated, Callable, TypeVar

__version__ = "0.1.0"

__all__ = ["Owned", "Ref", "Mut", "Shared", "Weak", "move", "native"]

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
