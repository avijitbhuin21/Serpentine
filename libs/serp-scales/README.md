# serp-scales (Scales)

pandas-style `DataFrame` / `Series` for Serpentine, written entirely in the Serpentine
subset: the same source compiles to a native binary with `serp` and imports under CPython
(via `serpentine-shim`). Codename **Scales**.

```python
from serp_scales import DataFrame, Series, merge, concat, read_csv

df = DataFrame({"region": ["east", "west", "east"], "units": [10, 5, 7], "price": [2.5, 2.5, 4.0]})
df["revenue"] = df["units"] * df["price"]
big = df.loc[(df["units"] > 5) & df["region"].ne("west")]
print(big)
print(df.groupby("region").sum())
print(df.sort_values("revenue", ascending=False).head(2))
print(merge(df, other, on="region", how="left"))
```

## What works

**Series** — `Series(data, index=, name=, dtype=)` from a list, dict or scalar;
`len`, `s[label]`, `s[label] = v`, `s.iloc[i]`, `s.loc[mask]`, `.values`/`.index`/`.name`/
`.dtype`/`.size`/`.empty`; `tolist`/`to_dict`/`to_frame`/`copy`/`head`/`tail`/`take`/`rename`;
arithmetic `+ - * / // % **` and `.add/.sub/.mul/.div` against a scalar or an equal-length
Series, unary `-`; comparisons `> < >= <=` **returning boolean Series**, plus `.eq/.ne/.gt/
.lt/.ge/.le`; mask algebra `&`, `|`, `^`, `~`; `isin`, `between`, `isna`/`notna`, `fillna`,
`dropna`, `astype`, `abs`, `round`, `clip`, `apply`/`map` (a function), `replace(old, new)`,
`where`/`mask`, `shift`, `diff`, `cumsum`; reductions `sum`/`prod`/`mean`/`median`/`quantile`/
`std`/`var`/`min`/`max`/`count`/`any`/`all`/`argmax`/`argmin`/`idxmax`/`idxmin`/`nunique`/
`unique`/`value_counts`/`describe`; `sort_values`/`sort_index`; the `.str` accessor (`upper`,
`lower`, `strip`, `len`, `contains`, `startswith`, `endswith`, `replace`, `slice`, `cat`).

**DataFrame** — from a dict of lists/scalars, a list of records (dicts) or a list of rows
(with `columns=`), plus `index=`; `df["col"]` → Series, `df["new"] = series | scalar | list`,
`df.loc[mask]`, `df.iloc[i]` (row Series), `.shape`/`.columns`/`.index`/`.dtypes`/`.values`/
`.size`/`.empty`; `head`/`tail`/`take`/`copy`/`filter(items=)`/`select`/`drop(columns=|index=|
labels, axis)`/`rename(columns=)`/`set_axis`/`insert`/`pop`/`get`; `sort_values(by, ascending)`
(multi-column, per-column direction, missing last)/`sort_index`/`nlargest`/`nsmallest`;
`reset_index`/`set_index`; `isna`/`notna`/`fillna(value | dict)`/`dropna(how, subset)`/
`duplicated`/`drop_duplicates`; `astype`/`round`/`applymap`/`map`/`apply(func, axis)`;
numeric reductions `sum`/`mean`/`median`/`std`/`var`/`min`/`max`/`count`/`nunique`/`prod`/
`describe`; `groupby(by, sort=)` with `sum`/`mean`/`min`/`max`/`count`/`size`/`median`/`std`/
`var`/`first`/`last`/`nunique`/`agg(str | list | dict)`/`get_group`/`ngroups` and a single
column via `g["col"].sum_series()` (and `mean_series`, `count_series`, `min_series`,
`max_series`, `agg_series(op)`); `merge`/`df.merge` (`on`/`left_on`+`right_on`, inner/left/
right/outer, suffixes); `concat` (axis 0 with column union, axis 1); `equals`; export with
`to_dict(orient=dict|list|records|index)`, `to_records`, `to_csv(path=None, sep, index,
header)`, and `read_csv(path)` / `read_csv_text(text)` with type inference and RFC 4180 quoting.

`print(df)` / `print(s)` reproduce pandas' text layout (right-aligned cells, common float
precision per column, `NaN` for missing floats, `Name: …, dtype: …` trailers,
`Empty DataFrame` / `Series([], …)` forms, `..`/`...` truncation past 60 rows / 20 columns with
`Length:` / `[N rows x M columns]` trailers).

