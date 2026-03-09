"""Structured event logging for chat, tools, and automations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from auth import get_db


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(
    *,
    event_type: str,
    source: str,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    channel: Optional[str] = None,
    thread_id: Optional[str] = None,
    message_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    content: Optional[str] = None,
    payload: Any = None,
) -> int:
    db = get_db()
    payload_json = None if payload is None else json.dumps(payload, ensure_ascii=False, sort_keys=True)
    cur = db.execute(
        """
        INSERT INTO events (
            user_id, session_id, channel, thread_id, message_id,
            event_type, source, tool_name, content, payload, ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            session_id,
            channel,
            thread_id,
            message_id,
            event_type,
            source,
            tool_name,
            content,
            payload_json,
            _utc_now_iso(),
        ),
    )
    db.commit()
    event_id = cur.lastrowid
    db.close()
    return event_id


def list_events(*, user_id: Optional[int] = None, session_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    db = get_db()
    clauses = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)
    params.append(max(1, min(limit, 500)))
    rows = db.execute(
        f"""
        SELECT id, user_id, session_id, channel, thread_id, message_id,
               event_type, source, tool_name, content, payload, ts
        FROM events
        {where_sql}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    db.close()

    results = []
    for row in reversed(rows):
        item = dict(row)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except Exception:
                pass
        results.append(item)
    return results
