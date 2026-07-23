"""serp-os — drop-in `os` facade (env + filesystem subset) over serp_os_core.

Pure Serpentine ([P] over the serp_os_core rtlib module): the same source
compiles natively and imports under CPython. Stdlib names and signatures:
getenv(key, default=None), putenv/unsetenv, getcwd/chdir, mkdir/rmdir/
remove/unlink, listdir(path=".").
Divergences: error messages are normalized (not CPython's "[Errno N] ..."
forms); listdir() is always sorted; putenv() updates getenv() (CPython
decouples them); no environ mapping object.
"""
from __future__ import annotations
from serp_os_core import getenv as _core_getenv, has_env as _core_has_env
from serp_os_core import setenv as _core_setenv, unsetenv as _core_unsetenv
from serp_os_core import getcwd as _core_getcwd, chdir as _core_chdir
from serp_os_core import mkdir as _core_mkdir, rmdir as _core_rmdir
from serp_os_core import remove as _core_remove, listdir as _core_listdir


def getenv(key: str, default: str | None = None) -> str | None:
    """Return the environment variable's value, or `default` when unset."""
    if _core_has_env(key):
        return _core_getenv(key)
    return default


def putenv(name: str, value: str) -> None:
    """Set an environment variable (also visible through getenv)."""
    _core_setenv(name, value)


def unsetenv(name: str) -> None:
    """Remove an environment variable (no error if it was unset)."""
    _core_unsetenv(name)


def getcwd() -> str:
    """Return the current working directory."""
    return _core_getcwd()


def chdir(path: str) -> None:
    """Change the working directory."""
    _core_chdir(path)


def mkdir(path: str) -> None:
    """Create one directory level."""
    _core_mkdir(path)


def rmdir(path: str) -> None:
    """Remove an empty directory."""
    _core_rmdir(path)


def remove(path: str) -> None:
    """Remove a file."""
    _core_remove(path)


def unlink(path: str) -> None:
    """Remove a file (alias of remove, like CPython)."""
    _core_remove(path)


def listdir(path: str = ".") -> list[str]:
    """Return the directory listing (always sorted, unlike CPython)."""
    return _core_listdir(path)
