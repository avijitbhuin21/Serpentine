"""Format specs: the CPython format mini-language for int, float, bool and str in f-strings."""


def ints() -> None:
    vals: list[int] = [0, 7, -42, 1234567, -9876543210]
    for v in vals:
        print(f"[{v:d}][{v:5d}][{v:05d}][{v:+d}][{v: d}][{v:<6}][{v:>6}][{v:^7}][{v:*^9}]")
        print(f"[{v:=+8}][{v:,}][{v:_}][{v:,d}][{v:x}][{v:X}][{v:#x}][{v:#X}][{v:#010x}]")
        print(f"[{v:b}][{v:#b}][{v:_b}][{v:o}][{v:#o}][{v:n}][{v:_x}][{v:>+12,}]")
        print(f"[{v:.2f}][{v:e}][{v:.3e}][{v:g}][{v:%}][{v:.1%}][{v:08.3f}][{v:+.2f}]")
    c: int = 65
    print(f"[{c:c}][{c:>3c}][{c:<3c}]")


def floats() -> None:
    vals: list[float] = [0.0, -0.0, 3.14159, -2.5, 1234567.891, 0.00001, 1e20, 0.000123456,
                         2.675, 0.5, 1.5, 100.0, 123456789.0, 1e-7, 99999.95]
    for v in vals:
        print(f"[{v}][{v:.2f}][{v:.0f}][{v:10.3f}][{v:<10.2f}][{v:^12.4f}][{v:+.3f}][{v: .1f}]")
        print(f"[{v:e}][{v:.2e}][{v:E}][{v:g}][{v:.3g}][{v:G}][{v:.10g}][{v:.1g}]")
        print(f"[{v:%}][{v:.2%}][{v:,}][{v:,.2f}][{v:_.3f}][{v:010.2f}][{v:=+10.2f}]")
        print(f"[{v:.3}][{v:.1}][{v:10}][{v:n}][{v:>12,.1f}][{v:*<14.5g}]")


def strs() -> None:
    vals: list[str] = ["", "ab", "héllo", "a much longer string"]
    for v in vals:
        print(f"[{v:10}][{v:<10}][{v:>10}][{v:^10}][{v:*^11}][{v:.2}][{v:8.3}][{v:s}][{v:>5s}]")
        print(f"[{v!r:>12}][{v!s:^8}]")


def bools() -> None:
    vals: list[bool] = [True, False]
    for v in vals:
        print(f"[{v}][{v:d}][{v:>6}][{v:05d}][{v:.1f}][{v:x}][{v!s:>6}][{v!r:<7}]")


def main() -> None:
    ints()
    floats()
    strs()
    bools()
    n: int = 3
    total: float = 1234.5
    name: str = "widget"
    print(f"{name:<10}|{n:>4}|{total:>12,.2f}|{n / 7:.4f}")


if __name__ == "__main__":
    main()
