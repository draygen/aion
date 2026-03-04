"""Authentication, SQLite sessions, and decorators for Jarvis."""
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

import bcrypt
from flask import g, jsonify, request

from config import CONFIG

DB_PATH = "data/jarvis.db"


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
    """)
    db.commit()

    # Create Brian's admin account on first run
    admin_pass = CONFIG.get("admin_password", "changeme2026")
    cur = db.execute("SELECT id FROM users WHERE username = 'brian'")
    if not cur.fetchone():
        pw_hash = bcrypt.hashpw(admin_pass.encode(), bcrypt.gensalt()).decode()
        db.execute(
            "INSERT INTO users (username, pw_hash, role, created) VALUES (?, ?, 'admin', ?)",
            ("brian", pw_hash, datetime.utcnow().isoformat()),
        )
        db.commit()
        print("[auth] Created admin user: brian")

    db.close()
    _migrate_learned_facts()


def _migrate_learned_facts():
    old_path = "data/user_learned.jsonl"
    new_path = CONFIG.get("shared_facts_file", "data/shared_learned.jsonl")
    if os.path.exists(old_path) and not os.path.exists(new_path):
        import shutil
        shutil.copy2(old_path, new_path)
        print(f"[auth] Migrated {old_path} → {new_path}")


def create_user(username: str, password: str, role: str = "user") -> int:
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (username, pw_hash, role, created) VALUES (?, ?, ?, ?)",
        (username.lower(), pw_hash, role, datetime.utcnow().isoformat()),
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
    expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO tokens (token, user_id, expires) VALUES (?, ?, ?)",
        (token, user_id, expires),
    )
    db.commit()
    db.close()
    return token


def get_user_by_token(token: str):
    db = get_db()
    row = db.execute(
        "SELECT u.*, t.expires FROM users u JOIN tokens t ON u.id = t.user_id WHERE t.token = ?",
        (token,),
    ).fetchone()
    if not row:
        db.close()
        return None
    if datetime.fromisoformat(row["expires"]) < datetime.utcnow():
        db.execute("DELETE FROM tokens WHERE token = ?", (token,))
        db.commit()
        db.close()
        return None
    # Sliding 30-day expiry
    new_expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
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
        if user["role"] != "admin":
            return jsonify({"error": "Forbidden"}), 403
        g.user = user
        return f(*args, **kwargs)
    return decorated
