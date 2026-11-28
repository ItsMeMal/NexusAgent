import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.checkpoints import CheckpointError, CheckpointManager
from nexus.tools.checkpoint_tools import get_checkpoint_tools


class CheckpointManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.workspace = root / "project"
        self.workspace.mkdir()
        self.storage = root / "checkpoint-storage"
        self.manager = CheckpointManager(self.workspace, self.storage)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_is_secret_safe_and_excludes_generated_directories(self):
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (self.workspace / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
        (self.workspace / ".env.example").write_text("API_KEY=replace-me\n", encoding="utf-8")
        (self.workspace / ".git").mkdir()
        (self.workspace / ".git" / "config").write_text("private git internals\n", encoding="utf-8")
        (self.workspace / "node_modules").mkdir()
        (self.workspace / "node_modules" / "package.js").write_text("generated\n", encoding="utf-8")
        (self.workspace / "private.pem").write_text("private key\n", encoding="utf-8")

        checkpoint = self.manager.create_checkpoint("before coding")

        self.assertEqual(checkpoint["file_count"], 2)
        self.assertTrue(Path(checkpoint["archive"]).is_file())
        with __import__("zipfile").ZipFile(checkpoint["archive"]) as archive:
            names = set(archive.namelist())
        self.assertIn("src/main.py", names)
        self.assertIn(".env.example", names)
        self.assertNotIn(".env", names)
        self.assertNotIn("private.pem", names)
        self.assertNotIn(".git/config", names)
        self.assertNotIn("node_modules/package.js", names)

    def test_overlay_restore_restores_snapshot_files_without_deleting_new_files(self):
        source = self.workspace / "main.py"
        source.write_text("version = 1\n", encoding="utf-8")
        checkpoint = self.manager.create_checkpoint("before refactor")
        source.write_text("version = 2\n", encoding="utf-8")
        (self.workspace / "new_file.py").write_text("new = True\n", encoding="utf-8")

        result = self.manager.restore_checkpoint(checkpoint["id"], mode="overlay")

        self.assertEqual(source.read_text(encoding="utf-8"), "version = 1\n")
        self.assertTrue((self.workspace / "new_file.py").exists())
        self.assertEqual(result["restored_files"], 1)
        self.assertEqual(result["deleted_new_files"], 0)
        self.assertNotEqual(result["safety_checkpoint_id"], checkpoint["id"])
        self.assertTrue(self.manager.inspect_checkpoint(result["safety_checkpoint_id"]))

    def test_exact_restore_requires_confirmation_and_removes_eligible_new_files(self):
        source = self.workspace / "main.py"
        source.write_text("version = 1\n", encoding="utf-8")
        checkpoint = self.manager.create_checkpoint("known good")
        source.write_text("version = 2\n", encoding="utf-8")
        (self.workspace / "generated.py").write_text("generated = True\n", encoding="utf-8")

        with self.assertRaises(CheckpointError):
            self.manager.restore_checkpoint(checkpoint["id"], mode="exact")

        result = self.manager.restore_checkpoint(
            checkpoint["id"], mode="exact", confirm_exact=True
        )

        self.assertEqual(source.read_text(encoding="utf-8"), "version = 1\n")
        self.assertFalse((self.workspace / "generated.py").exists())
        self.assertEqual(result["mode"], "exact")
        self.assertEqual(result["deleted_new_files"], 1)

    def test_exact_restore_is_blocked_when_snapshot_skipped_files(self):
        large_but_allowed = self.workspace / "important.bin"
        large_but_allowed.write_bytes(b"not captured because aggregate budget is tiny")
        self.manager.MAX_TOTAL_BYTES = 1
        checkpoint = self.manager.create_checkpoint("incomplete due to budget")
        self.assertGreater(checkpoint["skipped_count"], 0)

        with self.assertRaisesRegex(CheckpointError, "skipped one or more files"):
            self.manager.restore_checkpoint(
                checkpoint["id"], mode="exact", confirm_exact=True
            )

        self.assertTrue(large_but_allowed.exists())


    def test_restore_refuses_to_overwrite_live_file_not_captured_by_safety_snapshot(self):
        source = self.workspace / "main.py"
        source.write_text("old", encoding="utf-8")
        self.manager.MAX_FILE_BYTES = 5
        checkpoint = self.manager.create_checkpoint("small original")
        source.write_text("newer user changes exceed snapshot file limit", encoding="utf-8")

        with self.assertRaisesRegex(CheckpointError, "could not capture files"):
            self.manager.restore_checkpoint(checkpoint["id"], mode="overlay")

        self.assertEqual(
            source.read_text(encoding="utf-8"),
            "newer user changes exceed snapshot file limit",
        )

    def test_checkpoint_cannot_be_restored_into_a_different_workspace(self):
        checkpoint = self.manager.create_checkpoint("workspace identity")
        other = self.workspace.parent / "other-project"
        other.mkdir()
        other_manager = CheckpointManager(other, self.storage)
        with self.assertRaisesRegex(CheckpointError, "different workspace"):
            other_manager.inspect_checkpoint(checkpoint["id"])

    def test_invalid_checkpoint_paths_are_rejected(self):
        for path in ("../escape.py", "/absolute.py", r"..\escape.py", "C:/escape.py"):
            with self.subTest(path=path):
                with self.assertRaises(CheckpointError):
                    self.manager._safe_relative_path(path)

    def test_checkpoint_tools_are_registered(self):
        with patch("nexus.checkpoints.manager.Path.home", return_value=self.workspace.parent):
            names = {tool.name for tool in get_checkpoint_tools(self.workspace)}
        self.assertEqual(
            names,
            {"create_checkpoint", "list_checkpoints", "inspect_checkpoint", "restore_checkpoint"},
        )


if __name__ == "__main__":
    unittest.main()
