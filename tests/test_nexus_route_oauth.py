import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from nolthira.providers.nexus_route_oauth import NexusRouteOAuth


class NexusRouteOAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_rotates_and_persists_token_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            oauth = NexusRouteOAuth(store_path=Path(temp_dir) / "oauth" / "route.json")
            oauth._save({
                "access_token": "expired",
                "refresh_token": "refresh-old",
                "expires_at": time.time() - 1,
                "refresh_expires_at": time.time() + 3600,
                "user": {},
            })
            oauth._post_form = AsyncMock(return_value={
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_in": 3600,
                "refresh_expires_in": 86400,
            })
            self.assertEqual(await oauth.get_access_token(), "access-new")
            oauth._post_form.assert_awaited_once()
            self.assertEqual(oauth._load()["refresh_token"], "refresh-new")

    async def test_missing_session_requires_signin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            oauth = NexusRouteOAuth(store_path=Path(temp_dir) / "missing.json")
            with self.assertRaisesRegex(RuntimeError, "Use /provider"):
                await oauth.get_access_token()


if __name__ == "__main__":
    unittest.main()
