# serp-tomllib

Read-only TOML parsing written in the Serpentine subset. Values are
kind-tagged `TVal` dataclasses (`kind` in `str/int/float/bool/arr/table`),
mirroring serp-json's `JVal` shape.

## Supported TOML

Comments, bare/quoted/dotted keys, basic and literal strings (with
`\n \t \r \" \\ \uXXXX` escapes), decimal integers (underscores ok), floats,
booleans, single-line arrays, `[a.b]` table headers.

**Not supported** (raises `ValueError`): arrays of tables, inline tables,
multi-line strings/arrays, dates/times, hex/oct/bin integers. This covers the
`serp.toml` files the toolchain itself uses.

## API

- `loads(text) -> TVal` — root table.
- `has / keys / get_str / get_int / get_float / get_bool (t, key)` —
  navigation helpers (`KeyError` on a missing key, `ValueError` on a kind
  mismatch). Nested tables: navigate via `t.tbl["name"]`.
- `describe(t) -> str` — canonical debug rendering.

## Install

```
serp add serp-tomllib
pip install serp-tomllib
```
