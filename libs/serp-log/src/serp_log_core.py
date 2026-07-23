"""CPython delegate for the serp_log_core runtime module.

Under native compilation these calls map to runtime primitives holding the
process-global logging state (DECISIONS.md D12); under CPython this module
provides the same behavior with a plain dict and sys.stderr.
"""

import sys

_KV: dict = {}


def lg_set(key: str, val: str) -> None:
    """Store one config/registry entry."""
    _KV[key] = val


def lg_get(key: str) -> str:
    """Read one config/registry entry ('' when unset)."""
    return _KV.get(key, "")


def lg_write_err(line: str) -> None:
    """Write one line to stderr (console log sink)."""
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
