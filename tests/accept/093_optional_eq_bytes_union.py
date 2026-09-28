"""Accept: Optional == plain-value comparisons and refcounted bytes inside unions/optionals/tuples."""
from __future__ import annotations

from serpentine import Ref, dataclass, move

PIPE: int = -1
DEVNULL: int = -3


def flags(stdin: int | None, stdout: int | None) -> int:
    """Compare Optional[int] operands directly against int constants."""
    f: int = 0
    if stdin == PIPE:
        f += 1
    elif stdin == DEVNULL:
        f += 2
    if stdout != PIPE:
        f += 4
    if 7 == stdout:
        f += 8
    return f


def wrap(raw: bytes, text: bool) -> str | bytes | None:
    """Return a bytes parameter through a union."""
    if text:
        return raw.decode("utf-8")
    return raw


def pair(text: bool) -> tuple[str | bytes | None, str | bytes | None]:
    """Route runtime-produced bytes through union locals into a tuple."""
    out: str | bytes | None = None
    err: str | bytes | None = None
    out = wrap("oops".encode("utf-8"), text)
    err = wrap("zzz".encode("utf-8") + b"!", text)
    return (out, err)


def opt_ret(raw: bytes) -> bytes | None:
    """Return a bytes parameter through an Optional."""
    return raw


@dataclass
class Holder:
    a: str | bytes | None
    b: bytes | None


def show(h: Ref[Holder]) -> None:
    """Print a holder's union fields."""
    print(f"{h.a!r}", f"{h.b!r}")


def main() -> None:
    """Exercise both fixes across several copies of the same handles."""
    print(flags(PIPE, None), flags(DEVNULL, PIPE), flags(None, 7), flags(None, None))
    code: int | None = 3
    print(code == 3, code != 3, 3 == code, code == 4)
    code = None
    print(code == 3, code != 3)

    x = "shared".encode("utf-8")
    for _ in range(5):
        print(f"{wrap(x, False)!r}", f"{opt_ret(x)!r}")
    res = pair(False)
    print(f"{res[0]!r}", f"{res[1]!r}")
    h = Holder(res[0], opt_ret(x))
    show(h)
    h2 = move(h)
    show(h2)
    copies: list[Holder] = [move(h2), Holder(pair(True)[0], None)]
    for c in copies:
        show(c)
    dup: Holder = copies[0]
    show(dup)
    print(f"{x!r}")
    print("done")


if __name__ == "__main__":
    main()
