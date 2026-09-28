"""D43 indexer spellings: df.loc[mask, "col"], df.loc[mask, [cols]], df.loc[a:b], df.loc[:, col],
df.iloc[a:b], df.iloc[a:b, j], df.iloc[[i, j], [0, 1]], df[a:b]."""
from serp_scales import DataFrame, Series


def main() -> None:
    df: DataFrame = DataFrame({"a": [1, 2, 3, 4, 5], "b": [10.0, 20.0, 30.0, 40.0, 50.0],
                               "name": ["x", "y", "z", "x", "w"]})
    mask: Series = df["a"] > 2
    print(df.loc[mask, "b"])
    print(df.loc[mask, ["a", "name"]])
    print(df.loc[df["name"] == "x", "a"].tolist(), df.loc[mask, ["b"]].shape)
    print(df.loc[1:3])
    print(df.loc[:2, "name"].tolist(), df.loc[3:, ["a", "b"]].index, df.loc[:, "a"].sum())
    print(df.loc[2, ["a", "name"]])
    print(df.loc[2, "b"])
    print(df.iloc[1:3])
    print(df.iloc[:2, 0].tolist(), df.iloc[-2:, [0, 2]], df.iloc[::2].index, df.iloc[::-1]["a"].tolist())
    print(df.iloc[[0, 4], 1].tolist(), df.iloc[[0, 4], [1, 2]].columns, df.iloc[3, [0, 1]])
    print(df.iloc[mask, 0].tolist(), df.iloc[:, 2].tolist())
    print(df[1:3], df[3:].index, df[:1]["a"].tolist(), df[::-2].index)
    lbl: DataFrame = df.set_index("name")
    print(lbl.loc["x", "a"].tolist(), lbl.loc["y":"z"].index, lbl.loc["x", ["a", "b"]])
    print(lbl.loc["x", "a"])
    try:
        print(df.loc[9, "a"])
    except KeyError as e:
        print("KeyError:", e)
    try:
        print(df.iloc[1:2, 7])
    except IndexError as e2:
        print("IndexError:", e2)
    try:
        print(df.loc[mask, "zzz"])
    except KeyError as e3:
        print("KeyError:", e3)


if __name__ == "__main__":
    main()
