"""Series: construction, dtype, arithmetic, masks, reductions, display."""
from serpentine import PyVal, pyval_kind
from serp_scales import Series, DataFrame


def double(v: PyVal) -> PyVal:
    if pyval_kind(v) == "int":
        return int(v) * 2
    return v


def main() -> None:
    s: Series = Series([1, 2, 3, 4], name="a")
    print(s)
    print(len(s), s.dtype, s.sum(), s.mean(), s.min(), s.max(), s.count())
    print(s.tolist(), s.index, s.name)
    print(s[0], s[3], s.iloc[-1], s.get(9, "missing"))
    t: Series = s + 10
    print(t.tolist(), (s * 2).tolist(), (s - 1).tolist(), (s / 2).tolist())
    print((s // 2).tolist(), (s % 2).tolist(), (s ** 2).tolist(), (-s).tolist())
    print((s + s).tolist(), (s * s).tolist())
    m: Series = s > 2
    print(m.tolist(), m.dtype)
    print((s >= 2).tolist(), (s < 2).tolist(), (s <= 2).tolist())
    print(s.eq(2).tolist(), s.ne(2).tolist())
    print(((s > 1) & (s < 4)).tolist(), ((s < 2) | (s > 3)).tolist(), (~(s > 2)).tolist())
    print(s.loc[s > 2])
    print(s.loc[(s > 1) & (s < 4)].tolist())
    print(s.isin([1, 4]).tolist(), s.between(2, 3).tolist())
    f: Series = Series([1.5, None, 3.0, 2.25])
    print(f)
    print(f.dtype, f.isna().tolist(), f.notna().tolist(), f.count(), f.sum(), f.mean())
    print(f.fillna(0).tolist(), f.dropna().tolist(), f.dropna().index)
    print(f.median(), f.min(), f.max(), f.idxmax(), f.idxmin())
    print(s.std(), s.var(), s.median(), s.quantile(0.25))
    print(s.astype("float64").tolist(), s.astype("str").tolist(), f.fillna(0).astype("int64").tolist())
    o: Series = Series(["x", "yy", "zzz", "yy"], index=["a", "b", "c", "d"], name="w")
    print(o)
    print(o.dtype, o["b"], o.iloc[0], o.nunique(), o.unique())
    print(o.value_counts())
    print(o.str.upper().tolist(), o.str.len().tolist(), o.str.contains("y").tolist())
    print(o.str.startswith("z").tolist(), o.str.replace("y", "Y").tolist(), o.str.slice(0, 2).tolist())
    print(s.apply(double).tolist(), s.map(double).tolist())
    print(s.sort_values(ascending=False))
    print(s.sort_values(ascending=False).index)
    print(f.sort_values().tolist(), f.sort_values(ascending=False).tolist())
    print(s.cumsum().tolist(), s.diff().tolist(), s.shift(1).tolist(), s.shift(-1).tolist())
    print(s.abs().tolist(), (s - 3).abs().tolist(), f.round(1).tolist(), s.clip(2, 3).tolist())
    print(s.head(2).tolist(), s.tail(2).tolist(), s.tail(2).index)
    print(s.describe())
    print(o.describe())
    print(s.any(), (s > 5).any(), (s > 0).all(), (s > 1).all())
    print(s.where(s > 2).tolist(), s.where(s > 2, 0).tolist(), s.mask(s > 2, -1).tolist())
    print(s.replace(2, 20).tolist(), s.argmax(), s.argmin())
    print(Series([]))
    print(Series([], name="e"))
    print(Series(5, index=[0, 1, 2]).tolist(), Series({"a": 1, "b": 2}))
    b: Series = Series([True, False, True])
    print(b, b.sum(), b.mean())
    mixed: Series = Series([1, "a", 2.5, None])
    print(mixed)
    print(mixed.dtype, mixed.count())
    d: Series = Series([1, 2, 3], dtype="float64")
    print(d.dtype, d.tolist())
    s2: Series = s.copy()
    s2[0] = 100
    s2[9] = 9
    print(s2.tolist(), s2.index, s.tolist())
    print(s.to_dict(), o.to_dict(), o.keys())
    fr: DataFrame = o.to_frame()
    print(fr)
    print(s.reset_index().index)
    big: Series = Series([10, 200, 3000])
    print(big)
    print(Series([0.1 + 0.2, 1.0, 2.5]))
    print(Series([1e16, 2.0]))
    try:
        print(s["nope"])
    except KeyError as e:
        print("KeyError:", e)
    try:
        print(s.iloc[10])
    except IndexError as e2:
        print("IndexError:", e2)
    try:
        print((s + Series([1, 2])).tolist())
    except ValueError as e3:
        print("ValueError:", e3)
    try:
        print((o + 1).tolist())
    except TypeError as e4:
        print("TypeError:", e4)


if __name__ == "__main__":
    main()
