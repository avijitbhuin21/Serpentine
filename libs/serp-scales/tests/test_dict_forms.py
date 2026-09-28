"""D44: dict forms with non-str keys — replace({...}), rename(index={...}), Series({1: ...})."""
from serp_scales import DataFrame, Series


def main() -> None:
    s: Series = Series([1, 2, 3, 2, None], name="v")
    print(s.replace({1: 10, 2: 20}).tolist(), s.replace([1, 3], 0).tolist(), s.replace(2, -2).tolist())
    print(s.replace({2: "two"}))
    print(Series({1: "a", 2: "b", 10: "j"}))
    print(Series({1.5: 1, 2.5: 2}).index, Series({True: "t", False: "f"}).tolist())
    df: DataFrame = DataFrame({"a": [1, 2, 3], "b": ["x", "y", "x"]})
    print(df.replace({1: 100}).replace({"x": "X"}))
    print(df.replace("y", "Y")["b"].tolist(), df.replace([1, 2], 0)["a"].tolist())
    print(df.rename(index={0: "first", 2: "last"}))
    print(df.rename(columns={"a": "A"}, index={1: 99}).index)
    grades: Series = Series(["b", "a", "c"])
    print(grades.replace({"a": 4.0, "b": 3.0, "c": 2.0}).mean())


if __name__ == "__main__":
    main()
