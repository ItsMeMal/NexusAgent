import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

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

    def list_sessions(self, limit: int = 15) -> List[Dict[str, Any]]:
        """List past sessions with message counts and timestamps."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) as message_count
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