**Added in 0.2.0** — `Series.rank`/`pct_change`/`cummax`/`cummin`/`cumprod`; index-aligned
Series arithmetic; `rolling(n, min_periods).sum/mean/min/max/std/var/median/count` on Series and
frames; `corr`/`cov`; `pivot_table`/`pivot`/`melt`/`crosstab`; `groupby(...).apply(f)`/
`transform(op)` (frame and `["col"]` forms); `df.query(expr)`/`df.eval(expr)`;
`to_json`/`read_json`/`read_json_text` (orients columns/records/index/split/values, epoch or ISO
dates); datetime columns via `to_datetime(series|list|text, format=, errors=)`,
`read_csv(parse_dates=)` and the `.dt` accessor (`year`…`second`, `dayofweek`, `dayofyear`,
`quarter`, `days_in_month`, `date`, `day_name()`, `month_name()`, `strftime()`, `normalize()`);
`iterrows()`/`itertuples(index=)`; `replace({...})`/`replace([...], v)` on Series and frames;
`rename(index={...})`; tuple/slice indexer keys (`df.loc[mask, "col"]`, `df.loc[a:b]`,
`df.loc[:, cols]`, `df.iloc[a:b]`, `df.iloc[rows, cols]`, `df[a:b]`).

## Divergences from pandas

Serpentine has one static return type per method and no runtime reflection, so a few
spellings differ. Porting a pandas script is mostly an import rewrite plus these:

| pandas | Scales | why |
|---|---|---|
| `s[mask]`, `s.iloc[a:b]` | `s.loc[mask]`, `s.head`/`tail`/`take` | `s[key]` returns a cell; a cell (`PyVal`) cannot share a return union with `Series` |
| `df.loc[mask, "col"] = v` | `df["col"] = df["col"].mask(mask, v)` | `.loc` is an indexer over a copy (no returned borrows) |
| `df.loc[label, "col"]` → scalar | one-cell `Series` (`df.loc[label]["col"]` for the cell) | one static return type per overload |
| `s.map({...})` | `s.replace({...})` or `s.apply(lambda v: ...)` | a parameter cannot accept both a function and a dict |
| `{1: "a", "b": 2}` mixed-key dicts | one key type per literal | dynamic dict literals are typed by their first key |
| `df.columns = [...]` | `df.set_axis([...], axis=1)`, `rename(columns=)` | column storage is keyed by name |
| multi-key groupby / `pivot_table` with several `values` → `MultiIndex` | keys become ordinary columns with a range index; value columns are flattened to `value_colvalue` | no hierarchical index |
| `NaN` cells | `None` cells, printed as `NaN` in float columns / `NaT` in datetime columns | one missing marker for every dtype |
| `s.shape` → `(n,)` | `s.size` / `len(s)` | one-tuples |
| `itertuples()` namedtuples | rows as `list[PyVal]` (`t[0]`, `t[1]`, …) | no namedtuples |
| `Timestamp` cells | `"YYYY-MM-DD HH:MM:SS"` text from `tolist()`/`to_dict()`/`min()`/`max()`; raw `.index`/`.values` field reads show a tagged ISO string | no datetime kind in `PyVal` |
| `concat([a, b])` with live frames | `concat([a.copy(), b.copy()])` or `move()` | a list literal takes ownership |
| 80-column display wrapping | columns truncated at 20 (`...`), rows at 60 (`..`) — no wrapping | — |
| `read_csv` dtype options | inferred `int64`/`float64`/`bool`/`object` + `parse_dates=` | — |

These pandas spellings **do** work as written: `df["a"]`, `df[["a", "b"]]`, `df[mask]`,
`df[1:3]`, `df[(df["a"] > 1) & ~(df["b"] == "x")]`, `df["a"] == 1` / `!=`, `2 * df["a"]`,
`1 - s`, `s1 + s2` (index-aligned), `df.loc[mask]`, `df.loc[label]`, `df.loc[mask, "col"]`,
`df.loc[mask, ["a", "b"]]`, `df.loc[a:b]`, `df.loc[:, "col"]`, `df.iloc[i]`, `df.iloc[[i, j]]`,
`df.iloc[a:b]`, `df.iloc[a:b, j]`, `df.iloc[:, [0, 1]]`, `for i, row in df.iterrows()`,
`df.groupby("k")["v"].sum()` (a `Series`), `df.groupby("k").agg({...})`, `s.loc[mask]`,
`s.replace({1: "a"})`, `df.query("a > 1 and b in ['x', 'y']")`, `df["d"] = to_datetime(df["d"])`,
`df["d"].dt.month`, `df.pivot_table(values=, index=, columns=, aggfunc=)`.

`.loc`/`.iloc` are properties returning indexer objects over a **copy** of the frame, so
`df.iloc[i]` inside a hot loop is O(rows) per access; prefer `df["col"].tolist()` for bulk
reads. Cells are `PyVal` handles (heterogeneous columns, `None` missing), not typed arrays —
Scales is about API fidelity first; typed-column storage (on top of Coil) is the planned
performance step. Nothing here depends on Coil.

## Install

```
serp add serp-scales
pip install serp-scales
```
