import tempfile
import unittest
from pathlib import Path

from nexus.tools.todo import TodoStore, get_todo_tools


class TodoStoreTests(unittest.TestCase):
    def test_session_tasks_persist_and_follow_status_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TodoStore(root)
            added = store.add("session-a", "Inspect project", "Read AGENTS.md first", "high")
            task_id = added["task"]["id"]

            updated = store.update("session-a", task_id, status="in_progress")
            self.assertEqual(updated["task"]["status"], "in_progress")

            completed = store.update("session-a", task_id, status="completed")
            self.assertEqual(completed["summary"]["completed"], 1)

            reopened = TodoStore(root).list("session-a")
            self.assertEqual(reopened["tasks"][0]["id"], task_id)
            self.assertEqual(reopened["tasks"][0]["status"], "completed")
            self.assertEqual(reopened["remaining"], 0)

            removed = store.remove("session-a", task_id)
            self.assertEqual(removed["removed"], task_id)
            self.assertEqual(store.list("session-a")["tasks"], [])

    def test_task_lists_are_isolated_by_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TodoStore(Path(tmp))
            a = store.add("session-a", "Build module")
            store.add("session-b", "Review docs")

            self.assertEqual([x["title"] for x in store.list("session-a")["tasks"]], ["Build module"])
            self.assertEqual([x["title"] for x in store.list("session-b")["tasks"]], ["Review docs"])
            self.assertNotEqual(a["task"]["id"], "")

    def test_task_input_validation_and_task_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TodoStore(Path(tmp))
            with self.assertRaises(ValueError):
                store.add("session-a", " ")
            with self.assertRaises(ValueError):
                store.add("session-a", "Bad priority", priority="urgent")

            for index in range(100):
                store.add("session-a", f"Task {index}")
            with self.assertRaises(ValueError):
                store.add("session-a", "Overflow")

    def test_corrupt_task_file_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TodoStore(Path(tmp))
            path = store._path_for("session-a")
            path.write_text("{broken", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                store.add("session-a", "Do not overwrite damaged data")
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


class TodoToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_uses_the_current_session_getter(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = ["session-a"]
            tool = get_todo_tools(lambda: active[0], Path(tmp))[0]

            added = await tool.execute(action="add", title="Implement feature")
            active[0] = "session-b"
            empty = await tool.execute(action="list")
            active[0] = "session-a"
            restored = await tool.execute(action="list")

            self.assertIn("task", added)
            self.assertEqual(empty["tasks"], [])
            self.assertEqual(len(restored["tasks"]), 1)
            self.assertEqual(restored["tasks"][0]["title"], "Implement feature")


if __name__ == "__main__":
    unittest.main()
