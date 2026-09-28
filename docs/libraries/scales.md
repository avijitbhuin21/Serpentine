# Scales (`serp-scales`) — roadmap

> Per-library roadmap. One-line status lives in [../libraries.md](../libraries.md); this file
> is the working checklist. Goal: **the pandas API under a `serp_scales` import root**, with
> the divergences listed in the package README kept to what the language forces.
>
> Markers: `[x]` done · `[ ]` open · **[P]** library-only · **[R]** needs runtime work ·
> **[L]** language-blocked (see blockers at the bottom; LB numbers are local to this file).

## Where we are (2026-09-07) — 0.2.0, ✅ `pandas` drop-in for the everyday surface

`libs/serp-scales/` ships `DataFrame`, `Series`, `merge`, `concat`, `crosstab`, `to_datetime`,
`read_csv`/`read_csv_text`, `read_json`/`read_json_text`, `isna`, `notna`. Storage is one
`list[PyVal]` per column plus a `list[PyVal]` index; every operation returns a fresh object.
Eight library tests (`test_series.py`, `test_series_s2.py`, `test_dataframe.py`,
`test_groupby_merge_csv.py`, `test_reshape_window.py`, `test_query_json_dt.py`,
`test_indexers.py`, `test_dict_forms.py`) are byte-identical across CPython, Backend A and
Backend B. Depends on `serp-json` (to_json/read_json) and `serp-datetime` (datetime columns).
**Scales does not depend on Coil** — typed storage is the performance follow-up (S3).

**Compiler work that shipped with 0.1.0 (D38–D40):** class comparison dunders may return an
object (boolean-mask Series), `&`/`|`/`^`/`~` overload via `__and__`/`__or__`/`__xor__`/
`__invert__`, `__getitem__`/operator results are owned places, user `__eq__`/`__ne__` and
reflected `__radd__`… on classes, `@overload`-typed `__getitem__` (D40). Accept `094`, `097`,
`098`.

**Compiler work that shipped with 0.2.0 (D43–D44):** tuple and slice subscript keys
(`df.loc[mask, "col"]`, `df.iloc[2:5]`, `df.loc[:, ["a", "b"]]`) via multi-argument
`__getitem__` and a builtin `slice` class; non-Copy tuple destructuring in for-loops
(`for i, row in df.iterrows()`); `PyVal` dicts with int/float/bool keys (`s.replace({1: "a"})`,
`Series({1: "a"})`, `rename(index={0: "x"})`); `repr()` escapes control characters like
CPython. Accept `100`, `101`.

## S1 — core surface — SHIPPED

- [x] **[P]** `Series` constructor (list/dict/scalar + `index`/`name`/`dtype`), label
      `__getitem__`/`__setitem__`, `iloc`/`loc[mask]`, dtype inference (`int64`/`float64`/
      `bool`/`object`), pandas text layout.
- [x] **[L→done]** Arithmetic and comparison operators against scalars and Series; mask algebra
      `& | ^ ~` (needed D38).
- [x] **[P]** Reductions, `value_counts`, `describe`, `sort_values`/`sort_index` (stable merge
      sort, missing last), `apply`/`map`, `.str` accessor.
- [x] **[P]** `DataFrame` constructor (dict of lists, records, rows + `columns`/`index`),
      `df[col]`, `df[col] = …`, `loc[mask]`, `iloc[i]`, `shape`/`dtypes`/`values`, `head`/`tail`,
      `filter`/`drop`/`rename`/`insert`/`pop`, `set_index`/`reset_index`, pandas text layout.
- [x] **[P]** Missing data: `isna`/`notna`/`fillna`/`dropna`; `duplicated`/`drop_duplicates`.
- [x] **[P]** `groupby` (single/multi key, `sort=`) with the standard reductions, `agg`,
      `size`, `get_group`, single-column `*_series` reductions.
- [x] **[P]** `merge` (inner/left/right/outer, `on`/`left_on`/`right_on`, suffixes), `concat`
      (axis 0/1, `ignore_index`).
- [x] **[P]** `to_dict` (4 orients), `to_records`, `to_csv`, `read_csv`/`read_csv_text`.

## S2 — surface gaps — SHIPPED 0.2.0 (2026-09-07)

- [x] **[P]** `Series.rank(method=average|min|max|first|dense, ascending=)`, `pct_change(periods=)`
      (no forward-fill — pandas-3 semantics; a zero denominator yields missing where pandas gives
      `inf`), `cummax`/`cummin`/`cumprod` (skipna), `nunique(dropna=)`. Test:
      `tests/test_series_s2.py`.
- [x] **[P]** `pivot_table(values, index, columns, aggfunc, fill_value)` / `pivot` / `melt`,
      `crosstab(s1, s2)`. Several `values` columns become `value_colvalue` flat column names
      (no MultiIndex columns); a list `index` becomes ordinary key columns + range index.
- [x] **[P]** `rolling(n, min_periods).sum/mean/min/max/std/var/median/count` on Series and
      frames, `corr`/`cov` on Series pairs and frames (Pearson, pairwise-complete).
- [x] **[P]** `df.query("a > 1 and name in ['x', 'y']")` / `df.eval("a * 2 + b")` — recursive
      descent over PyVal row vectors: `and or not & | ~`, comparisons, `in`/`not in` lists,
      arithmetic, parentheses, backtick names, `index`; `@var` references are rejected.
