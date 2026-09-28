"""Series S2 additions: rank / pct_change / cummax / cummin / cumprod / nunique."""
from serp_scales import Series


def main() -> None:
    s: Series = Series([3, 1, 4, 1, 5, None, 9, 2], name="v")
    print(s.rank().tolist())
    print(s.rank(method="min").tolist())
    print(s.rank(method="max").tolist())
    print(s.rank(method="first").tolist())
    print(s.rank(method="dense").tolist())
    print(s.rank(ascending=False).tolist())
    print(s.cummax().tolist())
    print(s.cummin().tolist())
    print(s.cumprod().tolist())
    print(s.nunique(), s.nunique(dropna=False))

    p: Series = Series([100.0, 110.0, 99.0, None, 99.0, 0.0, 5.0])
    print(p.pct_change().tolist())
    print(p.pct_change(periods=2).tolist())
    print(p.rank())

    w: Series = Series(["pear", "apple", "fig", "apple"])
    print(w.rank().tolist(), w.nunique())


if __name__ == "__main__":
    main()
