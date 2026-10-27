"""serp-sqlite core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_sqlite_core import ...` (rtlib.py); natively
the runtime loads the system SQLite library dynamically (winsqlite3.dll on
Windows, libsqlite3 elsewhere) and drives the C prepare/step API. This file
emulates the same handle-based API over the stdlib sqlite3 module for
CPython runs (autocommit mode, matching the C API's default).

Handles are opaque ints. Statement flow: prepare -> bind_* (1-based
indices) -> step (True while a row is available) -> col_* getters
(0-based columns) -> reset/finalize. Call column getters only after a
successful step, and call the getter matching col_type (1=INTEGER,
2=FLOAT, 3=TEXT, 4=BLOB, 5=NULL). SQLite errors surface as ValueError
with the SQLite error message in both worlds.
"""

import sqlite3 as _sq

__all__ = ["connect", "close", "execute", "changes", "last_rowid", "prepare",
           "bind_int", "bind_float", "bind_text", "bind_blob", "bind_null",
           "step", "column_count", "col_type", "col_int", "col_float",
           "col_text", "col_blob", "reset", "finalize"]

_dbs: dict[int, list] = {}
_stmts: dict[int, "_Stmt"] = {}
_counter: list[int] = [0, 0]


class _Stmt:
    """Cursor-backed emulation of one prepared SQLite statement."""

    def __init__(self, dbh: int, sql: str) -> None:
        self.dbh = dbh
        self.sql = sql
        self.params: dict[int, object] = {}
        self.cur = None
        self.row = None
        self.done = False


def _db(h: int) -> list:
    """Look up a database record or raise the normalized handle error."""
    rec = _dbs.get(h)
    if rec is None:
        raise ValueError("invalid database handle")
    return rec


def _stmt(h: int) -> _Stmt:
    """Look up a statement record or raise the normalized handle error."""
    st = _stmts.get(h)
    if st is None:
        raise ValueError("invalid statement handle")
    return st


def connect(path: str) -> int:
    """Open (or create) a database file and return its handle."""
    try:
        conn = _sq.connect(path, isolation_level=None)
        conn.execute("SELECT 1").fetchone()
    except _sq.Error as e:
        raise ValueError(str(e))
    _counter[0] += 1
    _dbs[_counter[0]] = [conn]
    return _counter[0]


def close(db: int) -> None:
    """Close a database handle."""
    rec = _db(db)
    rec[0].close()
    del _dbs[db]


def execute(db: int, sql: str) -> None:
    """Run a single SQL statement without result rows."""
    rec = _db(db)
    try:
        rec[0].execute(sql)
    except _sq.Error as e:
        raise ValueError(str(e))


def changes(db: int) -> int:
    """Rows changed by the most recent INSERT/UPDATE/DELETE."""
    rec = _db(db)
    try:
        return rec[0].execute("SELECT changes()").fetchone()[0]
    except _sq.Error as e:
        raise ValueError(str(e))


def last_rowid(db: int) -> int:
    """Rowid of the most recent successful INSERT."""
    rec = _db(db)
    try:
        return rec[0].execute("SELECT last_insert_rowid()").fetchone()[0]
    except _sq.Error as e:
        raise ValueError(str(e))


def in_tx(db: int) -> bool:
    """True while an explicit or implicit transaction is open (not autocommit)."""
    return _db(db)[0].in_transaction


def prepare(db: int, sql: str) -> int:
    """Prepare a statement and return its handle (execution is deferred to step)."""
    rec = _db(db)
    if sql.strip() == "":
        raise ValueError("empty SQL statement")
    try:
        rec[0].execute("EXPLAIN " + sql).fetchall()
    except _sq.OperationalError as e:
        if not str(e).startswith("Could not decode to UTF-8"):
            raise ValueError(str(e))
    except _sq.ProgrammingError as e:
        m = str(e)
        if "Incorrect number of bindings" in m and " uses " in m:
            n = int(m.split(" uses ")[1].split(",")[0])
            try:
                rec[0].execute("EXPLAIN " + sql, (None,) * n).fetchall()
            except _sq.Error as e2:
                raise ValueError(str(e2))
        else:
            raise ValueError(m)
    except _sq.Error as e:
        raise ValueError(str(e))
    _counter[1] += 1
    _stmts[_counter[1]] = _Stmt(db, sql)
    return _counter[1]


