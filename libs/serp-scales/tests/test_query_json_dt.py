"""S2: query/eval, to_json/read_json, datetime columns (.dt), display truncation."""
from serp_scales import DataFrame, Series, to_datetime, read_json_text, read_json, read_csv_text


def main() -> None:
    df: DataFrame = DataFrame({"a": [1, 2, 3, 4, 5], "b": [10.0, 20.0, 30.0, 40.0, 50.0],
                               "name": ["x", "y", "z", "x", "w"], "big col": [1, 0, 1, 0, 1]})
    print(df.query("a > 2"))
    print(df.query("a > 1 and b < 45").index, df.query("a > 1 & b < 45").index)
    print(df.query("name == 'x' or a == 5")["a"].tolist())
    print(df.query("name in ['x', 'w']").index, df.query("name not in ['x', 'w']").index)
    print(df.query("not (a > 2)").index, df.query("~(a > 2) | a == 5").index)
    print(df.query("a * 2 + 1 >= b / 10").index, df.query("`big col` == 1").index)
    print(df.query("index >= 3").index, df.query("-a < -3").index, df.query("a % 2 == 0").index)
    print(df.eval("a + b").tolist(), df.eval("a * 2 > 4").tolist(), df.eval("(a + 1) ** 2").tolist())
    try:
        print(df.query("zzz > 1"))
    except KeyError as e:
        print("KeyError:", e)
    try:
        print(df.query("a >"))
    except ValueError as e2:
        print("ValueError:", e2)

    js: DataFrame = DataFrame({"a": [1, 2], "b": [1.5, None], "c": ["p/q", "r"]}, index=["u", "v"])
    print(js.to_json())
    print(js.to_json(orient="records"))
    print(js.to_json(orient="index"))
    print(js.to_json(orient="split"))
    print(js.to_json(orient="values"))
    print(js["a"].to_json(), js["c"].to_json(orient="records"), js["b"].to_json(orient="split"))
    print(read_json_text(js.to_json()))
    print(read_json_text(js.to_json(orient="records"), orient="records"))
    print(read_json_text(js.to_json(orient="index"), orient="index"))
    print(read_json_text(js.to_json(orient="split"), orient="split"))
    print(read_json_text(js.to_json(orient="values"), orient="values"))
    print(read_json_text(DataFrame({"a": [1, 2]}).to_json()).index)
    js.to_json("tmp_serp_scales.json")
    print(read_json("tmp_serp_scales.json").equals(js))

    d: Series = to_datetime(Series(["2024-01-05", "2024-02-29 13:45:10", None, "2023/12/31"], name="d"))
    print(d)
    print(d.dtype, d.tolist())
    print(d.dt.year.tolist(), d.dt.month.tolist(), d.dt.day.tolist(), d.dt.hour.tolist())
    print(d.dt.dayofweek.tolist(), d.dt.dayofyear.tolist(), d.dt.quarter.tolist(), d.dt.days_in_month.tolist())
    print(d.dt.day_name().tolist(), d.dt.month_name().tolist(), d.dt.date.tolist())
    print(d.dt.strftime("%d/%m/%Y %H:%M:%S %a %b %j %y %%").tolist())
    print(d.dt.normalize())
    print(to_datetime(["01/15/2024", "12/01/2023"]).dt.month.tolist())
    print(to_datetime(["15.01.2024"], format="%d.%m.%Y").tolist(), to_datetime("2024-06-01").tolist())
    print(to_datetime(Series(["2024-01-05", "nope"]), errors="coerce").tolist())
    try:
        print(to_datetime(Series(["nope"])))
    except ValueError as e3:
        print("ValueError:", e3)
    ev: DataFrame = DataFrame({"when": ["2024-03-01", "2024-01-15", "2024-02-10"], "v": [3, 1, 2]})
    ev["when"] = to_datetime(ev["when"])
    print(ev)
    print(ev.dtypes)
    print(ev.sort_values("when"))
    print(ev[ev["when"] > "2024-02-01"].index, ev[ev["when"] == "2024-01-15"]["v"].tolist())
    print(ev["when"].min(), ev["when"].max(), ev.set_index("when").index)
    print(ev.set_index("when"))
    print(ev["when"].dt.month.tolist())
    print(ev.to_csv(index=False), ev.to_json(orient="records"), ev.to_json(orient="records", date_format="iso"))
    print(read_csv_text("when,v\n2024-01-01,1\n2024-01-02 06:00:00,2\n", parse_dates=["when"]))
    print(read_csv_text("when,v\n2024-01-01,1\n", parse_dates="when").dtypes.tolist())

    long: Series = Series([i * i for i in range(100)], name="sq")
    print(long)
    print(Series([i for i in range(61)]))
    print(Series([i for i in range(60)]).tail(2))
    wide: DataFrame = DataFrame({"a": [i for i in range(70)]})
    for k in range(24):
        wide["c" + str(k)] = k
    print(wide)
    print(DataFrame({"a": [1.5, 2.5], "b": ["x", "y"]}))


if __name__ == "__main__":
    main()
