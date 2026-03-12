import os
import sqlite3
import sys


DB_PATH = "/workspace/aion/data/aion.db"


def ensure_column(conn: sqlite3.Connection, name: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if name not in cols:
        conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
        conn.commit()


def inspect() -> int:
    print("DB_EXISTS", os.path.exists(DB_PATH))
    conn = sqlite3.connect(DB_PATH)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    print("COLUMNS", ",".join(cols))
    print("USER", conn.execute("SELECT id, username FROM users WHERE username='brian'").fetchone())
    conn.close()
    return 0


def force_reset() -> int:
    conn = sqlite3.connect(DB_PATH)
    ensure_column(conn, "must_change_password", "INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "UPDATE users SET must_change_password = 1 WHERE username = ?",
        ("brian",),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, username, must_change_password FROM users WHERE username='brian'"
    ).fetchone()
    print("UPDATED", row)
    conn.close()
    return 0


def set_admin() -> int:
    conn = sqlite3.connect(DB_PATH)
    ensure_column(conn, "must_change_password", "INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "UPDATE users SET role = 'admin' WHERE username = ?",
        ("brian",),
    )
    conn.commit()
    row = conn.execute(
        "SELECT username, role, must_change_password FROM users WHERE username='brian'"
    ).fetchone()
    print("ADMIN", row)
    conn.close()
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "inspect"
    if action == "inspect":
        raise SystemExit(inspect())
    if action == "force-reset":
        raise SystemExit(force_reset())
    if action == "set-admin":
        raise SystemExit(set_admin())
    print(f"Unknown action: {action}", file=sys.stderr)
    raise SystemExit(2)
