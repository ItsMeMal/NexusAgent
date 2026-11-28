import re
import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


def _derive_session_title(text: Optional[str], max_len: int = 56) -> str:
    """Turn a raw user prompt into a crisp single-line session title."""
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return ""
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3].rstrip() + "..."


def _is_placeholder_title(title: Optional[str], session_id: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    low = t.lower()
    return low in ("new session", "untitled") or low == f"session {session_id}".lower()


class SQLiteMemory:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Sessions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    summary TEXT,
                    summary_msg_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Safe migration for existing databases
            cursor.execute("PRAGMA table_info(sessions)")
            sess_cols = {row[1] for row in cursor.fetchall()}
            if "summary" not in sess_cols:
                cursor.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
            if "summary_msg_count" not in sess_cols:
                cursor.execute("ALTER TABLE sessions ADD COLUMN summary_msg_count INTEGER DEFAULT 0")

            # Messages Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)

            # Long-term Key-Value / Fact Memory
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT,
                    key TEXT,
                    content TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Try to create FTS5 table for fast semantic/text search
            try:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        key,
                        content,
                        category,
                        content='memories',
                        content_rowid='id'
                    )
                """)
                # Triggers to keep FTS index synced
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, key, content, category)
                        VALUES (new.id, new.key, new.content, new.category);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, key, content, category)
                        VALUES('delete', old.id, old.key, old.content, old.category);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, key, content, category)
                        VALUES('delete', old.id, old.key, old.content, old.category);
                        INSERT INTO memories_fts(rowid, key, content, category)
                        VALUES (new.id, new.key, new.content, new.category);
                    END;
                """)

                # Cross-session message search FTS5 index
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'")
                msg_fts_existed = cursor.fetchone() is not None
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                        content,
                        session_id UNINDEXED,
                        role UNINDEXED,
                        content='messages',
                        content_rowid='id'
                    )
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                        INSERT INTO messages_fts(rowid, content, session_id, role)
                        VALUES (new.id, COALESCE(new.content, ''), new.session_id, new.role);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                        INSERT INTO messages_fts(messages_fts, rowid, content, session_id, role)
                        VALUES('delete', old.id, COALESCE(old.content, ''), old.session_id, old.role);
                    END;
                """)
                if not msg_fts_existed:
                    cursor.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
                self.has_fts = True
            except sqlite3.OperationalError:
                self.has_fts = False
            conn.commit()

    def store_memory(self, key: str, content: str, category: str = "general") -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check if key exists
            cursor.execute("SELECT id FROM memories WHERE key = ? AND category = ?", (key, category))
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    "UPDATE memories SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (content, row["id"])
                )
            else:
                cursor.execute(
                    "INSERT INTO memories (category, key, content) VALUES (?, ?, ?)",
                    (category, key, content)
                )
            conn.commit()
            return True

    def recall_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            results = []
            if getattr(self, "has_fts", False):
                try:
                    # Clean query for FTS5 (remove special syntax characters that break FTS)
                    clean_query = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
                    if clean_query:
                        fts_query = " OR ".join(f'"{word}"' for word in clean_query.split())
                        cursor.execute(
                            """
                            SELECT m.id, m.category, m.key, m.content, m.updated_at
                            FROM memories_fts f
                            JOIN memories m ON f.rowid = m.id
                            WHERE memories_fts MATCH ?
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (fts_query, limit)
                        )
                        for row in cursor.fetchall():
                            results.append(dict(row))
                        if results:
                            return results
                except Exception:
                    pass

            # Fallback to standard LIKE search
            search_param = f"%{query}%"
            cursor.execute(
                """
                SELECT id, category, key, content, updated_at
                FROM memories
                WHERE key LIKE ? OR content LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (search_param, search_param, limit)
            )
            for row in cursor.fetchall():
                results.append(dict(row))
            return results

    def get_all_memories(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, category, key, content, updated_at FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def save_message(self, session_id: str, role: str, content: Optional[str] = None, 
                     tool_calls: Optional[List[Dict[str, Any]]] = None, 
                     tool_call_id: Optional[str] = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO sessions (id, title) VALUES (?, ?)", (session_id, f"Session {session_id}"))
            cursor.execute(
                """
                INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    json.dumps(tool_calls) if tool_calls else None,
                    tool_call_id
                )
            )
            # Auto-name session from the first real user prompt if title is still a placeholder
            if role == "user" and content:
                cursor.execute("SELECT title FROM sessions WHERE id = ?", (session_id,))
                row = cursor.fetchone()
                if row and _is_placeholder_title(row["title"], session_id):
                    auto_title = _derive_session_title(content)
                    if auto_title:
                        cursor.execute(
                            "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (auto_title, session_id),
                        )
                        conn.commit()
                        return
            cursor.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
            conn.commit()

    def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content, tool_calls, tool_call_id FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,)
            )
            history = []
            for row in cursor.fetchall():
                msg = {"role": row["role"]}
                if row["content"] is not None:
                    msg["content"] = row["content"]
                if row["tool_calls"]:
                    msg["tool_calls"] = json.loads(row["tool_calls"])
                if row["tool_call_id"]:
                    msg["tool_call_id"] = row["tool_call_id"]
                history.append(msg)
            return history

    def create_session(self, session_id: str, title: str = "New Session"):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO sessions (id, title) VALUES (?, ?)", (session_id, title))
            conn.commit()

    def rename_session(self, session_id: str, new_title: str) -> bool:
        clean = _derive_session_title(new_title, max_len=80)
        if not clean:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (clean, session_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.id, s.title, s.summary, s.summary_msg_count, s.created_at, s.updated_at,
                       COUNT(m.id) as message_count,
                       (SELECT content FROM messages WHERE session_id = s.id AND role = 'user' ORDER BY id ASC LIMIT 1) as first_user_msg
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                WHERE s.id = ?
                GROUP BY s.id
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            if _is_placeholder_title(d.get("title"), session_id) and d.get("first_user_msg"):
                d["title"] = _derive_session_title(d["first_user_msg"])
            return d

    def set_session_summary(self, session_id: str, summary: str, msg_count: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET summary = ?, summary_msg_count = ? WHERE id = ?",
                (summary, int(msg_count), session_id),
            )
            conn.commit()

    def list_sessions(self, limit: int = 20, include_empty: bool = False) -> List[Dict[str, Any]]:
        """List past sessions with derived titles, message counts, previews, and timestamps."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            having_clause = "" if include_empty else "HAVING COUNT(m.id) > 0"
            cursor.execute(f"""
                SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) as message_count,
                       (SELECT content FROM messages WHERE session_id = s.id AND role = 'user' AND content IS NOT NULL AND content != '' ORDER BY id ASC LIMIT 1) as first_user_msg,
                       (SELECT content FROM messages WHERE session_id = s.id AND role IN ('user', 'assistant') AND content IS NOT NULL AND content != '' AND content != '[calling tools]' ORDER BY id DESC LIMIT 1) as last_msg
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                GROUP BY s.id
                {having_clause}
                ORDER BY s.updated_at DESC
                LIMIT ?
            """, (limit,))
            out: List[Dict[str, Any]] = []
            for row in cursor.fetchall():
                d = dict(row)
                sid = d["id"]
                if _is_placeholder_title(d.get("title"), sid):
                    d["title"] = _derive_session_title(d.get("first_user_msg")) or f"Session {sid}"
                d["preview"] = _derive_session_title(d.get("last_msg") or d.get("first_user_msg") or "", max_len=90)
                out.append(d)
            return out

    def search_sessions(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search past conversations across all sessions using FTS5 with LIKE fallback."""
        q = (query or "").strip()
        if not q:
            return []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = []
            if getattr(self, "has_fts", False):
                try:
                    clean_q = "".join(c for c in q if c.isalnum() or c.isspace()).strip()
                    if clean_q:
                        fts_q = " OR ".join(f'"{w}"' for w in clean_q.split())
                        cursor.execute(
                            """
                            SELECT m.session_id, COALESCE(s.title, m.session_id) as session_title,
                                   m.role, m.content, m.created_at,
                                   (SELECT content FROM messages WHERE session_id = m.session_id AND role = 'user' ORDER BY id ASC LIMIT 1) as first_user_msg
                            FROM messages_fts f
                            JOIN messages m ON f.rowid = m.id
                            LEFT JOIN sessions s ON s.id = m.session_id
                            WHERE messages_fts MATCH ? AND m.role IN ('user', 'assistant')
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (fts_q, limit),
                        )
                        rows = [dict(r) for r in cursor.fetchall()]
                except Exception:
                    rows = []

            if not rows:
                like_q = f"%{q}%"
                cursor.execute(
                    """
                    SELECT m.session_id, COALESCE(s.title, m.session_id) as session_title,
                           m.role, m.content, m.created_at,
                           (SELECT content FROM messages WHERE session_id = m.session_id AND role = 'user' ORDER BY id ASC LIMIT 1) as first_user_msg
                    FROM messages m
                    LEFT JOIN sessions s ON s.id = m.session_id
                    WHERE m.content LIKE ? AND m.role IN ('user', 'assistant') AND m.content != '[calling tools]'
                    ORDER BY m.id DESC
                    LIMIT ?
                    """,
                    (like_q, limit),
                )
                rows = [dict(r) for r in cursor.fetchall()]

            for r in rows:
                sid = r["session_id"]
                if _is_placeholder_title(r.get("session_title"), sid) and r.get("first_user_msg"):
                    r["session_title"] = _derive_session_title(r["first_user_msg"])
            return rows
