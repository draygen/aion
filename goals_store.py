# goals_store.py
# Goal tracking with subtasks, priorities, and progress journal
# Ported from Sapphire functions/goals.py (single-user, scope hardcoded to 'default')

import sqlite3
import logging
import threading
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from config import CONFIG

logger = logging.getLogger(__name__)

_db_path = None
_db_initialized = False
_db_lock = threading.Lock()

VALID_PRIORITIES = ('high', 'medium', 'low')
VALID_STATUSES = ('active', 'completed', 'abandoned')


# ─── Database ─────────────────────────────────────────────────────────────────

def _get_db_path():
    global _db_path
    if _db_path is None:
        _db_path = Path(__file__).parent / "data" / "goals.db"
    return _db_path


@contextmanager
def _get_connection():
    _ensure_db()
    conn = sqlite3.connect(_get_db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _scope_condition(scope='default', col='scope'):
    return f"{col} IN (?, 'global')", [scope]


def _ensure_db():
    global _db_initialized
    if _db_initialized:
        return
    with _db_lock:
        if _db_initialized:
            return

        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(db_path, timeout=10)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'active',
                parent_id INTEGER REFERENCES goals(id),
                scope TEXT NOT NULL DEFAULT 'default',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                permanent INTEGER DEFAULT 0
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS goal_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                note TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_goals_scope ON goals(scope)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_progress_goal ON goal_progress(goal_id)')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS goal_scopes (
                name TEXT PRIMARY KEY,
                created DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute("INSERT OR IGNORE INTO goal_scopes (name) VALUES ('default')")

        try:
            cursor.execute('ALTER TABLE goals ADD COLUMN permanent INTEGER DEFAULT 0')
        except sqlite3.OperationalError as e:
            if 'duplicate column' not in str(e).lower():
                logger.error(f"Goals migration failed (permanent column): {e}")

        conn.commit()
        conn.close()
        _db_initialized = True
        logger.info(f"Goals database ready at {db_path}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _time_ago(timestamp_str):
    try:
        from zoneinfo import ZoneInfo
        tz_name = CONFIG.get('USER_TIMEZONE', 'UTC') or 'UTC'
        user_tz = ZoneInfo(tz_name)
        ts = datetime.fromisoformat(timestamp_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ZoneInfo('UTC'))
        diff = datetime.now(user_tz) - ts
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        if days > 13:
            return f"{days // 7}w ago"
        if days > 0:
            return f"{days}d ago"
        if hours > 0:
            return f"{hours}h ago"
        if minutes > 0:
            return f"{minutes}m ago"
        return "just now"
    except Exception:
        return ""


def _format_goal_full(goal, subtasks, progress_notes):
    gid, title, desc, priority, status, parent_id, scope, created, updated, completed = goal[:10]
    permanent = goal[10] if len(goal) > 10 else 0
    ago = _time_ago(updated)
    perm_tag = " [PERMANENT]" if permanent else ""
    lines = [f"[{gid}] {title} ({priority}){perm_tag} — updated {ago}"]
    if desc:
        lines.append(f'    "{desc}"')
    if subtasks:
        lines.append("    Subtasks:")
        for s in subtasks:
            sid, stitle, spri, sstatus = s
            mark = 'x' if sstatus == 'completed' else '-' if sstatus == 'abandoned' else ' '
            lines.append(f"      [{mark}] [{sid}] {stitle} ({sstatus})")
    else:
        lines.append("    (no subtasks)")
    if progress_notes:
        lines.append("    Recent progress:")
        for note, note_time in progress_notes[:3]:
            lines.append(f"      * {_time_ago(note_time)}: {note}")
    else:
        lines.append("    (no progress logged)")
    return '\n'.join(lines)


def _format_goal_summary(goal, subtask_count, subtask_done):
    gid, title, priority, status, updated, permanent = goal
    ago = _time_ago(updated)
    perm_tag = " [PERMANENT]" if permanent else ""
    sub_info = f" — {subtask_count} subtasks, {subtask_done} done" if subtask_count else " — no subtasks"
    return f"[{gid}] {title} ({priority}){perm_tag}{sub_info} — {ago}"


def _validate_priority(priority):
    if priority and priority not in VALID_PRIORITIES:
        return f"Invalid priority '{priority}'. Choose from: {', '.join(VALID_PRIORITIES)}."
    return None


def _validate_status(status):
    if status and status not in VALID_STATUSES:
        return f"Invalid status '{status}'. Choose from: {', '.join(VALID_STATUSES)}."
    return None


def _validate_goal_exists(cursor, goal_id, scope=None):
    if not isinstance(goal_id, int) or goal_id < 1:
        return None, f"Invalid goal_id '{goal_id}'. Must be a positive integer."
    if scope:
        cursor.execute('SELECT * FROM goals WHERE id = ? AND scope = ?', (goal_id, scope))
    else:
        cursor.execute('SELECT * FROM goals WHERE id = ?', (goal_id,))
    row = cursor.fetchone()
    if not row:
        scope_note = f" in scope '{scope}'" if scope else ""
        return None, f"Goal [{goal_id}] not found{scope_note}."
    return row, None


def _validate_length(value, field_name, max_len):
    if value and len(value) > max_len:
        return f"{field_name} too long ({len(value)} chars). Max is {max_len}."
    return None


# ─── Operations ───────────────────────────────────────────────────────────────

def _create_goal(title, description=None, priority='medium', parent_id=None, scope='default', permanent=False):
    if not title or not title.strip():
        return "Cannot create a goal without a title.", False
    title = title.strip()
    err = _validate_length(title, 'Title', 200)
    if err:
        return err, False
    if description:
        description = description.strip()
        err = _validate_length(description, 'Description', 500)
        if err:
            return err, False
    priority = (priority or 'medium').lower().strip()
    err = _validate_priority(priority)
    if err:
        return err, False

    with _get_connection() as conn:
        cursor = conn.cursor()
        if parent_id is not None:
            parent, err = _validate_goal_exists(cursor, parent_id, scope)
            if err:
                return f"Cannot create subtask: {err}", False
            if parent[5] is not None:
                return f"Goal [{parent_id}] is already a subtask. Subtasks can only be one level deep.", False

        perm_val = 1 if permanent else 0
        cursor.execute(
            'INSERT INTO goals (title, description, priority, parent_id, scope, permanent) VALUES (?, ?, ?, ?, ?, ?)',
            (title, description, priority, parent_id, scope, perm_val)
        )
        goal_id = cursor.lastrowid
        conn.commit()

    kind = "Subtask" if parent_id else "Goal"
    parent_note = f" under goal [{parent_id}]" if parent_id else ""
    perm_note = " [PERMANENT]" if permanent else ""
    return f"{kind} created: [{goal_id}] {title} ({priority}){parent_note}{perm_note}", True


def _list_goals(goal_id=None, status='active', scope='default'):
    with _get_connection() as conn:
        cursor = conn.cursor()

        if goal_id is not None:
            goal, err = _validate_goal_exists(cursor, goal_id, scope)
            if err:
                return err, False
            cursor.execute('SELECT id, title, priority, status FROM goals WHERE parent_id = ? ORDER BY created_at', (goal_id,))
            subtasks = cursor.fetchall()
            cursor.execute('SELECT note, created_at FROM goal_progress WHERE goal_id = ? ORDER BY created_at DESC', (goal_id,))
            progress = cursor.fetchall()
            return _format_goal_full(goal, subtasks, progress), True

        status_filter = status.lower().strip() if status else 'active'
        if status_filter not in ('active', 'completed', 'abandoned', 'all'):
            return f"Invalid status filter '{status_filter}'.", False

        scope_sql, scope_params = _scope_condition(scope)
        if status_filter == 'all':
            cursor.execute(
                f'SELECT * FROM goals WHERE parent_id IS NULL AND {scope_sql} ORDER BY updated_at DESC',
                scope_params
            )
        else:
            cursor.execute(
                f'SELECT * FROM goals WHERE parent_id IS NULL AND {scope_sql} AND status = ? ORDER BY updated_at DESC',
                scope_params + [status_filter]
            )
        top_level = cursor.fetchall()

        if not top_level:
            label = f" ({status_filter})" if status_filter != 'active' else ""
            return f"No{label} goals. Use /goal-add to start planning.", True

        full_goals = top_level[:3]
        summary_goals = top_level[3:10]
        lines = [f"=== {status_filter.capitalize()} Goals ===\n"]

        for goal in full_goals:
            gid = goal[0]
            cursor.execute('SELECT id, title, priority, status FROM goals WHERE parent_id = ? ORDER BY created_at', (gid,))
            subtasks = cursor.fetchall()
            cursor.execute('SELECT note, created_at FROM goal_progress WHERE goal_id = ? ORDER BY created_at DESC LIMIT 3', (gid,))
            progress = cursor.fetchall()
            lines.append(_format_goal_full(goal, subtasks, progress))
            lines.append("")

        if summary_goals:
            lines.append(f"--- Also {status_filter} ({len(summary_goals)} more) ---")
            for goal in summary_goals:
                gid = goal[0]
                cursor.execute('SELECT COUNT(*) FROM goals WHERE parent_id = ?', (gid,))
                sub_count = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(*) FROM goals WHERE parent_id = ? AND status = ?', (gid, 'completed'))
                sub_done = cursor.fetchone()[0]
                summary = (gid, goal[1], goal[3], goal[4], goal[8], goal[10] if len(goal) > 10 else 0)
                lines.append(_format_goal_summary(summary, sub_count, sub_done))

        remaining = len(top_level) - 10
        if remaining > 0:
            lines.append(f"... and {remaining} more")

        if status_filter == 'active':
            _append_recently_completed(cursor, lines, scope)

        return '\n'.join(lines), True


def _append_recently_completed(cursor, lines, scope, limit=5):
    scope_sql, scope_params = _scope_condition(scope)
    cursor.execute(
        f'SELECT id, title, completed_at FROM goals WHERE parent_id IS NULL AND {scope_sql} AND status = ? ORDER BY completed_at DESC LIMIT ?',
        scope_params + ['completed', limit]
    )
    completed = cursor.fetchall()
    if not completed:
        return
    lines.append("")
    lines.append("--- Recently Completed ---")
    for gid, gtitle, completed_at in completed:
        cursor.execute('SELECT note FROM goal_progress WHERE goal_id = ? ORDER BY created_at DESC LIMIT 1', (gid,))
        last_note = cursor.fetchone()
        ago = _time_ago(completed_at) if completed_at else ""
        note_preview = ""
        if last_note and last_note[0]:
            preview = last_note[0][:150] + ('...' if len(last_note[0]) > 150 else '')
            note_preview = f"\n      {preview}"
        lines.append(f"  [x] [{gid}] {gtitle} — completed {ago}{note_preview}")


def _update_goal(goal_id, scope='default', **kwargs):
    if not isinstance(goal_id, int) or goal_id < 1:
        return f"Invalid goal_id '{goal_id}'.", False

    title = kwargs.get('title')
    description = kwargs.get('description')
    priority = kwargs.get('priority')
    status = kwargs.get('status')
    progress_note = kwargs.get('progress_note')

    if title is not None:
        title = title.strip()
        if not title:
            return "Title cannot be empty.", False
        err = _validate_length(title, 'Title', 200)
        if err:
            return err, False
    if description is not None:
        description = description.strip()
        err = _validate_length(description, 'Description', 500)
        if err:
            return err, False
    if priority is not None:
        priority = priority.lower().strip()
        err = _validate_priority(priority)
        if err:
            return err, False
    if status is not None:
        status = status.lower().strip()
        err = _validate_status(status)
        if err:
            return err, False
    if progress_note is not None:
        progress_note = progress_note.strip()
        if not progress_note:
            return "Progress note cannot be empty.", False
        err = _validate_length(progress_note, 'Progress note', 1024)
        if err:
            return err, False

    has_update = any(v is not None for v in [title, description, priority, status, progress_note])
    if not has_update:
        return "Nothing to update.", False

    with _get_connection() as conn:
        cursor = conn.cursor()
        goal, err = _validate_goal_exists(cursor, goal_id, scope)
        if err:
            return err, False

        if len(goal) > 10 and goal[10]:
            if any(v is not None for v in [title, description, priority, status]):
                return f"Goal [{goal_id}] is permanent — only progress notes can be added.", False

        updates = []
        params = []
        if title is not None:
            updates.append('title = ?')
            params.append(title)
        if description is not None:
            updates.append('description = ?')
            params.append(description)
        if priority is not None:
            updates.append('priority = ?')
            params.append(priority)
        if status is not None:
            updates.append('status = ?')
            params.append(status)
            if status == 'completed':
                updates.append('completed_at = ?')
                params.append(datetime.now().isoformat())
            elif status == 'active':
                updates.append('completed_at = NULL')

        updates.append('updated_at = ?')
        params.append(datetime.now().isoformat())
        params.append(goal_id)
        cursor.execute(f'UPDATE goals SET {", ".join(updates)} WHERE id = ?', params)

        if progress_note:
            cursor.execute('INSERT INTO goal_progress (goal_id, note) VALUES (?, ?)', (goal_id, progress_note))

        conn.commit()

    changes = []
    if title is not None:
        changes.append(f"title → '{title}'")
    if priority is not None:
        changes.append(f"priority → {priority}")
    if status is not None:
        changes.append(f"status → {status}")
    if description is not None:
        changes.append("description updated")
    if progress_note:
        changes.append(f"logged: {progress_note[:80]}{'...' if len(progress_note) > 80 else ''}")

    return f"Goal [{goal_id}] updated: {', '.join(changes)}", True


def _delete_goal(goal_id, cascade=True, scope='default'):
    if not isinstance(goal_id, int) or goal_id < 1:
        return f"Invalid goal_id '{goal_id}'.", False

    with _get_connection() as conn:
        cursor = conn.cursor()
        goal, err = _validate_goal_exists(cursor, goal_id, scope)
        if err:
            return err, False

        if len(goal) > 10 and goal[10]:
            return f"Goal [{goal_id}] is permanent and cannot be deleted.", False

        title = goal[1]
        cursor.execute('SELECT COUNT(*) FROM goals WHERE parent_id = ?', (goal_id,))
        subtask_count = cursor.fetchone()[0]

        if subtask_count > 0 and not cascade:
            cursor.execute('UPDATE goals SET parent_id = NULL WHERE parent_id = ?', (goal_id,))

        cursor.execute('DELETE FROM goal_progress WHERE goal_id = ?', (goal_id,))
        if subtask_count > 0 and cascade:
            cursor.execute('DELETE FROM goal_progress WHERE goal_id IN (SELECT id FROM goals WHERE parent_id = ?)', (goal_id,))
            cursor.execute('DELETE FROM goals WHERE parent_id = ?', (goal_id,))
        cursor.execute('DELETE FROM goals WHERE id = ?', (goal_id,))
        conn.commit()

    sub_note = ""
    if subtask_count > 0:
        sub_note = f" and {subtask_count} subtask(s)" if cascade else f" ({subtask_count} subtasks promoted)"

    return f"Deleted goal [{goal_id}] '{title}'{sub_note}", True
