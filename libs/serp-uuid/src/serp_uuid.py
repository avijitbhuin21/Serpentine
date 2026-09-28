"""serp-uuid — drop-in `uuid` facade: UUID objects over the runtime CSPRNG.

Pure Serpentine ([P] over the serp_uuid_core rtlib module). uuid4() returns a
UUID object that prints as the dashed lowercase hex string (like stdlib);
.hex/.urn/.version/.variant are properties. UUID(text) accepts the dashed,
bare-32-hex, braced and urn:uuid: spellings in any case. Caps: only version 4
generation; no .int/.bytes/.fields (int would overflow int64) and no
bytes=/fields= keyword constructors.
"""
from __future__ import annotations
from serpentine import Mut, Ref, dataclass
from serp_uuid_core import u4_str

_HEX: str = "0123456789abcdef"


@dataclass
class UUID:
    _s: str

    def __post_init__(self: Mut[UUID]) -> None:
        self._s = _normalized(self._s)

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


def _normalized(s: str) -> str:
    """Canonical dashed lowercase text from any accepted UUID spelling."""
    t: str = s.strip().lower()
    if t.startswith("urn:uuid:"):
        t = t[9:]
    if t.startswith("{") and t.endswith("}"):
        t = t[1:len(t) - 1]
    if len(t) == 32:
        t = f"{t[:8]}-{t[8:12]}-{t[12:16]}-{t[16:20]}-{t[20:]}"
    _validate(t)
    return t


def uuid4() -> UUID:
    """Return a random version-4 UUID object (uuid.uuid4)."""
    return UUID(u4_str())


def parse(s: str) -> UUID:
    """Build a UUID from text (dashed, plain-hex, braced or urn spellings)."""
    return UUID(s)
