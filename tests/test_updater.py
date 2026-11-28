import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from rich.console import Console

from nolthira import updater
from nolthira.ui import tui


class UpdateCacheTests(unittest.TestCase):
    def test_cached_update_compares_full_commit_shas(self):
        local_sha = "a" * 40
        remote_sha = "b" * 40
        now = 1_800_000_000.0

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "update-cache.json"
            with patch.object(updater, "CACHE_FILE", cache):
                updater._write_update_cache(local_sha, remote_sha, "New release", now)
                hit, payload = updater._read_update_cache(local_sha, now + 1)

            self.assertTrue(hit)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["full_remote_sha"], remote_sha)
            self.assertEqual(payload["remote_sha"], remote_sha[:7])
            self.assertTrue(payload["update_available"])

    def test_cache_is_invalidated_when_local_commit_changes(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "update-cache.json"
            with patch.object(updater, "CACHE_FILE", cache):
                updater._write_update_cache("a" * 40, "b" * 40, "New release", now)
                hit, payload = updater._read_update_cache("c" * 40, now + 1)
        self.assertFalse(hit)
        self.assertIsNone(payload)

    def test_legacy_short_sha_cache_is_ignored(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "update-cache.json"
            cache.write_text(json.dumps({
                "schema": 2,
                "timestamp": now,
                "local_sha": "a" * 7,
                "remote_sha": "b" * 7,
                "update_available": True,
            }), encoding="utf-8")
            with patch.object(updater, "CACHE_FILE", cache):
                hit, payload = updater._read_update_cache("a" * 40, now + 1)
        self.assertFalse(hit)
        self.assertIsNone(payload)


class UpdateCheckErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_network_failure_is_reported_not_hidden_as_current(self):
        class OfflineClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url):
                raise httpx.ConnectError("offline")

        with patch.object(updater, "get_local_commit", return_value="a" * 40), patch.object(
            updater.httpx, "AsyncClient", return_value=OfflineClient()
        ):
            result = await updater.check_for_update(force=True)

        self.assertFalse(result["update_available"])
        self.assertIn("check_error", result)
        self.assertIn("ConnectError", result["check_error"])

    def test_manual_update_card_displays_check_failure(self):
        import io

        buffer = io.StringIO()
        original_console = tui.console
        tui.console = Console(file=buffer, width=100, force_terminal=False)
        try:
            tui.render_update_card({
                "update_available": False,
                "check_error": "Could not reach GitHub: ConnectError.",
            })
        finally:
            tui.console = original_console

        rendered = buffer.getvalue()
        self.assertIn("Could not check for updates", rendered)
        self.assertNotIn("up to date", rendered.lower())


if __name__ == "__main__":
    unittest.main()
