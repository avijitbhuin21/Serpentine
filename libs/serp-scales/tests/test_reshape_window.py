"""S2: index alignment, rolling, corr/cov, pivot/pivot_table/melt/crosstab, groupby apply/
transform, iterrows/itertuples."""
from serpentine import PyVal, Owned
from serp_scales import DataFrame, Series, crosstab


def spread(g: Owned[DataFrame]) -> PyVal:
    return float(g["v"].max()) - float(g["v"].min())


def first_plus_len(s: Owned[Series]) -> PyVal:
    return int(s.iloc[0]) + len(s)


def main() -> None:
    a: Series = Series([1, 2, 3], index=["x", "y", "z"], name="v")
    b: Series = Series([10, 20, 30], index=["y", "z", "w"], name="v")
    print(a + b)
    print((a * b).tolist(), (a - b).index, (a + b).name, (a + a.rename("q")).name)
    print(a + a)
    try:
        print(a == b)
    except ValueError as e:
        print("ValueError:", e)
    print((a == a).tolist())

    s: Series = Series([1.0, 2.0, 4.0, None, 8.0, 16.0], name="p")
    print(s.rolling(2).sum())
    print(s.rolling(3).mean().tolist())
    print(s.rolling(3, min_periods=1).max().tolist(), s.rolling(2).count().tolist())
    print(s.rolling(2).min().tolist(), s.rolling(3).std().tolist())
    x: Series = Series([1, 2, 3, 4, 5])
    y: Series = Series([2, 4, 6, 8, 11])
    print(x.corr(y), x.cov(y), x.corr(x), Series([1, 1, 1]).corr(Series([1, 2, 3])))

    df: DataFrame = DataFrame({"k": ["a", "b", "a", "b", "c"], "c": ["p", "p", "q", "q", "p"],
                               "v": [1, 2, 3, 4, 5], "w": [1.5, 2.5, 3.5, 4.5, 5.5]})
    print(df.rolling(2).sum())
    print(df.corr())
    print(df.cov())
    print(df.pivot_table(values="v", index="k", columns="c", aggfunc="sum"))
    print(df.pivot_table(values="v", index="k", columns="c", aggfunc="sum", fill_value=0))
    print(df.pivot_table(index="k", columns="c"))
    print(df.pivot_table(values="w", index=["k", "c"], columns="c", aggfunc="max"))
    print(df.pivot(index="k", columns="c", values="v"))
    dup: DataFrame = DataFrame({"k": ["a", "a"], "c": ["p", "p"], "v": [1, 2]})
    try:
        print(dup.pivot(index="k", columns="c", values="v"))
    except ValueError as e2:
        print("ValueError:", e2)
    long: DataFrame = df.melt(id_vars="k", value_vars=["v", "w"])
    print(long)
    print(long.shape, df.melt(id_vars=["k", "c"], var_name="m", value_name="val").columns)
    print(df.melt().shape)
    print(crosstab(df["k"], df["c"]))
    print(df.groupby("k").apply(spread))
    print(df.groupby("k")["v"].apply(first_plus_len))
    print(df.groupby("k").transform("sum"))
    print(df.groupby("k")["v"].transform("mean").tolist())
    print(df.groupby(["k", "c"])["w"].transform("max").tolist())
    for lbl, row in df.iterrows():
        print(lbl, row["k"], row["v"], row.name)
    for tup in df.itertuples():
        print(tup)
    for tup2 in df.itertuples(index=False):
        print(tup2)
    cnt: int = 0
    for _lbl2, _row2 in df[df["v"] > 3].iterrows():
        cnt += 1
    print(cnt)
    total: float = 0.0
    for lbl3, row3 in df.iterrows():
        if int(lbl3) % 2 == 0:
            total += float(row3["w"])
    print(total)


if __name__ == "__main__":
    main()
