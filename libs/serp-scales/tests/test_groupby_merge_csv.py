"""groupby/agg, merge, concat and CSV round-trip."""
from serp_scales import DataFrame, Series, merge, concat, read_csv, read_csv_text


def main() -> None:
    sales: DataFrame = DataFrame({
        "region": ["east", "west", "east", "north", "west", "east"],
        "product": ["a", "a", "b", "b", "b", "a"],
        "units": [10, 5, 7, 3, 8, 2],
        "price": [2.5, 2.5, 4.0, 4.0, 4.0, 2.5],
    })
    sales["revenue"] = sales["units"] * sales["price"]
    print(sales)
    g = sales.groupby("region")
    print(g.ngroups)
    print(g.sum())
    print(g.mean())
    print(g.count())
    print(g.size())
    print(g.min())
    print(g.max())
    print(g.first())
    print(g["units"].sum())
    print(g["revenue"].mean().tolist())
    print(g["product"].count().tolist(), g["product"].agg("nunique").tolist())
    print(g.agg({"units": "sum", "revenue": "mean"}))
    print(g.agg({"units": ["sum", "max"]}))
    print(g.agg("sum"))
    print(sales.groupby(["region", "product"]).sum())
    print(sales.groupby(["region", "product"])["units"].sum())
    print(sales.groupby("region", sort=False).size().index)
    print(g.get_group("west"))
    print(sales.groupby("product").nunique())
    print(sales.groupby("product").median())
    holes: DataFrame = DataFrame({"k": ["a", None, "a", "b"], "v": [1, 2, 3, 4]})
    print(holes.groupby("k").sum())
    left: DataFrame = DataFrame({"id": [1, 2, 3, 4], "name": ["ann", "bob", "cy", "dee"]})
    right: DataFrame = DataFrame({"id": [3, 1, 5, 1], "score": [30, 10, 50, 11], "name": ["c", "a", "e", "a2"]})
    print(merge(left, right, on="id"))
    print(left.merge(right, on="id", how="left"))
    print(merge(left, right, on="id", how="right"))
    print(merge(left, right, on="id", how="outer"))
    print(merge(left, right, on="id", suffixes=["_l", "_r"]).columns)
    other: DataFrame = DataFrame({"key": [2, 4], "extra": ["two", "four"]})
    print(merge(left, other, left_on="id", right_on="key"))
    multi_l: DataFrame = DataFrame({"a": [1, 1, 2], "b": ["x", "y", "x"], "v": [1, 2, 3]})
    multi_r: DataFrame = DataFrame({"a": [1, 2, 2], "b": ["x", "x", "z"], "w": [9, 8, 7]})
    print(merge(multi_l, multi_r, on=["a", "b"]))
    print(merge(multi_l, multi_r))
    top: DataFrame = DataFrame({"a": [1, 2], "b": ["p", "q"]})
    bottom: DataFrame = DataFrame({"a": [3], "c": [True]})
    print(concat([top.copy(), bottom.copy()]))
    print(concat([top.copy(), bottom.copy()], ignore_index=True).index)
    print(concat([top.copy(), bottom.copy()], axis=1))
    print(concat([top.copy(), top.rename(columns={"a": "a2", "b": "b2"})], axis=1))
    text: str = sales.to_csv()
    print(text)
    print(sales.to_csv(index=False, header=False))
    print(DataFrame({"t": ['he said "hi"', "a,b", "plain"], "n": [1, None, 3]}).to_csv(index=False))
    back: DataFrame = read_csv_text(text)
    print(back)
    print(back.dtypes)
    print(back.equals(sales))
    path: str = "tmp_serp_scales.csv"
    sales.to_csv(path, index=False)
    loaded: DataFrame = read_csv(path)
    print(loaded)
    print(loaded.dtypes)
    print(loaded["revenue"].sum(), loaded.index)
    print(read_csv_text("x;y\n1;a\n2;b\n", sep=";"))
    print(read_csv_text("1,2\n3,4\n", header=False))
    print(read_csv_text('a,b,c\n1,"x,y",True\n,"say ""hi""",false\n'))
    print(read_csv_text("a,b\n1.5,NaN\n2,\n"))
    print(read_csv_text("").shape)
    try:
        print(merge(top, other))
    except ValueError as e:
        print("ValueError:", e)
    try:
        print(g.get_group("south"))
    except KeyError as e2:
        print("KeyError:", e2)
    try:
        print(g.agg({"units": "bogus"}))
    except ValueError as e3:
        print("ValueError:", e3)


if __name__ == "__main__":
    main()
