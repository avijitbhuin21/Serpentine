"""serp-sqlite — drop-in `sqlite3` replacement (subset) in the Serpentine subset.

`connect()` returns a `Connection`; cursors execute SQL with `?` parameters and
fetch rows as dynamic values (PyVal lists), like sqlite3 row tuples. SQLite
errors raise `OperationalError` (under `DatabaseError` / `Error`) with the
SQLite message. Transactions follow sqlite3's legacy (3.11) rules: with the
default `isolation_level=""`, an INSERT/UPDATE/DELETE/REPLACE implicitly opens
`BEGIN`; `commit()`/`rollback()` end it; `in_transaction` reports it;
`isolation_level=None` is autocommit and explicit `BEGIN`/`SAVEPOINT` SQL works.

Caps: rows are lists (not tuples); no `description`/`executemany`/`row_factory`;
parameters must be a list (any sequence works under CPython's sqlite3, and a
list already does); `Connection` is not a context manager (use commit/rollback
in try/except).
"""
from __future__ import annotations
from serpentine import Mut, Ref, PyVal, pyval_kind, dataclass, move
from serp_sqlite_core import connect as _core_connect, close as _core_close
from serp_sqlite_core import changes as _core_changes, last_rowid as _core_last_rowid
from serp_sqlite_core import prepare as _core_prepare, finalize as _core_finalize
from serp_sqlite_core import bind_int as _core_bind_int, bind_float as _core_bind_float
from serp_sqlite_core import bind_text as _core_bind_text, bind_blob as _core_bind_blob
from serp_sqlite_core import bind_null as _core_bind_null, step as _core_step
from serp_sqlite_core import column_count as _core_column_count, col_type as _core_col_type
from serp_sqlite_core import col_int as _core_col_int, col_float as _core_col_float
from serp_sqlite_core import col_text as _core_col_text, col_blob as _core_col_blob
from serp_sqlite_core import execute as _core_execute, in_tx as _core_in_tx


class Error(Exception):
    pass


class DatabaseError(Error):
    pass


class OperationalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


def _bind_params(stmt: int, params: PyVal) -> None:
    idx: int = 0
    for p in params:
        idx += 1
        kind: str = pyval_kind(p)
        if kind == "NoneType":
            _core_bind_null(stmt, idx)
        elif kind == "bool":
            _core_bind_int(stmt, idx, int(p))
        elif kind == "int":
            _core_bind_int(stmt, idx, int(p))
        elif kind == "float":
            _core_bind_float(stmt, idx, float(p))
        elif kind == "str":
            _core_bind_text(stmt, idx, str(p))
        elif kind == "bytes":
            _core_bind_blob(stmt, idx, bytes(p))
        else:
            raise ProgrammingError(f"Error binding parameter {idx}: type '{kind}' is not supported")


def _is_dml(sql: str) -> bool:
    """True when the statement starts with INSERT/UPDATE/DELETE/REPLACE (sqlite3's implicit-BEGIN rule)."""
    head: str = sql.lstrip().upper()
    return (head.startswith("INSERT") or head.startswith("UPDATE")
            or head.startswith("DELETE") or head.startswith("REPLACE"))


def _begin_sql(level: str | None) -> str:
    """The BEGIN statement sqlite3 issues for an isolation level ('' when autocommit)."""
    if level is None:
        return ""
    return "BEGIN " + level


@dataclass
class Cursor:
    _db: int
    _stmt: int
    rowcount: int
    lastrowid: int
    _begin: str = ""

    def execute(self: Mut[Cursor], sql: str, params: PyVal | None = None) -> None:
        if self._stmt != 0:
            _core_finalize(self._stmt)
            self._stmt = 0
        if self._begin != "" and _is_dml(sql):
            try:
                if not _core_in_tx(self._db):
                    _core_execute(self._db, self._begin)
            except ValueError as e0:
                raise OperationalError(f"{e0}")
        stmt: int = 0
        try:
            stmt = _core_prepare(self._db, sql)
        except ValueError as e:
            raise OperationalError(f"{e}")
        if params is not None:
            _bind_params(stmt, params)
        cols: int = 0
        try:
            cols = _core_column_count(stmt)
        except ValueError as e2:
            _core_finalize(stmt)
            raise OperationalError(f"{e2}")
        if cols == 0:
            try:
                while _core_step(stmt):
                    pass
            except ValueError as e3:
                _core_finalize(stmt)
                raise OperationalError(f"{e3}")
            _core_finalize(stmt)
            self.rowcount = _core_changes(self._db)
            self.lastrowid = _core_last_rowid(self._db)
            return
        self._stmt = stmt
        self.rowcount = -1

    def fetchone(self: Mut[Cursor]) -> PyVal | None:
        if self._stmt == 0:
            return None
        more: bool = False
        try:
            more = _core_step(self._stmt)
        except ValueError as e:
            raise OperationalError(f"{e}")
        if not more:
            _core_finalize(self._stmt)
            self._stmt = 0
            return None
        row: list[PyVal] = []
        n: int = _core_column_count(self._stmt)
        for i in range(n):
            t: int = _core_col_type(self._stmt, i)
            if t == 1:
                row.append(_core_col_int(self._stmt, i))
            elif t == 2:
                row.append(_core_col_float(self._stmt, i))
            elif t == 3:
                row.append(_core_col_text(self._stmt, i))
            elif t == 4:
                row.append(_core_col_blob(self._stmt, i))
            else:
                row.append(None)
        return move(row)

    def fetchall(self: Mut[Cursor]) -> PyVal:
        rows: list[PyVal] = []
        r: PyVal | None = self.fetchone()
        while r is not None:
            rows.append(r)
            r = self.fetchone()
        return move(rows)

    def close(self: Mut[Cursor]) -> None:
        if self._stmt != 0:
            _core_finalize(self._stmt)
            self._stmt = 0


@dataclass
class Connection:
    _db: int
    isolation_level: str | None = ""

    def cursor(self: Ref[Connection]) -> Cursor:
        return Cursor(self._db, 0, -1, 0, _begin_sql(self.isolation_level))

    @property
    def in_transaction(self: Ref[Connection]) -> bool:
        try:
            return _core_in_tx(self._db)
        except ValueError as e:
            raise ProgrammingError(f"{e}")

    def _finish(self: Ref[Connection], sql: str) -> None:
        try:
            if _core_in_tx(self._db):
                _core_execute(self._db, sql)
        except ValueError as e:
            raise OperationalError(f"{e}")

    def rollback(self: Ref[Connection]) -> None:
        self._finish("ROLLBACK")

    def execute(self: Ref[Connection], sql: str, params: PyVal | None = None) -> Cursor:
        cur: Cursor = self.cursor()
        if params is not None:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return move(cur)

    def commit(self: Ref[Connection]) -> None:
        self._finish("COMMIT")

    def close(self: Ref[Connection]) -> None:
        try:
            _core_close(self._db)
        except ValueError as e:
            raise ProgrammingError(f"{e}")


def connect(database: str, isolation_level: str | None = "") -> Connection:
    h: int = 0
    try:
        h = _core_connect(database)
    except ValueError as e:
        raise OperationalError(f"{e}")
    return Connection(h, isolation_level)
