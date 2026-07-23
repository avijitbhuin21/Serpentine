"""serp-pathlib — path string helpers plus filesystem queries in the Serpentine subset.

Pure Serpentine ([P]) over serp-os for the syscalls. String helpers accept
both '/' and '\\' separators and Windows drive prefixes; joins are emitted
with '/'. Semantics follow CPython pathlib for the common cases.
"""
from __future__ import annotations
from serpentine import Ref, dataclass
from serp_os_core import exists as _os_exists, is_file as _os_is_file, is_dir as _os_is_dir
from serp_os_core import mkdir as _os_mkdir, rmdir as _os_rmdir, remove as _os_remove
from serp_os_core import listdir as _os_listdir, getcwd as _os_getcwd


def _is_sep(c: str) -> bool:
    return c == "/" or c == "\\"


def _root_len(p: str) -> int:
    if len(p) >= 3 and p[1] == ":" and _is_sep(p[2]):
        return 3
    if len(p) >= 2 and p[1] == ":":
        return 2
    if len(p) >= 1 and _is_sep(p[0]):
        return 1
    return 0


def is_absolute(p: str) -> bool:
    return _root_len(p) > 0


def _strip_trailing(p: str) -> str:
    root: int = _root_len(p)
    end: int = len(p)
    while end > root and _is_sep(p[end - 1]):
        end -= 1
    return p[:end]


def _last_sep(p: str) -> int:
    i: int = len(p) - 1
    while i >= 0:
        if _is_sep(p[i]):
            return i
        i -= 1
    return -1


def join(a: str, b: str) -> str:
    if b == "":
        return a
    if is_absolute(b):
        return b
    if a == "":
        return b
    base: str = _strip_trailing(a)
    if len(base) > 0 and _is_sep(base[len(base) - 1]):
        return base + b
    return base + "/" + b


def name(p: str) -> str:
    base: str = _strip_trailing(p)
    root: int = _root_len(base)
    idx: int = _last_sep(base)
    if idx < root:
        return base[root:]
    return base[idx + 1:]


def parent(p: str) -> str:
    base: str = _strip_trailing(p)
    root: int = _root_len(base)
    if len(base) == root:
        return base if root > 0 else "."
    idx: int = _last_sep(base)
    if idx < 0:
        return "."
    if idx < root:
        return base[:root]
    out: str = _strip_trailing(base[:idx])
    if out == "":
        return p[:root] if root > 0 else "/"
    return out


def _last_dot(s: str) -> int:
    i: int = len(s) - 1
    while i >= 0:
        if s[i] == ".":
            return i
        i -= 1
    return -1


def suffix(p: str) -> str:
    n: str = name(p)
    idx: int = _last_dot(n)
    if idx <= 0:
        return ""
    return n[idx:]


def stem(p: str) -> str:
    n: str = name(p)
    idx: int = _last_dot(n)
    if idx <= 0:
        return n
    return n[:idx]


def with_suffix(p: str, suf: str) -> str:
    if suf != "" and not suf.startswith("."):
        raise ValueError(f"invalid suffix {suf!r} (must start with '.')")
    if suf == ".":
        raise ValueError("invalid suffix '.'")
    n: str = name(p)
    if n == "":
        raise ValueError(f"path {p!r} has an empty name")
    base: str = _strip_trailing(p)
    old: str = suffix(p)
    return base[:len(base) - len(old)] + suf


def parts(p: str) -> list[str]:
    out: list[str] = []
    base: str = _strip_trailing(p)
    root: int = _root_len(base)
    if root > 0:
        out.append(base[:root])
    cur: list[str] = []
    for i in range(root, len(base)):
        c: str = base[i]
        if _is_sep(c):
            if len(cur) > 0:
                out.append("".join(cur))
                cur.clear()
        else:
            cur.append(c)
    if len(cur) > 0:
        out.append("".join(cur))
    return out


def exists(p: str) -> bool:
    return _os_exists(p)


def is_file(p: str) -> bool:
    return _os_is_file(p)


def is_dir(p: str) -> bool:
    return _os_is_dir(p)


def mkdir(p: str) -> None:
    _os_mkdir(p)


def rmdir(p: str) -> None:
    _os_rmdir(p)


def remove(p: str) -> None:
    _os_remove(p)


def listdir(p: str) -> list[str]:
    return _os_listdir(p)


@dataclass
class Path:
    _raw: str

    def __str__(self: Ref[Path]) -> str:
        return self._raw

    def __repr__(self: Ref[Path]) -> str:
        return f"Path({self.as_posix()!r})"

    @staticmethod
    def cwd() -> Path:
        return Path(_os_getcwd())

    def as_posix(self: Ref[Path]) -> str:
        out: list[str] = []
        for i in range(len(self._raw)):
            c: str = self._raw[i]
            if c == "\\":
                out.append("/")
            else:
                out.append(c)
        return "".join(out)

    @property
    def name(self: Ref[Path]) -> str:
        return name(self._raw)

    @property
    def stem(self: Ref[Path]) -> str:
        return stem(self._raw)

    @property
    def suffix(self: Ref[Path]) -> str:
        return suffix(self._raw)

    @property
    def parent(self: Ref[Path]) -> Path:
        return Path(parent(self._raw))

    @property
    def parts(self: Ref[Path]) -> list[str]:
        return parts(self._raw)

    def is_absolute(self: Ref[Path]) -> bool:
        return is_absolute(self._raw)

    def joinpath(self: Ref[Path], other: str) -> Path:
        return Path(join(self._raw, other))

    def __truediv__(self: Ref[Path], other: str) -> Path:
        return Path(join(self._raw, other))

    def with_suffix(self: Ref[Path], suf: str) -> Path:
        return Path(with_suffix(self._raw, suf))

    def with_name(self: Ref[Path], new_name: str) -> Path:
        old: str = name(self._raw)
        if old == "":
            raise ValueError(f"path {self._raw!r} has an empty name")
        if new_name == "" or new_name.find("/") >= 0 or new_name.find("\\") >= 0:
            raise ValueError(f"invalid name {new_name!r}")
        base: str = _strip_trailing(self._raw)
        return Path(base[:len(base) - len(old)] + new_name)

    def exists(self: Ref[Path]) -> bool:
        return _os_exists(self._raw)

    def is_file(self: Ref[Path]) -> bool:
        return _os_is_file(self._raw)

    def is_dir(self: Ref[Path]) -> bool:
        return _os_is_dir(self._raw)

    def mkdir(self: Ref[Path]) -> None:
        _os_mkdir(self._raw)

    def rmdir(self: Ref[Path]) -> None:
        _os_rmdir(self._raw)

    def unlink(self: Ref[Path]) -> None:
        _os_remove(self._raw)

    def iterdir(self: Ref[Path]) -> list[Path]:
        out: list[Path] = []
        names: list[str] = _os_listdir(self._raw)
        for i in range(len(names)):
            out.append(Path(join(self._raw, names[i])))
        return out

    def read_text(self: Ref[Path]) -> str:
        with open(self._raw, "r") as f:
            text: str = f.read()
        return text

    def write_text(self: Ref[Path], text: str) -> int:
        with open(self._raw, "w") as f:
            f.write(text)
        return len(text)

    def read_bytes(self: Ref[Path]) -> bytes:
        with open(self._raw, "rb") as f:
            data: bytes = f.read()
        return data

    def write_bytes(self: Ref[Path], data: bytes) -> int:
        with open(self._raw, "wb") as f:
            f.write(data)
        return len(data)
