import sqlite3
import tempfile
import unittest
from pathlib import Path

from nexus.memory import SQLiteMemory


class MemoryGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "memory.db"
        self.memory = SQLiteMemory(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_proposals_are_invisible_until_approved(self):
        proposal_id = self.memory.propose_memory(
            key="preferred_editor",
            content="Use Neovim for terminal editing.",
            category="preference",
            source="agent_inference",
            confidence=0.72,
            evidence="User repeatedly requested Neovim-specific instructions.",
        )
        self.assertEqual(
            self.memory.propose_memory(
                key="preferred_editor",
                content="Use Neovim for terminal editing.",
                category="preference",
            ),
            proposal_id,
        )
        self.assertEqual(self.memory.get_all_memories(), [])
        self.assertEqual(self.memory.recall_memories("Neovim"), [])
        self.assertEqual(len(self.memory.list_memory_proposals("pending")), 1)

        self.assertTrue(self.memory.review_memory_proposal(proposal_id, "approve", reason="Confirmed"))
        active = self.memory.recall_memories("Neovim")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["key"], "preferred_editor")
        self.assertEqual(active[0]["source"], "agent_inference")
        self.assertEqual(active[0]["evidence"], "User repeatedly requested Neovim-specific instructions.")
        self.assertEqual(self.memory.list_memory_proposals("pending"), [])
        self.assertEqual(self.memory.list_memory_proposals("approved")[0]["id"], proposal_id)

    def test_concurrent_proposal_reviews_are_applied_exactly_once(self):
        from concurrent.futures import ThreadPoolExecutor

        proposal_id = self.memory.propose_memory(
            key="reviewed_once",
            content="This proposal should enter active memory once.",
            category="learning",
            evidence="Concurrent review regression test.",
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _: self.memory.review_memory_proposal(proposal_id, "approve"),
                range(2),
            ))
        self.assertEqual(sorted(results), [False, True])
        active = [item for item in self.memory.get_all_memories() if item["key"] == "reviewed_once"]
        self.assertEqual(len(active), 1)
        self.assertEqual(self.memory.list_memory_proposals("approved")[0]["id"], proposal_id)

    def test_rejected_proposal_never_enters_active_memory(self):
        proposal_id = self.memory.propose_memory(
            key="assumed_preference",
            content="Assumed preference",
        )
        self.assertTrue(self.memory.review_memory_proposal(proposal_id, "reject", reason="Not accurate"))
        self.assertEqual(self.memory.get_all_memories(), [])
        self.assertEqual(self.memory.list_memory_proposals("rejected")[0]["review_reason"], "Not accurate")
        self.assertFalse(self.memory.review_memory_proposal(proposal_id, "approve"))

    def test_updates_keep_prior_value_and_provenance(self):
        self.memory.store_memory(
            key="preferred_language",
            content="Indonesian",
            category="preference",
            source="user_explicit",
            confidence=1.0,
            evidence="User explicitly requested Indonesian.",
        )
        memory_id = self.memory.get_all_memories()[0]["id"]
        self.memory.store_memory(
            key="preferred_language",
            content="English",
            category="preference",
            source="user_explicit",
            confidence=1.0,
            evidence="User changed preference.",
        )
        current = self.memory.get_all_memories()[0]
        self.assertEqual(current["id"], memory_id)
        self.assertEqual(current["content"], "English")
        history = self.memory.get_memory_history(memory_id)
        self.assertEqual(history[0]["action"], "updated")
        self.assertEqual(history[0]["snapshot"]["content"], "Indonesian")

    def test_archive_and_restore_control_recall_without_losing_history(self):
        self.memory.store_memory("project", "NexusAgent", category="work")
        memory_id = self.memory.get_all_memories()[0]["id"]
        self.assertTrue(self.memory.archive_memory(memory_id, reason="Project completed"))
        self.assertEqual(self.memory.get_all_memories(), [])
        self.assertEqual(self.memory.recall_memories("NexusAgent"), [])
        self.assertTrue(self.memory.restore_memory(memory_id, reason="Project resumed"))
        self.assertEqual(self.memory.get_all_memories()[0]["content"], "NexusAgent")
        self.assertEqual(
            [item["action"] for item in self.memory.get_memory_history(memory_id)],
            ["restored", "archived"],
        )

    def test_permanent_delete_also_purges_revision_snapshots(self):
        self.memory.store_memory("temporary", "Sensitive value", category="test")
        memory_id = self.memory.get_all_memories()[0]["id"]
        self.memory.store_memory("temporary", "Updated sensitive value", category="test")
        self.assertTrue(self.memory.get_memory_history(memory_id))
        self.assertTrue(self.memory.delete_memory(memory_id, reason="User requested deletion"))
        self.assertEqual(self.memory.get_all_memories(), [])
        self.assertEqual(self.memory.get_memory_history(memory_id), [])

    def test_existing_sqlite_memory_database_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            with sqlite3.connect(path) as conn:
                conn.execute("""
                    CREATE TABLE memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT,
                        key TEXT,
                        content TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute(
                    "INSERT INTO memories(category, key, content) VALUES (?, ?, ?)",
                    ("legacy", "old_fact", "Existing memory remains available."),
                )
            migrated = SQLiteMemory(path)
            rows = migrated.get_all_memories()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["content"], "Existing memory remains available.")
            self.assertEqual(rows[0]["source"], "legacy")
            self.assertEqual(rows[0]["status"], "active")
            self.assertIsNotNone(rows[0]["created_at"])


if __name__ == "__main__":
    unittest.main()
