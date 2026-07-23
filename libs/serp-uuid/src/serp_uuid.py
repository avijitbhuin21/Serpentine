"""serp-uuid — drop-in `uuid` facade: UUID objects over the runtime CSPRNG.

Pure Serpentine ([P] over the serp_uuid_core rtlib module). uuid4() returns a
UUID object that prints as the dashed lowercase hex string (like stdlib);
.hex/.urn/.version/.variant are properties. Caps: only version 4 generation;
the constructor takes the dashed string (stdlib UUID() accepts many forms);
no .int/.bytes/.fields (int would overflow int64).
"""
from __future__ import annotations
from serpentine import Ref, dataclass
from serp_uuid_core import u4_str

_HEX: str = "0123456789abcdef"


@dataclass
class UUID:
    _s: str

    def __str__(self: Ref[UUID]) -> str:
        return self._s

    @property
    def hex(self: Ref[UUID]) -> str:
        out: list[str] = []
        for i in range(len(self._s)):
            c: str = self._s[i]
            if c != "-":
                out.append(c)
        return "".join(out)

    @property
    def urn(self: Ref[UUID]) -> str:
        return "urn:uuid:" + self._s

    @property
    def version(self: Ref[UUID]) -> int:
        return int(self._s[14:15])

    @property
    def variant(self: Ref[UUID]) -> str:
        c: str = self._s[19]
        if c == "8" or c == "9" or c == "a" or c == "b":
            return "specified in RFC 4122"
        if c == "c" or c == "d":
            return "reserved for Microsoft compatibility"
        if c == "e" or c == "f":
            return "reserved for future definition"
        return "reserved for NCS compatibility"


def _validate(s: str) -> None:
    """Reject strings that are not dashed lowercase RFC 4122 text."""
    if len(s) != 36:
        raise ValueError("badly formed hexadecimal UUID string")
    for i in range(36):
        c: str = s[i]
        if i == 8 or i == 13 or i == 18 or i == 23:
            if c != "-":
                raise ValueError("badly formed hexadecimal UUID string")
        elif _HEX.find(c) < 0:
            raise ValueError("badly formed hexadecimal UUID string")


def uuid4() -> UUID:
    """Return a random version-4 UUID object (uuid.uuid4)."""
    return UUID(u4_str())


def parse(s: str) -> UUID:
    """Build a UUID from dashed lowercase text (subset of uuid.UUID(hex=...))."""
    lowered: str = s.lower()
    _validate(lowered)
    return UUID(lowered)
