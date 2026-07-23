"""serp-os core CPython delegate: native builds use runtime primitives instead.

The Serpentine compiler intercepts `from serp_os_core import ...` (rtlib.py) and
never reads this file. Error messages are normalized on BOTH sides (here and
in the runtime) so dual runs stay byte-identical: FileNotFoundError uses
"No such file or directory: <repr>", mkdir-on-existing raises
OSError("File exists: <repr>"), etc. getenv returns "" when unset;
listdir is always sorted.
"""

import os as _os

__all__ = ["getenv", "has_env", "setenv", "unsetenv", "getcwd", "chdir",
           "exists", "is_file", "is_dir", "mkdir", "rmdir", "remove", "listdir"]


def getenv(name: str) -> str:
    """Return the environment variable's value, or "" when unset."""
    return _os.environ.get(name, "")


def has_env(name: str) -> bool:
    """Return whether the environment variable is set."""
    return name in _os.environ


def _check_name(name: str) -> None:
    """Reject names that CPython/putenv would refuse, with one message."""
    if name == "" or "=" in name or "\x00" in name:
        raise ValueError("illegal environment variable name")


def setenv(name: str, value: str) -> None:
    """Set an environment variable (ValueError on illegal name/value)."""
    _check_name(name)
    if "\x00" in value:
        raise ValueError("embedded null character")
    _os.environ[name] = value


def unsetenv(name: str) -> None:
    """Remove an environment variable (no error if it was unset)."""
    _check_name(name)
    _os.environ.pop(name, None)


def getcwd() -> str:
    """Return the current working directory."""
    return _os.getcwd()


def chdir(p: str) -> None:
    """Change the working directory (normalized errors)."""
    try:
        _os.chdir(p)
    except FileNotFoundError:
        raise FileNotFoundError(f"No such file or directory: {p!r}") from None
    except OSError:
        raise OSError(f"Not a directory: {p!r}") from None


def exists(p: str) -> bool:
    """Return whether the path exists."""
    return _os.path.exists(p)


def is_file(p: str) -> bool:
    """Return whether the path is a regular file."""
    return _os.path.isfile(p)


def is_dir(p: str) -> bool:
    """Return whether the path is a directory."""
    return _os.path.isdir(p)


def mkdir(p: str) -> None:
    """Create one directory level (normalized errors)."""
    try:
        _os.mkdir(p)
    except FileExistsError:
        raise OSError(f"File exists: {p!r}") from None
    except FileNotFoundError:
        raise FileNotFoundError(f"No such file or directory: {p!r}") from None
    except OSError:
        raise OSError(f"mkdir failed: {p!r}") from None


def rmdir(p: str) -> None:
    """Remove an empty directory (normalized errors)."""
    try:
        _os.rmdir(p)
    except FileNotFoundError:
        raise FileNotFoundError(f"No such file or directory: {p!r}") from None
    except OSError:
        raise OSError(f"Directory not empty: {p!r}") from None


def remove(p: str) -> None:
    """Remove a file (normalized errors)."""
    try:
        _os.remove(p)
    except FileNotFoundError:
        raise FileNotFoundError(f"No such file or directory: {p!r}") from None
    except OSError:
        raise OSError(f"Cannot remove: {p!r}") from None


def listdir(p: str) -> list:
    """Return the sorted directory listing (normalized errors)."""
    try:
        return sorted(_os.listdir(p))
    except FileNotFoundError:
        raise FileNotFoundError(f"No such file or directory: {p!r}") from None
    except OSError:
        raise OSError(f"Not a directory: {p!r}") from None
