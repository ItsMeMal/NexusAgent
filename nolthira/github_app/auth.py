"""
nolthira/github_app/auth.py
GitHub App JWT authentication + Installation Token manager.

Flow:
  1. Generate a JWT signed with the App's RSA private key (valid 10 min)
  2. Exchange JWT for an Installation Token (valid 1 h) via GitHub API
  3. Auto-refresh the Installation Token when it's < 5 min from expiry
  4. Expose get_token() — always returns a valid bearer token for GitHub API calls

Env / Config keys (read from .env):
  GITHUB_APP_ID               — numeric App ID shown on App settings page
  GITHUB_APP_PRIVATE_KEY_PATH — path to the .pem file  (preferred)
  GITHUB_APP_PRIVATE_KEY      — raw PEM content (alternative if no file)
  GITHUB_INSTALLATION_ID      — installation ID (find via /app/installations API)
"""

from __future__ import annotations

import os
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional

import jwt  # PyJWT >=2
import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
JWT_LIFETIME_S = 540       # 9 minutes (GitHub max is 10)
TOKEN_REFRESH_BUFFER_S = 300  # refresh Installation Token 5 min before expiry


class GitHubAppAuth:
    """
    Manages GitHub App JWT generation and Installation Token lifecycle.

    Usage:
        auth = GitHubAppAuth(app_id=12345, private_key_pem=..., installation_id=67890)
        token = await auth.get_token()   # always fresh
        headers = await auth.auth_headers()
    """

    def __init__(
        self,
        app_id: int,
        private_key_pem: str,
        installation_id: int,
    ) -> None:
        self.app_id = int(app_id)
        self.installation_id = int(installation_id)
        self._private_key_pem: str = private_key_pem.strip()
        self._installation_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Class-method constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "GitHubAppAuth":
        """Build instance from environment variables / .env."""
        app_id = os.getenv("GITHUB_APP_ID")
        inst_id = os.getenv("GITHUB_INSTALLATION_ID")
        pem_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
        pem_raw = os.getenv("GITHUB_APP_PRIVATE_KEY")

        if not app_id:
            raise ValueError("GITHUB_APP_ID not set in environment")
        if not inst_id:
            raise ValueError("GITHUB_INSTALLATION_ID not set in environment")

        if pem_path and Path(pem_path).exists():
            pem = Path(pem_path).read_text()
        elif pem_raw:
            # Allow \\n literals in env value
            pem = pem_raw.replace("\\n", "\n")
        else:
            raise ValueError(
                "Neither GITHUB_APP_PRIVATE_KEY_PATH nor GITHUB_APP_PRIVATE_KEY is set"
            )

        return cls(app_id=int(app_id), private_key_pem=pem, installation_id=int(inst_id))

    @classmethod
    def available(cls) -> bool:
        """Return True if the minimum env vars are present to construct an auth instance."""
        return bool(
            os.getenv("GITHUB_APP_ID")
            and os.getenv("GITHUB_INSTALLATION_ID")
            and (
                os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
                or os.getenv("GITHUB_APP_PRIVATE_KEY")
            )
        )

    # ------------------------------------------------------------------
    # JWT generation (synchronous — CPU only, no I/O)
    # ------------------------------------------------------------------

    def _generate_jwt(self) -> str:
        """Return a freshly-signed GitHub App JWT (valid ~9 min)."""
        now = int(time.time())
        payload = {
            "iat": now - 60,          # issued-at: 60 s in the past (clock skew)
            "exp": now + JWT_LIFETIME_S,
            "iss": str(self.app_id),
        }
        token = jwt.encode(payload, self._private_key_pem, algorithm="RS256")
        # PyJWT >=2 returns str; older versions return bytes
        return token if isinstance(token, str) else token.decode()

    # ------------------------------------------------------------------
    # Installation Token (async — HTTP call)
    # ------------------------------------------------------------------

    async def _fetch_installation_token(self) -> tuple[str, float]:
        """Call GitHub API to get a new Installation Token. Returns (token, expires_at)."""
        jwt_token = self._generate_jwt()
        url = f"{GITHUB_API}/app/installations/{self.installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        token = data["token"]
        # expires_at is ISO 8601 — convert to epoch
        import datetime
        exp_str = data.get("expires_at", "")
        try:
            exp = datetime.datetime.fromisoformat(exp_str.replace("Z", "+00:00")).timestamp()
        except Exception:
            exp = time.time() + 3600  # fallback: 1 hour

        logger.info(
            "GitHub App: got new installation token (expires %s)", exp_str
        )
        return token, exp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_token(self) -> str:
        """
        Return a valid GitHub Installation Token, refreshing automatically
        when < TOKEN_REFRESH_BUFFER_S seconds remain.
        Thread/task-safe via asyncio.Lock.
        """
        async with self._lock:
            remaining = self._token_expires_at - time.time()
            if self._installation_token is None or remaining < TOKEN_REFRESH_BUFFER_S:
                self._installation_token, self._token_expires_at = (
                    await self._fetch_installation_token()
                )
            return self._installation_token

    async def auth_headers(self) -> dict:
        """Return Authorization + Accept headers ready to pass to httpx/aiohttp."""
        token = await self.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def app_info(self) -> dict:
        """Return basic info about the installed GitHub App (name, slug, permissions)."""
        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{GITHUB_API}/app", headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def list_installations(self) -> list:
        """List all installations of this GitHub App."""
        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{GITHUB_API}/app/installations", headers=headers)
            resp.raise_for_status()
            return resp.json()
