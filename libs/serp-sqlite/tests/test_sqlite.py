from serpentine import PyVal, pyval_kind
from serp_os_core import exists, remove
from serp_sqlite import (Connection, Cursor, Error, DatabaseError,
                         OperationalError, ProgrammingError, connect)


def main() -> None:
    path: str = "tmp_serp_sqlite_test.db"
    if exists(path):
        remove(path)

    conn: Connection = connect(path)
    cur: Cursor = conn.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, score REAL, tag BLOB)")
    cur.execute("INSERT INTO users (name, score, tag) VALUES ('ada', 99.5, x'c0ffee')")
    print(cur.rowcount, cur.lastrowid)
    cur.execute("INSERT INTO users (name, score, tag) VALUES (?, ?, ?)",
                ["grace", 88.25, b"\x00\xff"])
    print(cur.rowcount, cur.lastrowid)
    cur.execute("INSERT INTO users (name, score, tag) VALUES (?, ?, ?)",
                ["nobody", None, None])
    print(cur.rowcount, cur.lastrowid)

    cur.execute("SELECT id, name, score, tag FROM users ORDER BY id")
    print(cur.rowcount)
    row: PyVal | None = cur.fetchone()
    while row is not None:
        r: PyVal = row
        print(r)
        print(pyval_kind(r[1]), pyval_kind(r[2]), pyval_kind(r[3]))
        row = cur.fetchone()
    last: PyVal | None = cur.fetchone()
    print(last is None)

    rows: PyVal = conn.execute("SELECT name FROM users WHERE score > ? ORDER BY score DESC",
                               [80.0]).fetchall()
    print(rows)
    print(len(rows), rows[0][0])

    agg: PyVal = conn.execute("SELECT count(*), sum(score) FROM users").fetchall()
    print(agg)

    up: Cursor = conn.execute("UPDATE users SET score = ? WHERE name = ?", [100.0, "ada"])
    print(up.rowcount)
    conn.commit()

    blob: PyVal = conn.execute("SELECT tag FROM users WHERE name = 'grace'").fetchall()
    b: bytes = bytes(blob[0][0])
    print(b.hex())

    try:
        cur.execute("SELECT * FROM missing_table")
    except OperationalError as e:
        print("exec:", e)
    try:
        cur.execute("INSERT INTO")
    except DatabaseError as e2:
        print("prep: rejected")
    try:
        cur.execute("INSERT INTO users (name) VALUES (?)", [[1, 2]])
    except ProgrammingError as e3:
        print("bind:", e3)

    cur.close()
    conn.close()
    try:
        conn.close()
    except Error as e4:
        print("closed:", e4)

    print("done")


if __name__ == "__main__":
    main()