- [x] **[P]** `to_json(path, orient=columns|records|index|split|values, date_format=epoch|iso)`
      (compact, ASCII, `\/`-escaped like pandas) and `read_json`/`read_json_text` over
      `serp-json`.
- [x] **[P]** Display truncation: 60 rows → head 5 / `..` / tail 5 with `Length:`/
      `[N rows x M columns]` trailers; more than 20 columns → 10 / `...` / 10. No 80-column
      line wrapping.
- [x] **[P→L→done]** `iterrows()` (needed D43 tuple destructuring) and `itertuples(index=)`
      (rows as `list[PyVal]`, not namedtuples).
- [x] **[P]** datetime columns over `serp-datetime`: `to_datetime(series|list|str, format=,
      errors=)`, `read_csv(parse_dates=)`, dtype `datetime64[ns]`, `NaT`, comparisons against
      date text, `.dt.year/month/day/hour/minute/second/dayofweek/weekday/dayofyear/quarter/
      days_in_month/date`, `.dt.day_name()/month_name()/strftime()/normalize()`. Cells are
      tagged ISO text internally; `tolist()`/`to_dict()`/`min()`/`max()`/csv/json unwrap them
      to `"YYYY-MM-DD HH:MM:SS"` text (raw `.index`/`.values` field reads show the tag).
- [x] **[P]** `groupby(...).apply(f)` (Series of per-group results) and `transform(op)` (frame /
      Series aligned to the original rows) for frames and `["col"]` selections.
- [x] **[P]** Index alignment in Series arithmetic (sorted union of labels, missing where a
      label is absent, name kept only when both agree); comparisons still require identically
      labelled operands like pandas.
- [x] **[L→done]** `df.loc[mask, "col"]`, `df.loc[mask, ["a", "b"]]`, `df.loc[a:b]` (inclusive
      labels), `df.loc[:, "col"]`, `df.loc[label, cols]`, `df.iloc[a:b]`, `df.iloc[a:b, j]`,
      `df.iloc[[i, j], [p, q]]`, `df.iloc[mask, j]`, `df[a:b]` (D43). Test:
      `tests/test_indexers.py`.
- [x] **[L→done]** `replace({...})` / `replace([..], v)` on Series and frames,
      `rename(index={...})`, `Series({1: "a"})` (D44). Test: `tests/test_dict_forms.py`.

## S3 — performance (after Coil)

- [ ] **[R]** Typed column storage: `list[float]`/`list[int]`/`list[str]` blocks behind the same
      API (or Coil arrays for numeric columns) instead of boxed `PyVal` cells.
- [ ] **[P]** `.loc`/`.iloc` without copying the frame — needs either `Shared` storage or a
      language-level borrowed-view return (LB1).
- [ ] **[P]** Hash-based groupby keys without the `kind:text` string round-trip.
- [ ] **[P]** Parallel column reductions over `spawn` (D9).

## Divergences that are language-shaped (see README table)

`s[mask]` (a cell is a `PyVal`, which cannot share a union with `Series` — LB2; spell it
`s.loc[mask]`), `s.iloc[a:b]` (same union: `s.head`/`tail`/`take`), `s.map({...})` (a
`Callable | dict` parameter is not expressible — use `s.replace({...})` or a lambda),
`df.loc[mask, "col"] = v` (`.loc` is a copy — LB1; use `df["col"] = df["col"].mask(mask, v)`),
`df.loc[label, "col"]` scalar (returns a one-cell `Series`; `df.loc[label]["col"]` for the
cell), `MultiIndex` (flat `value_colvalue` names / key columns), mixed-key dict literals,
`df.columns = …`, `s.shape` one-tuples, 80-column display wrapping, raw `.index`/`.values`
field reads of datetime cells. **Cleared by D39/D40:** `df[mask]`, `df[[cols]]`, `==`/`!=`
masks, reflected scalar operators, `df.loc[label]`, `groupby()["v"].sum()` as a Series.
**Cleared by D43/D44:** `df.loc[mask, "col"]`, `df.iloc[2:5]`, `df.loc[:, cols]`,
`for i, row in df.iterrows()`, `replace({1: "a"})`, `Series({1: "a"})`, `rename(index={...})`.

## Language blockers

- **LB1 — returned borrows.** `df.loc`/`df.iloc` must copy because a property cannot return a
  view that borrows `self` (SE209). A scoped "view object" return would remove the O(rows)
  cost of `df.iloc[i]` and make `df.loc[mask, "col"] = v` writable.
- **LB2 — `PyVal` as a union member.** `s[key]` / `s.iloc[key]` cannot be overloaded to return
  either a cell or a `Series` because `PyVal | Series` is not a legal union; `s.loc[mask]` and
  `s.head/tail/take` are the spellings.
- ~~**LB3 — heterogeneous-key PyVal dicts.**~~ Done (D44): int/float/bool keys; a single
  literal must keep one key type.
- ~~**LB4 — tuple/slice keys on `__getitem__`.**~~ Done (D43).
- **LB5 — `Callable | T` parameter unions.** `s.map(func_or_dict)`, `s.apply(func_or_name)`
  and `agg(func)` need a parameter that accepts either a function or a value; today `map`/`apply`
  take functions only and `replace`/`agg` take values only.
