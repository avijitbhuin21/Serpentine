"""First-class functions: refs, capturing lambdas, stored callbacks, returns."""
from serpentine import Callable, dataclass


def double(x: int) -> int:
    return x * 2


def shout(s: str) -> str:
    return s.upper() + "!"


def apply_twice(f: Callable[[int], int], v: int) -> int:
    return f(f(v))


@dataclass
class Button:
    label: str
    on_click: Callable[[int], str]


def make_prefixer(prefix: str) -> Callable[[str], str]:
    return lambda s: prefix + s


def main() -> None:
    f: Callable[[int], int] = double
    print(f(21))
    print(apply_twice(double, 3))

    n: int = 10
    add_n: Callable[[int], int] = lambda x: x + n
    print(add_n(5))
    print(apply_twice(add_n, 1))

    fs: list[Callable[[int], int]] = [double, add_n]
    total: int = 0
    for i in range(2):
        g: Callable[[int], int] = fs[i]
        total = total + g(7)
    print(total)

    b: Button = Button("ok", lambda code: f"clicked {code}")
    print(b.label)
    print(b.on_click(3))

    p: Callable[[str], str] = make_prefixer(">> ")
    print(p("hi"))
    print(apply_twice(lambda x: x - 1, 10))

    sf: Callable[[str], str] = shout
    combo: Callable[[str], str] = lambda s: sf(p(s))
    print(combo("go"))


if __name__ == "__main__":
    main()
