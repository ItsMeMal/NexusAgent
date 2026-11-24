import time
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional

class CronScheduler:
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    schedule TEXT,
                    instruction TEXT,
                    status TEXT DEFAULT 'active',
                    last_run TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def add_task(self, name: str, schedule: str, instruction: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO scheduled_tasks (name, schedule, instruction) VALUES (?, ?, ?)",
                (name, schedule, instruction)
            )
            conn.commit()
            return cursor.lastrowid

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scheduled_tasks ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def cancel_task(self, task_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE scheduled_tasks SET status = 'cancelled' WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0
