# serp-sqlite

Embedded SQLite for Serpentine. Runtime-backed ([R]): native builds load the
system SQLite library dynamically at first use — `winsqlite3.dll` (shipped
with Windows 10+) or `sqlite3.dll` on Windows, `libsqlite3.so.0` on Linux,
`libsqlite3.dylib` on macOS — no link-time dependency. Under CPython the
same imports delegate to the stdlib `sqlite3` module in autocommit mode.

```python
from serp_sqlite import (connect, close, execute, prepare, bind_int,
                         bind_text, step, col_int, col_text, finalize)

db: int = connect("app.db")
execute(db, "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")

st: int = prepare(db, "INSERT INTO users (name) VALUES (?)")
bind_text(st, 1, "ada")
step(st)
finalize(st)

q: int = prepare(db, "SELECT id, name FROM users ORDER BY id")
while step(q):
    print(col_int(q, 0), col_text(q, 1))
finalize(q)
close(db)
```

## API

Handles are opaque ints.

- `connect(path) -> int`, `close(db)`
- `execute(db, sql)` — one statement, no result rows
- `changes(db) -> int`, `last_rowid(db) -> int`
- `prepare(db, sql) -> int`
- `bind_int/bind_float/bind_text/bind_blob(stmt, idx, v)`, `bind_null(stmt, idx)` — 1-based `?` parameters
- `step(stmt) -> bool` — True while a row is available
- `column_count(stmt) -> int`
- `col_type(stmt, i) -> int` — 1=INTEGER, 2=FLOAT, 3=TEXT, 4=BLOB, 5=NULL (0-based columns)
- `col_int/col_float/col_text/col_blob(stmt, i)`
- `reset(stmt)` — rewind, keeping bindings; `finalize(stmt)`

SQLite errors surface as `ValueError` carrying the SQLite error message
(e.g. `no such table: users`) in both worlds.

## Usage rules

- Call column getters only after a `step` that returned True, and use the
  getter matching `col_type` — cross-type getters are not guaranteed to
  agree between worlds.
- Call `column_count` after the first `step` (the CPython delegate defers
  execution to the first step).
- `execute` takes exactly one statement; use multiple calls for scripts.
- If no SQLite library can be found natively, calls raise
  `OSError("SQLite library not found")`.
