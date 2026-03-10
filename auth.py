"""Authentication, SQLite sessions, and decorators for Jarvis."""
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
from flask import g, jsonify, request

from config import CONFIG

DB_PATH = "data/jarvis.db"
MIN_PASSWORD_LENGTH = 10
PASSWORD_CHANGE_ALLOWED_PATHS = {"/api/change-password", "/api/whoami", "/api/logout"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_db_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    os.makedirs("data", exist_ok=True)
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id      INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            pw_hash  TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'user',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token    TEXT PRIMARY KEY,
            user_id  INTEGER NOT NULL,
            expires  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS history (
            id       INTEGER PRIMARY KEY,
            user_id  INTEGER NOT NULL,
            role     TEXT NOT NULL,
            content  TEXT NOT NULL,
            ts       TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id, id DESC);
        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY,
            user_id    INTEGER,
            session_id TEXT,
            channel    TEXT,
            thread_id  TEXT,
            message_id TEXT,
            event_type TEXT NOT NULL,
            source     TEXT NOT NULL,
            tool_name  TEXT,
            content    TEXT,
            payload    TEXT,
            ts         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id DESC);
    """)
    _ensure_user_column(db, "must_change_password", "INTEGER NOT NULL DEFAULT 0")
    _ensure_history_column(db, "session_id", "TEXT")
    _ensure_history_column(db, "channel", "TEXT")
    _ensure_history_column(db, "thread_id", "TEXT")
    _ensure_history_column(db, "message_id", "TEXT")
    db.commit()

    # Create Brian's admin account on first run
    admin_pass = CONFIG.get("admin_password", "")
    cur = db.execute("SELECT id FROM users WHERE username = 'brian'")
    existing_brian = cur.fetchone()
    if not existing_brian:
        if not admin_pass:
            admin_pass = secrets.token_urlsafe(18)
            print("[auth] No admin_password configured. Generated a one-time bootstrap password for user 'brian'.")
            print(f"[auth] Bootstrap password: {admin_pass}")
        pw_hash = bcrypt.hashpw(admin_pass.encode(), bcrypt.gensalt()).decode()
        db.execute(
            "INSERT INTO users (username, pw_hash, role, must_change_password, created) VALUES (?, ?, 'admin', 1, ?)",
            ("brian", pw_hash, _utc_now_iso()),
        )
        db.commit()
        print("[auth] Created admin user: brian")
    else:
        db.execute("UPDATE users SET role = 'admin' WHERE username = 'brian'")
        db.commit()
        _mark_bootstrap_password_if_needed(db, "brian", admin_pass)

    db.close()
    _migrate_learned_facts()


def _ensure_user_column(db, column_name: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if column_name not in columns:
        db.execute(f"ALTER TABLE users ADD COLUMN {column_name} {definition}")


def _ensure_history_column(db, column_name: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute("PRAGMA table_info(history)").fetchall()}
    if column_name not in columns:
        db.execute(f"ALTER TABLE history ADD COLUMN {column_name} {definition}")


def _mark_bootstrap_password_if_needed(db, username: str, configured_password: str) -> None:
    if not configured_password:
        return
    row = db.execute(
        "SELECT id, pw_hash, must_change_password FROM users WHERE username = ?",
        (username.lower(),),
    ).fetchone()
    if not row or row["must_change_password"]:
        return
    try:
        if bcrypt.checkpw(configured_password.encode(), row["pw_hash"].encode()):
            db.execute(
                "UPDATE users SET must_change_password = 1 WHERE id = ?",
                (row["id"],),
            )
            db.commit()
    except ValueError:
        return


def _migrate_learned_facts():
    old_path = "data/user_learned.jsonl"
    new_path = CONFIG.get("shared_facts_file", "data/shared_learned.jsonl")
    if os.path.exists(old_path) and not os.path.exists(new_path):
        import shutil
        shutil.copy2(old_path, new_path)
        print(f"[auth] Migrated {old_path} → {new_path}")


def _validate_new_password(password: str) -> str | None:
    if not password:
        return "Password is required."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def create_user(
    username: str,
    password: str,
    role: str = "user",
    must_change_password: bool = True,
) -> int:
    err = _validate_new_password(password)
    if err:
        raise ValueError(err)
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (username, pw_hash, role, must_change_password, created) VALUES (?, ?, ?, ?, ?)",
        (username.lower(), pw_hash, role, 1 if must_change_password else 0, _utc_now_iso()),
    )
    db.commit()
    user_id = cur.lastrowid
    db.close()
    return user_id


def verify_login(username: str, password: str):
    db = get_db()
    row = db.execute(
        "SELECT * FROM users WHERE username = ?", (username.lower(),)
    ).fetchone()
    db.close()
    if not row:
        return None
    if bcrypt.checkpw(password.encode(), row["pw_hash"].encode()):
        return dict(row)
    return None


def create_token(user_id: int) -> str:
    token = secrets.token_hex(32)
    expires = (_utc_now() + timedelta(days=30)).isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO tokens (token, user_id, expires) VALUES (?, ?, ?)",
        (token, user_id, expires),
    )
    db.commit()
    db.close()
    return token


def change_password(user_id: int, current_password: str, new_password: str) -> str | None:
    err = _validate_new_password(new_password)
    if err:
        return err

    db = get_db()
    row = db.execute("SELECT pw_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        db.close()
        return "User not found."
    if not bcrypt.checkpw(current_password.encode(), row["pw_hash"].encode()):
        db.close()
        return "Current password is incorrect."
    if bcrypt.checkpw(new_password.encode(), row["pw_hash"].encode()):
        db.close()
        return "New password must be different from the current password."

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.execute(
        "UPDATE users SET pw_hash = ?, must_change_password = 0 WHERE id = ?",
        (new_hash, user_id),
    )
    db.commit()
    db.close()
    return None


def get_user_by_token(token: str):
    db = get_db()
    row = db.execute(
        "SELECT u.*, t.expires FROM users u JOIN tokens t ON u.id = t.user_id WHERE t.token = ?",
        (token,),
    ).fetchone()
    if not row:
        db.close()
        return None
    if _parse_db_datetime(row["expires"]) < _utc_now():
        db.execute("DELETE FROM tokens WHERE token = ?", (token,))
        db.commit()
        db.close()
        return None
    # Sliding 30-day expiry
    new_expires = (_utc_now() + timedelta(days=30)).isoformat()
    db.execute("UPDATE tokens SET expires = ? WHERE token = ?", (new_expires, token))
    db.commit()
    db.close()
    return dict(row)


def delete_token(token: str):
    db = get_db()
    db.execute("DELETE FROM tokens WHERE token = ?", (token,))
    db.commit()
    db.close()


def delete_user(user_id: int):
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM events WHERE user_id = ?", (user_id,))
    db.commit()
    db.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("jarvis_token")
        if not token:
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        user = get_user_by_token(token)
        if not user:
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        if user.get("must_change_password") and request.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
            return jsonify({"error": "Password change required", "requires_password_change": True}), 403
        g.user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("jarvis_token")
        if not token:
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        user = get_user_by_token(token)
        if not user:
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        if user.get("must_change_password") and request.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
            return jsonify({"error": "Password change required", "requires_password_change": True}), 403
        if user["role"] != "admin":
            return jsonify({"error": "Forbidden"}), 403
        g.user = user
        return f(*args, **kwargs)
    return decorated


def vast_required(f):
    """Allow access to users with 'admin' or 'vast' role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("jarvis_token")
        if not token:
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        user = get_user_by_token(token)
        if not user:
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        if user.get("must_change_password") and request.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
            return jsonify({"error": "Password change required", "requires_password_change": True}), 403
        if user["role"] not in ("admin", "vast"):
            return jsonify({"error": "Forbidden"}), 403
        g.user = user
        return f(*args, **kwargs)
    return decorated
