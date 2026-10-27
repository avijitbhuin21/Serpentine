from serpentine import PyVal, Ref
from serp_os_core import exists, remove
from serp_sqlite import Connection, Cursor, OperationalError, connect


def count(conn: Ref[Connection]) -> int:
    """Number of rows in t, seen through a given connection."""
    rows: PyVal = conn.execute("SELECT count(*) FROM t").fetchall()
    return int(rows[0][0])


def main() -> None:
    path: str = "tmp_serp_sqlite_tx.db"
    if exists(path):
        remove(path)

    conn: Connection = connect(path)
    print(conn.isolation_level == "", conn.in_transaction)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    print("after ddl:", conn.in_transaction)

    conn.execute("INSERT INTO t (v) VALUES (?)", ["a"])
    print("after insert:", conn.in_transaction)
    other: Connection = connect(path)
    print("other sees:", count(other))
    conn.commit()
    print("after commit:", conn.in_transaction, count(other))

    conn.execute("INSERT INTO t (v) VALUES ('b')")
    conn.execute("  update t SET v = 'z' WHERE v = 'a'")
    print("pending:", conn.in_transaction, count(conn))
    conn.rollback()
    print("after rollback:", conn.in_transaction, count(conn))
    rows: PyVal = conn.execute("SELECT v FROM t").fetchall()
    print(rows)

    cur: Cursor = conn.cursor()
    try:
        cur.execute("INSERT INTO t (v) VALUES ('c')")
        cur.execute("INSERT INTO t (id, v) VALUES (1, 'dup')")
        conn.commit()
    except OperationalError as e:
        print("failed:", conn.in_transaction)
        conn.rollback()
    except Exception as e2:
        print("integrity:", conn.in_transaction)
        conn.rollback()
    print("after failed batch:", count(conn))

    conn.commit()
    conn.rollback()
    print("idempotent:", conn.in_transaction)
    conn.close()
    other.close()

    auto: Connection = connect(path, isolation_level=None)
    print(auto.isolation_level is None)
    auto.execute("INSERT INTO t (v) VALUES ('auto')")
    print("autocommit:", auto.in_transaction)
    auto.execute("BEGIN")
    auto.execute("DELETE FROM t")
    print("explicit:", auto.in_transaction, count(auto))
    auto.rollback()
    print("restored:", auto.in_transaction, count(auto))
    auto.execute("SAVEPOINT sp1")
    auto.execute("INSERT INTO t (v) VALUES ('sp')")
    auto.execute("ROLLBACK TO sp1")
    auto.execute("RELEASE sp1")
    print("savepoint:", count(auto))
    auto.close()

    imm: Connection = connect(path, isolation_level="IMMEDIATE")
    imm.execute("INSERT INTO t (v) VALUES ('imm')")
    print("immediate:", imm.in_transaction)
    imm.commit()
    print("final:", count(imm))
    imm.close()
    remove(path)
    print("done")


if __name__ == "__main__":
    main()
