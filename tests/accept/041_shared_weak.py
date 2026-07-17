"""Shared[T]: refcounted aliasing; Weak[T]: non-owning handle with upgrade."""
from serpentine import Shared, Weak, share, downgrade, upgrade, move


def main() -> None:
    xs: list[int] = [1, 2]
    s: Shared[list[int]] = share(move(xs))
    t: Shared[list[int]] = s
    t.append(3)
    print(s)
    print(len(s))
    print(s[0] + s[2])
    s[0] = 10
    print(t)
    w: Weak[list[int]] = downgrade(s)
    u: Shared[list[int]] | None = upgrade(w)
    if u is not None:
        print(u[0])
    print(s == t)


if __name__ == "__main__":
    main()
