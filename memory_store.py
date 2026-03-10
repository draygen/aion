# memory_store.py
# Long-term memory with FTS5 full-text search, semantic embeddings, and labels
# Ported from Sapphire functions/memory.py (single-user, scope hardcoded to 'default')

import sqlite3
import logging
import re
import threading
import numpy as np
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from config import CONFIG

logger = logging.getLogger(__name__)

from memory_embeddings import get_embedder as _get_embedder

SUGGESTED_LABELS = "family, preferences, technical, stories, people, places, routines, opinions, self"

STOPWORDS = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
             'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
             'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
             'would', 'should', 'could', 'may', 'might', 'can', 'this', 'that',
             'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they'}

SIMILARITY_THRESHOLD = 0.40
MAX_MEMORY_LENGTH = 512

_db_path = None
_db_initialized = False
_db_lock = threading.Lock()


# ─── Database ─────────────────────────────────────────────────────────────────

def _get_db_path():
    global _db_path
    if _db_path is None:
        _db_path = Path(__file__).parent / "data" / "memory.db"
    return _db_path


@contextmanager
def _get_connection():
    _ensure_db()
    conn = sqlite3.connect(_get_db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def _repair_db(db_path):
    backup_path = db_path.with_suffix('.db.corrupted')
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT id, content, timestamp, importance, keywords, context, scope, label FROM memories')
        except sqlite3.DatabaseError:
            try:
                cursor.execute('SELECT id, content, timestamp, importance, keywords, context FROM memories')
            except sqlite3.DatabaseError:
                conn.close()
                logger.error("Cannot read any data from corrupted database")
                db_path.rename(backup_path)
                return

        rows = cursor.fetchall()
        conn.close()
        db_path.rename(backup_path)
        logger.info(f"Corrupted database backed up to {backup_path}")

        if not rows:
            return

        conn = sqlite3.connect(db_path, timeout=10)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute('''
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                importance INTEGER DEFAULT 5,
                keywords TEXT,
                context TEXT,
                scope TEXT NOT NULL DEFAULT 'default',
                label TEXT,
                embedding BLOB
            )
        ''')
        for row in rows:
            r = list(row) + [None] * (8 - len(row))
            cursor.execute(
                'INSERT INTO memories (id, content, timestamp, importance, keywords, context, scope, label) VALUES (?,?,?,?,?,?,?,?)',
                r[:8]
            )
        conn.commit()
        conn.close()
        logger.info(f"Salvaged {len(rows)} memories into fresh database")
    except Exception as e:
        logger.error(f"Repair failed: {e}")
        if db_path.exists() and not backup_path.exists():
            db_path.rename(backup_path)


def _setup_fts(cursor):
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content, keywords, label,
            content=memories, content_rowid=id
        )
    """)
    cursor.execute("DROP TRIGGER IF EXISTS memories_fts_insert")
    cursor.execute("DROP TRIGGER IF EXISTS memories_fts_delete")
    cursor.execute("DROP TRIGGER IF EXISTS memories_fts_update")
    cursor.execute("""
        CREATE TRIGGER memories_fts_insert
        AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, keywords, label)
            VALUES (new.id, new.content, new.keywords, new.label);
        END
    """)
    cursor.execute("""
        CREATE TRIGGER memories_fts_delete
        AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, keywords, label)
            VALUES ('delete', old.id, old.content, old.keywords, old.label);
        END
    """)
    cursor.execute("""
        CREATE TRIGGER memories_fts_update
        AFTER UPDATE OF content, keywords, label ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, keywords, label)
            VALUES ('delete', old.id, old.content, old.keywords, old.label);
            INSERT INTO memories_fts(rowid, content, keywords, label)
            VALUES (new.id, new.content, new.keywords, new.label);
        END
    """)
    cursor.execute("SELECT COUNT(*) FROM memories")
    mem_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM memories_fts")
    fts_count = cursor.fetchone()[0]
    if mem_count > 0 and fts_count == 0:
        logger.info(f"Populating FTS5 index from {mem_count} existing memories...")
        cursor.execute("""
            INSERT INTO memories_fts(rowid, content, keywords, label)
            SELECT id, content, keywords, label FROM memories
        """)


def _ensure_db():
    global _db_initialized
    if _db_initialized:
        return True
    with _db_lock:
        if _db_initialized:
            return True
        try:
            db_path = _get_db_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)

            if db_path.exists():
                try:
                    conn = sqlite3.connect(db_path, timeout=10)
                    result = conn.execute("PRAGMA integrity_check").fetchone()
                    conn.close()
                    if result[0] != 'ok':
                        logger.error(f"DB integrity check failed: {result[0]}")
                        _repair_db(db_path)
                except sqlite3.DatabaseError as e:
                    logger.error(f"Database corrupted: {e}")
                    _repair_db(db_path)

            conn = sqlite3.connect(db_path, timeout=10)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    importance INTEGER DEFAULT 5,
                    keywords TEXT,
                    context TEXT
                )
            ''')

            cursor.execute("PRAGMA table_info(memories)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'scope' not in columns:
                cursor.execute("ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT 'default'")
            if 'label' not in columns:
                cursor.execute("ALTER TABLE memories ADD COLUMN label TEXT")
            if 'embedding' not in columns:
                cursor.execute("ALTER TABLE memories ADD COLUMN embedding BLOB")

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON memories(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_scope ON memories(scope)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_label ON memories(label)')

            try:
                _setup_fts(cursor)
            except sqlite3.DatabaseError as e:
                logger.warning(f"FTS5 corrupted, rebuilding: {e}")
                cursor.execute("DROP TABLE IF EXISTS memories_fts")
                cursor.execute("DROP TRIGGER IF EXISTS memories_fts_insert")
                cursor.execute("DROP TRIGGER IF EXISTS memories_fts_delete")
                cursor.execute("DROP TRIGGER IF EXISTS memories_fts_update")
                conn.commit()
                _setup_fts(cursor)

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memory_scopes (
                    name TEXT PRIMARY KEY,
                    created DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute("INSERT OR IGNORE INTO memory_scopes (name) VALUES ('default')")
            conn.commit()
            conn.close()
            _db_initialized = True
            logger.info(f"Memory database ready at {db_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize memory database: {e}")
            return False


_backfill_done = False


def _backfill_embeddings():
    global _backfill_done
    if _backfill_done:
        return
    embedder = _get_embedder()
    if not embedder.available:
        _backfill_done = True
        return

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, content FROM memories WHERE embedding IS NULL')
        rows = cursor.fetchall()

    if not rows:
        _backfill_done = True
        return

    logger.info(f"Backfilling embeddings for {len(rows)} memories...")
    batch_size = 32
    filled = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]
        embs = embedder.embed(texts, prefix='search_document')
        if embs is None:
            break
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                for row_id, emb in zip(ids, embs):
                    cursor.execute('UPDATE memories SET embedding = ? WHERE id = ?',
                                   (emb.tobytes(), row_id))
                conn.commit()
                filled += len(batch)
        except Exception as e:
            logger.error(f"Backfill batch failed: {e}")
            break

    _backfill_done = True
    if filled:
        logger.info(f"Backfill complete: {filled}/{len(rows)} memories embedded")


def _scope_condition(scope='default', col='scope'):
    return f"{col} IN (?, 'global')", [scope]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_keywords(content: str) -> str:
    words = content.lower().split()
    keywords = [w.strip('.,!?;:\'\"()') for w in words if len(w) > 2 and w.lower() not in STOPWORDS]
    return ' '.join(sorted(set(keywords)))


def _format_time_ago(timestamp_str: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        tz_name = CONFIG.get('USER_TIMEZONE', 'UTC') or 'UTC'
        user_tz = ZoneInfo(tz_name)
        ts = datetime.fromisoformat(timestamp_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ZoneInfo('UTC'))
        diff = datetime.now(user_tz) - ts
        days, hours, minutes = diff.days, diff.seconds // 3600, (diff.seconds % 3600) // 60
        if days > 0:
            return f"{days}d ago"
        elif hours > 0:
            return f"{hours}h ago"
        elif minutes > 0:
            return f"{minutes}m ago"
        return "just now"
    except Exception:
        return ""


def _format_memory(row_id, content, timestamp, label):
    time_ago = _format_time_ago(timestamp)
    time_str = f" ({time_ago})" if time_ago else ""
    label_str = f" [{label}]" if label else ""
    preview = content[:150] + ('...' if len(content) > 150 else '')
    return f"[{row_id}]{time_str}{label_str} {preview}"


def _parse_labels(label) -> list:
    if not label:
        return []
    return [l.strip().lower() for l in label.split(',') if l.strip()]


def _sanitize_fts_query(query: str, use_or=False, use_prefix=False) -> str:
    sanitized = re.sub(r'[^\w\s"*]', ' ', query)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    if not sanitized or '"' in sanitized:
        return sanitized
    terms = sanitized.split()
    if use_prefix:
        terms = [t + '*' if not t.endswith('*') else t for t in terms]
    if use_or and len(terms) > 1:
        return ' OR '.join(terms)
    return ' '.join(terms)


# ─── Core Operations ──────────────────────────────────────────────────────────

def _save_memory(content: str, label: str = None, scope: str = 'default') -> tuple:
    try:
        if not content or not content.strip():
            return "Cannot save empty memory.", False
        if len(content) > MAX_MEMORY_LENGTH:
            return f"Memory too long ({len(content)} chars). Max is {MAX_MEMORY_LENGTH}.", False

        content = content.strip()
        keywords = _extract_keywords(content)
        label = label.strip().lower() if label else None

        embedding_blob = None
        embedder = _get_embedder()
        if embedder.available:
            embs = embedder.embed([content], prefix='search_document')
            if embs is not None:
                embedding_blob = embs[0].tobytes()

        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO memories (content, keywords, scope, label, embedding) VALUES (?, ?, ?, ?, ?)',
                (content, keywords, scope, label, embedding_blob)
            )
            memory_id = cursor.lastrowid
            conn.commit()

        label_str = f", label: {label}" if label else ""
        logger.info(f"Stored memory ID {memory_id}{label_str}")
        return f"Memory saved (ID: {memory_id}{label_str})", True

    except Exception as e:
        logger.error(f"Error saving memory: {e}")
        return f"Failed to save memory: {e}", False


def _fts_search(cursor, fts_query, scope, labels, limit):
    scope_sql, scope_params = _scope_condition(scope, 'm.scope')
    if labels:
        placeholders = ','.join('?' * len(labels))
        cursor.execute(f'''
            SELECT m.id, m.content, m.timestamp, m.label, bm25(memories_fts) as rank
            FROM memories_fts f JOIN memories m ON f.rowid = m.id
            WHERE memories_fts MATCH ? AND {scope_sql} AND m.label IN ({placeholders})
            ORDER BY rank LIMIT ?
        ''', [fts_query] + scope_params + labels + [limit])
    else:
        cursor.execute(f'''
            SELECT m.id, m.content, m.timestamp, m.label, bm25(memories_fts) as rank
            FROM memories_fts f JOIN memories m ON f.rowid = m.id
            WHERE memories_fts MATCH ? AND {scope_sql}
            ORDER BY rank LIMIT ?
        ''', [fts_query] + scope_params + [limit])
    return cursor.fetchall()


def _vector_search(query: str, scope: str, labels: list, limit: int) -> list:
    embedder = _get_embedder()
    if not embedder.available:
        return []

    query_emb = embedder.embed([query], prefix='search_query')
    if query_emb is None:
        return []
    query_vec = query_emb[0]

    with _get_connection() as conn:
        cursor = conn.cursor()
        scope_sql, scope_params = _scope_condition(scope)
        if labels:
            placeholders = ','.join('?' * len(labels))
            cursor.execute(
                f'SELECT id, content, timestamp, label, embedding FROM memories WHERE {scope_sql} AND label IN ({placeholders}) AND embedding IS NOT NULL LIMIT 10000',
                scope_params + labels)
        else:
            cursor.execute(
                f'SELECT id, content, timestamp, label, embedding FROM memories WHERE {scope_sql} AND embedding IS NOT NULL LIMIT 10000',
                scope_params)
        rows = cursor.fetchall()

    if not rows:
        return []

    scored = []
    for row_id, content, timestamp, lbl, emb_blob in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        sim = float(np.dot(query_vec, emb))
        if sim >= SIMILARITY_THRESHOLD:
            scored.append((row_id, content, timestamp, lbl, sim))

    scored.sort(key=lambda x: x[4], reverse=True)
    return scored[:limit]


def _search_memory(query: str, limit: int = 10, label: str = None, scope: str = 'default') -> tuple:
    try:
        if not query or not query.strip():
            return "Search query cannot be empty.", False

        labels = _parse_labels(label)
        label_note = f" with labels '{label}'" if labels else ""

        _backfill_embeddings()

        with _get_connection() as conn:
            cursor = conn.cursor()

            fts_exact = _sanitize_fts_query(query)
            if fts_exact:
                try:
                    rows = _fts_search(cursor, fts_exact, scope, labels, limit)
                    if rows:
                        results = [_format_memory(r[0], r[1], r[2], r[3]) for r in rows]
                        return f"Found {len(rows)} memories:\n" + "\n".join(results), True

                    fts_broad = _sanitize_fts_query(query, use_or=True, use_prefix=True)
                    if fts_broad != fts_exact:
                        rows = _fts_search(cursor, fts_broad, scope, labels, limit)
                        if rows:
                            results = [_format_memory(r[0], r[1], r[2], r[3]) for r in rows]
                            return f"Found {len(rows)} memories:\n" + "\n".join(results), True
                except sqlite3.OperationalError as e:
                    logger.warning(f"FTS5 query failed: {e}")

        vec_results = _vector_search(query, scope, labels, limit)
        if vec_results:
            results = [_format_memory(r[0], r[1], r[2], r[3]) for r in vec_results]
            return f"Found {len(vec_results)} memories:\n" + "\n".join(results), True

        # LIKE fallback
        terms = query.lower().split()[:5]
        if terms:
            with _get_connection() as conn:
                cursor = conn.cursor()
                conditions = ' OR '.join(['(content LIKE ? OR keywords LIKE ?)' for _ in terms])
                params = []
                for term in terms:
                    params.extend([f'%{term}%', f'%{term}%'])
                if labels:
                    placeholders = ','.join('?' * len(labels))
                    label_filter = f" AND label IN ({placeholders})"
                    params.extend(labels)
                else:
                    label_filter = ""
                scope_sql, scope_params = _scope_condition(scope)
                cursor.execute(f'''
                    SELECT id, content, timestamp, label FROM memories
                    WHERE {scope_sql} AND ({conditions}){label_filter}
                    ORDER BY timestamp DESC LIMIT ?
                ''', scope_params + params + [limit])
                rows = cursor.fetchall()
            if rows:
                results = [_format_memory(r[0], r[1], r[2], r[3]) for r in rows]
                return f"Found {len(rows)} memories:\n" + "\n".join(results), True

        return f"No memories found for '{query}'{label_note}.", True

    except Exception as e:
        logger.error(f"Error searching memory: {e}")
        return f"Search failed: {e}", False


def _get_recent_memories(count: int = 10, label: str = None, scope: str = 'default') -> tuple:
    try:
        labels = _parse_labels(label)
        scope_sql, scope_params = _scope_condition(scope)
        with _get_connection() as conn:
            cursor = conn.cursor()
            if labels:
                placeholders = ','.join('?' * len(labels))
                cursor.execute(f'''
                    SELECT id, content, timestamp, label FROM memories
                    WHERE {scope_sql} AND label IN ({placeholders}) ORDER BY timestamp DESC LIMIT ?
                ''', scope_params + labels + [count])
            else:
                cursor.execute(f'''
                    SELECT id, content, timestamp, label FROM memories
                    WHERE {scope_sql} ORDER BY timestamp DESC LIMIT ?
                ''', scope_params + [count])
            rows = cursor.fetchall()
        if not rows:
            label_note = f" with labels '{label}'" if labels else ""
            return f"No memories stored{label_note}.", True
        results = [_format_memory(r[0], r[1], r[2], r[3]) for r in rows]
        return f"Recent {len(rows)} memories:\n" + "\n".join(results), True
    except Exception as e:
        logger.error(f"Error getting recent memories: {e}")
        return f"Failed to retrieve memories: {e}", False


def _delete_memory(memory_id: int, scope: str = 'default') -> tuple:
    try:
        if not isinstance(memory_id, int) or memory_id < 1:
            return "Invalid memory ID. Use the number shown in brackets [N].", False
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, content FROM memories WHERE id = ? AND scope = ?', (memory_id, scope))
            row = cursor.fetchone()
            if not row:
                return f"Memory [{memory_id}] not found.", False
            cursor.execute('DELETE FROM memories WHERE id = ? AND scope = ?', (memory_id, scope))
            conn.commit()
        preview = row[1][:50] + ('...' if len(row[1]) > 50 else '')
        return f"Deleted memory [{memory_id}]: {preview}", True
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        return f"Failed to delete memory: {e}", False