def _bind(stmt: int, idx: int, v: object) -> None:
    """Store one 1-based parameter binding on a statement."""
    st = _stmt(stmt)
    st.params[idx] = v


def bind_int(stmt: int, idx: int, v: int) -> None:
    """Bind an integer parameter (1-based index)."""
    _bind(stmt, idx, v)


def bind_float(stmt: int, idx: int, v: float) -> None:
    """Bind a float parameter (1-based index)."""
    _bind(stmt, idx, v)


def bind_text(stmt: int, idx: int, v: str) -> None:
    """Bind a text parameter (1-based index)."""
    _bind(stmt, idx, v)


def bind_blob(stmt: int, idx: int, v: bytes) -> None:
    """Bind a blob parameter (1-based index)."""
    _bind(stmt, idx, v)


def bind_null(stmt: int, idx: int) -> None:
    """Bind NULL to a parameter (1-based index)."""
    _bind(stmt, idx, None)


def _run(st: _Stmt) -> None:
    """Execute the statement's SQL with its current bindings."""
    n = max(st.params.keys(), default=0)
    args = tuple(st.params.get(i) for i in range(1, n + 1))
    try:
        st.cur = _db(st.dbh)[0].execute(st.sql, args)
    except _sq.Error as e:
        raise ValueError(str(e))


def step(stmt: int) -> bool:
    """Advance the statement; True while a result row is available."""
    st = _stmt(stmt)
    if st.done:
        return False
    if st.cur is None:
        _run(st)
    try:
        st.row = st.cur.fetchone()
    except _sq.Error as e:
        raise ValueError(str(e))
    if st.row is None:
        st.done = True
        return False
    return True


def column_count(stmt: int) -> int:
    """Number of result columns (0 for statements without results)."""
    st = _stmt(stmt)
    if st.cur is None:
        _run(st)
    if st.cur.description is None:
        return 0
    return len(st.cur.description)


def _col(stmt: int, i: int) -> object:
    """Fetch column i of the current row."""
    st = _stmt(stmt)
    if st.row is None:
        return None
    return st.row[i]


def col_type(stmt: int, i: int) -> int:
    """SQLite storage class of column i: 1=INT, 2=FLOAT, 3=TEXT, 4=BLOB, 5=NULL."""
    v = _col(stmt, i)
    if v is None:
        return 5
    if isinstance(v, bool) or isinstance(v, int):
        return 1
    if isinstance(v, float):
        return 2
    if isinstance(v, str):
        return 3
    return 4


def col_int(stmt: int, i: int) -> int:
    """Column i as an integer (call when col_type is 1)."""
    v = _col(stmt, i)
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def col_float(stmt: int, i: int) -> float:
    """Column i as a float (call when col_type is 2)."""
    v = _col(stmt, i)
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def col_text(stmt: int, i: int) -> str:
    """Column i as text (call when col_type is 3)."""
    v = _col(stmt, i)
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def col_blob(stmt: int, i: int) -> bytes:
    """Column i as a blob (call when col_type is 4)."""
    v = _col(stmt, i)
    if v is None:
        return b""
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        return v.encode("utf-8")
    return b""


def reset(stmt: int) -> None:
    """Rewind a statement for re-execution (bindings are kept)."""
    st = _stmt(stmt)
    st.cur = None
    st.row = None
    st.done = False


def finalize(stmt: int) -> None:
    """Destroy a statement handle."""
    _stmt(stmt)
    del _stmts[stmt]
