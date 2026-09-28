"""DataFrame: construction, indexing, masks, mutation, sorting, missing data, display."""
from typing import Optional
from serpentine import PyVal, Owned
from serp_scales import DataFrame, Series


def total(row: Owned[Series]) -> PyVal:
    return float(row["a"]) + float(row["b"])


def col_max(col: Owned[Series]) -> PyVal:
    return col.max()


def main() -> None:
    df: DataFrame = DataFrame({"a": [1, 2, 3, 4], "b": [10.5, 20.0, 30.25, 40.0],
                               "name": ["x", "yy", "zzz", "w"]})
    print(df)
    print(df.shape, len(df), df.columns, df.index, df.size, df.empty)
    print(df.dtypes)
    print(df["a"])
    print(df["a"].tolist(), df["name"].tolist(), df["b"].sum(), df["a"].mean())
    df["c"] = df["a"] * 2
    df["d"] = 7
    df["e"] = "k"
    df["f"] = [True, False, True, False]
    df["g"] = 1.5
    print(df)
    print(df.columns)
    mask: Series = df["a"] > 2
    print(df.loc[mask])
    print(df[mask])
    print(df[df["a"] == 2])
    print(df[(df["a"] != 1) & (df["name"] == "zzz")].index)
    print(df[["a", "name"]])
    print(df[["b"]].columns, df[df["a"] > 100].shape)
    print((10 - df["a"]).tolist(), (2 * df["a"]).tolist(), (1 + df["a"]).tolist(), (8 / df["a"]).tolist())
    print(("<" + df["name"]).tolist(), (7 // df["a"]).tolist(), (7 % df["a"]).tolist(), (2 ** df["a"]).tolist())
    print(df.loc[2])
    print(df.iloc[[0, 3]].index, df.iloc[[-1]]["a"].tolist())
    lbl: DataFrame = df.set_index("name")
    print(lbl.loc["yy"]["a"], lbl.loc["yy"].name)
    print(df.loc[(df["a"] > 1) & (df["b"] < 40.0)])
    print(df.loc[df["name"].isin(["x", "w"])].index)
    print(df.loc[~(df["a"] > 2)]["a"].tolist())
    row: Series = df.iloc[1]
    print(row)
    print(row["a"], row["name"], row.name, df.iloc[-1]["a"])
    print(df.head(2))
    print(df.tail(2).index)
    print(df.filter(["a", "name"]))
    print(df.drop(columns=["c", "d", "e", "f", "g"]))
    print(df.drop(columns="g").columns)
    print(df.drop(index=[0, 2]).index, df.drop([1], axis=0).index)
    print(df.rename(columns={"a": "A", "name": "label"}).columns)
    small: DataFrame = df.filter(["a", "b", "name"])
    print(small.sort_values("b", ascending=False))
    print(small.sort_values(["name", "a"]).index)
    print(small.sort_values("name", ascending=[False]).index)
    print(small.sort_index(ascending=False).index)
    print(small.set_index("name"))
    print(small.set_index("name").reset_index())
    print(small.reset_index(drop=True).index, small.reset_index().columns)
    print(small.sum())
    print(small.mean())
    print(small.min(), small.max(), small.count())
    print(small.describe())
    print(small.apply(total, axis=1).tolist())
    print(small.filter(["a", "b"]).apply(col_max).tolist())
    print(small.nlargest(2, "a").index, small.nsmallest(1, "b")["b"].tolist())
    miss: DataFrame = DataFrame({"a": [1, None, 3], "b": [None, "q", "r"], "c": [1.5, 2.5, None]})
    print(miss)
    print(miss.dtypes)
    print(miss.isna())
    print(miss.notna().sum())
    print(miss.fillna(0))
    print(miss.fillna({"a": -1, "b": "?"}))
    print(miss.dropna())
    print(miss.dropna(subset=["a"]).index, miss.dropna(how="all").index)
    recs: DataFrame = DataFrame([{"x": 1, "y": "a"}, {"x": 2, "y": "b"}, {"x": 3, "z": True}])
    print(recs)
    rows: DataFrame = DataFrame([[1, 2], [3, 4]], columns=["p", "q"], index=["r1", "r2"])
    print(rows)
    print(rows.values, rows.to_dict(), rows.to_dict("records"), rows.to_dict("list"))
    print(rows.to_dict("index"))
    print(DataFrame())
    print(DataFrame({"a": [], "b": []}))
    print(DataFrame({"a": [1, 2]}, columns=["a"], index=["u", "v"]))
    dup: DataFrame = DataFrame({"k": [1, 1, 2, 2, 3], "v": [5, 5, 6, 7, 8]})
    print(dup.duplicated().tolist(), dup.duplicated(subset=["k"]).tolist(), dup.duplicated(keep="last").tolist())
    print(dup.drop_duplicates())
    print(dup.drop_duplicates(subset=["k"], keep="last").index)
    print(dup.nunique().tolist(), dup["k"].nunique(), dup["k"].value_counts().tolist())
    print(small.equals(small.copy()), small.equals(dup))
    print(small.astype("str")["a"].tolist(), small.round(1)["b"].tolist())
    print(small.applymap(len_or_id).values)
    print(small.copy().pop("a").tolist())
    ins: DataFrame = small.copy()
    ins.insert(0, "id", [100, 200, 300, 400])
    print(ins.columns, ins["id"].tolist())
    print(small.set_axis(["A", "B", "C"], axis=1).columns, small.set_axis([9, 8, 7, 6]).index)
    got: Optional[Series] = df.get("zzz")
    got2: Optional[Series] = df.get("a")
    print(got is None, got2 is None)
    try:
        print(df["nope"])
    except KeyError as e:
        print("KeyError:", e)
    try:
        df["bad"] = [1, 2]
    except ValueError as e2:
        print("ValueError:", e2)
    try:
        print(DataFrame({"a": [1, 2], "b": [1]}))
    except ValueError as e3:
        print("ValueError:", e3)
    try:
        print(df.iloc[99])
    except IndexError as e4:
        print("IndexError:", e4)


def len_or_id(v: PyVal) -> PyVal:
    return str(v) + "!"


if __name__ == "__main__":
    main()
