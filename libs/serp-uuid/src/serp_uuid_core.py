"""serp-uuid core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_uuid_core import ...` (rtlib.py); this file
delegates to the stdlib uuid module for CPython runs.
"""

import uuid as _uuid

__all__ = ["u4_str"]


def u4_str() -> str:
    """Return a random RFC 4122 version-4 UUID string (dashed, lowercase)."""
    return str(_uuid.uuid4())
