"""Governed long-term memory: provenance, review queue, and change history."""

import json
from typing import Any, Dict, List, Optional


class MemoryGovernanceMixin:
    """Add reviewable learning and auditable lifecycle operations to SQLiteMemory."""

    def _init_governance(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            columns = {row[1] for row in cursor.execute("PRAGMA table_info(memories)").fetchall()}
            migrations = {
                "status": "TEXT NOT NULL DEFAULT 'active'",
                "source": "TEXT NOT NULL DEFAULT 'legacy'",
                "confidence": "REAL NOT NULL DEFAULT 0.5",
                "evidence": "TEXT",
                "session_id": "TEXT",
                "created_at": "TIMESTAMP",
            }
            for name, declaration in migrations.items():
                if name not in columns:
                    cursor.execute(f"ALTER TABLE memories ADD COLUMN {name} {declaration}")
            # Backfill the external-content FTS index before updating legacy rows.
            # Otherwise its UPDATE trigger may try to delete a row that was never indexed.
            if getattr(self, "has_fts", False):
                cursor.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
            cursor.execute(
                "UPDATE memories SET created_at = COALESCE(created_at, updated_at, CURRENT_TIMESTAMP)"
            )
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'agent_learning',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence TEXT,
                    session_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    review_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    changed_by TEXT NOT NULL DEFAULT 'agent',
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_status_updated ON memories(status, updated_at DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_proposals_status ON memory_proposals(status, created_at DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_revisions_memory ON memory_revisions(memory_id, created_at DESC)"
            )

    @staticmethod
    def _clean_text(value: Any, field: str, max_length: int) -> str:
        clean = str(value or "").strip()
        if not clean:
            raise ValueError(f"{field} must not be empty.")
        if len(clean) > max_length:
            raise ValueError(f"{field} exceeds {max_length} characters.")
        return clean

    @staticmethod
    def _record_revision(
        cursor: Any,
        row: Any,
        action: str,
        changed_by: str = "agent",
        reason: str = "",
    ) -> None:
        snapshot = {
            key: row[key]
            for key in (
                "id", "category", "key", "content", "status", "source",
                "confidence", "evidence", "session_id", "created_at", "updated_at",
            )
            if key in row.keys()
        }
        cursor.execute(
            """
            INSERT INTO memory_revisions (memory_id, action, snapshot_json, changed_by, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                action,
                json.dumps(snapshot, ensure_ascii=False, default=str),
                changed_by,
                reason or None,
            ),
        )

    def store_memory(
        self,
        key: str,
        content: str,
        category: str = "general",
        source: str = "agent_direct",
        confidence: float = 0.6,
        evidence: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Persist an approved memory and preserve the previous value in its revision history."""
        clean_key = self._clean_text(key, "key", 160)
        clean_content = self._clean_text(content, "content", 12000)
        clean_category = self._clean_text(category, "category", 80)
        clean_source = self._clean_text(source, "source", 80)
        score = float(confidence)
        if not 0.0 <= score <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")
        clean_evidence = str(evidence or "").strip()[:4000] or None
        clean_session = str(session_id or "").strip()[:120] or None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM memories WHERE key = ? AND category = ? ORDER BY id LIMIT 1",
                (clean_key, clean_category),
            )
            existing = cursor.fetchone()
            if existing:
                self._record_revision(
                    cursor,
                    existing,
                    action="updated",
                    changed_by=clean_source,
                    reason="Memory value replaced.",
                )
                cursor.execute(
                    """
                    UPDATE memories
                    SET content = ?, source = ?, confidence = ?, evidence = ?,
                        session_id = ?, status = 'active', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        clean_content, clean_source, score, clean_evidence,
                        clean_session, existing["id"],
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO memories
                        (category, key, content, status, source, confidence, evidence, session_id, created_at)
                    VALUES (?, ?, ?, 'active', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        clean_category, clean_key, clean_content, clean_source,
                        score, clean_evidence, clean_session,
                    ),
                )
        return True

    def propose_memory(
        self,
        key: str,
        content: str,
        category: str = "learning",
        source: str = "agent_learning",
        confidence: float = 0.7,
        evidence: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Queue a candidate memory; it is invisible to recall until approved."""
        clean_key = self._clean_text(key, "key", 160)
        clean_content = self._clean_text(content, "content", 12000)
        clean_category = self._clean_text(category, "category", 80)
        clean_source = self._clean_text(source, "source", 80)
        score = float(confidence)
        if not 0.0 <= score <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")
        clean_evidence = str(evidence or "").strip()[:4000] or None
        clean_session = str(session_id or "").strip()[:120] or None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id FROM memory_proposals
                WHERE status = 'pending' AND category = ? AND key = ? AND content = ?
                ORDER BY id DESC LIMIT 1
                """,
                (clean_category, clean_key, clean_content),
            )
            existing = cursor.fetchone()
            if existing:
                return int(existing["id"])
            cursor.execute(
                """
                INSERT INTO memory_proposals
                    (category, key, content, source, confidence, evidence, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_category, clean_key, clean_content, clean_source,
                    score, clean_evidence, clean_session,
                ),
            )
            return int(cursor.lastrowid)

    def list_memory_proposals(self, status: str = "pending", limit: int = 20) -> List[Dict[str, Any]]:
        clean_status = str(status or "pending").strip().lower()
        if clean_status not in {"pending", "approved", "rejected"}:
            raise ValueError("status must be pending, approved, or rejected.")
        safe_limit = max(1, min(int(limit), 100))
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, category, key, content, source, confidence, evidence,
                       session_id, status, review_reason, created_at, reviewed_at
                FROM memory_proposals
                WHERE status = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (clean_status, safe_limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def review_memory_proposal(
        self,
        proposal_id: int,
        decision: str,
        reviewer: str = "user",
        reason: str = "",
    ) -> bool:
        """Atomically approve into active memory or reject without mutating active facts."""
        choice = str(decision or "").strip().lower()
        if choice not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject.")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Serialize reviewers so a rejected proposal cannot race with an approval
            # that has already written the candidate into active memory.
            cursor.execute("BEGIN IMMEDIATE")
            row = cursor.execute(
                "SELECT * FROM memory_proposals WHERE id = ? AND status = 'pending'",
                (int(proposal_id),),
            ).fetchone()
            if not row:
                return False
            proposal = dict(row)

            if choice == "approve":
                cursor.execute(
                    "SELECT * FROM memories WHERE key = ? AND category = ? ORDER BY id LIMIT 1",
                    (proposal["key"], proposal["category"]),
                )
                existing = cursor.fetchone()
                if existing:
                    self._record_revision(
                        cursor,
                        existing,
                        action="updated",
                        changed_by=reviewer,
                        reason=f"Approved learning proposal #{proposal_id}.",
                    )
                    cursor.execute(
                        """
                        UPDATE memories
                        SET content = ?, source = ?, confidence = ?, evidence = ?,
                            session_id = ?, status = 'active', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            proposal["content"], proposal["source"], proposal["confidence"],
                            proposal["evidence"], proposal["session_id"], existing["id"],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO memories
                            (category, key, content, status, source, confidence, evidence, session_id, created_at)
                        VALUES (?, ?, ?, 'active', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            proposal["category"], proposal["key"], proposal["content"],
                            proposal["source"], proposal["confidence"], proposal["evidence"],
                            proposal["session_id"],
                        ),
                    )

            final_status = "approved" if choice == "approve" else "rejected"
            cursor.execute(
                """
                UPDATE memory_proposals
                SET status = ?, review_reason = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (
                    final_status,
                    str(reason or "").strip()[:1000] or None,
                    int(proposal_id),
                ),
            )
            return cursor.rowcount == 1

    def recall_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        safe_limit = max(1, min(int(limit), 100))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if getattr(self, "has_fts", False):
                clean_query = "".join(c for c in q if c.isalnum() or c.isspace()).strip()
                if clean_query:
                    fts_query = " OR ".join(f'"{word}"' for word in clean_query.split())
                    try:
                        cursor.execute(
                            """
                            SELECT m.id, m.category, m.key, m.content, m.status, m.source,
                                   m.confidence, m.evidence, m.session_id, m.created_at, m.updated_at
                            FROM memories_fts f
                            JOIN memories m ON f.rowid = m.id
                            WHERE memories_fts MATCH ? AND m.status = 'active'
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (fts_query, safe_limit),
                        )
                        results = [dict(row) for row in cursor.fetchall()]
                        if results:
                            return results
                    except Exception:
                        pass
            like = f"%{q}%"
            rows = cursor.execute(
                """
                SELECT id, category, key, content, status, source, confidence, evidence,
                       session_id, created_at, updated_at
                FROM memories
                WHERE status = 'active' AND (key LIKE ? OR content LIKE ? OR category LIKE ?)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, safe_limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_memories(self, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, category, key, content, status, source, confidence,
                       evidence, session_id, created_at, updated_at
                FROM memories
                WHERE status = 'active'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def archive_memory(self, memory_id: int, reason: str = "", changed_by: str = "user") -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND status = 'active'", (int(memory_id),)
            ).fetchone()
            if not row:
                return False
            self._record_revision(cursor, row, "archived", changed_by, reason)
            cursor.execute(
                "UPDATE memories SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(memory_id),),
            )
            return True

    def restore_memory(self, memory_id: int, reason: str = "", changed_by: str = "user") -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND status = 'archived'", (int(memory_id),)
            ).fetchone()
            if not row:
                return False
            self._record_revision(cursor, row, "restored", changed_by, reason)
            cursor.execute(
                "UPDATE memories SET status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(memory_id),),
            )
            return True

    def delete_memory(self, memory_id: int, reason: str = "", changed_by: str = "user") -> bool:
        # Privacy deletion is intentionally different from archive: remove both the
        # row and its historical snapshots so deleted content is not retained.
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT id FROM memories WHERE id = ?", (int(memory_id),)
            ).fetchone()
            if not row:
                return False
            cursor.execute("DELETE FROM memory_revisions WHERE memory_id = ?", (int(memory_id),))
            cursor.execute("DELETE FROM memories WHERE id = ?", (int(memory_id),))
            return cursor.rowcount == 1

    def get_memory_history(self, memory_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, memory_id, action, snapshot_json, changed_by, reason, created_at
                FROM memory_revisions
                WHERE memory_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(memory_id), safe_limit),
            ).fetchall()
            history = []
            for row in rows:
                item = dict(row)
                try:
                    item["snapshot"] = json.loads(item.pop("snapshot_json"))
                except (TypeError, ValueError):
                    item["snapshot"] = {}
                history.append(item)
            return history
