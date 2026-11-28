"""
nolthira/github_app/client.py
High-level GitHub App API client for NolthiraAgent.

Wraps common GitHub API operations using the Installation Token from GitHubAppAuth.
Supports: repos, issues, pull requests, file content, webhooks, search.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Any

import httpx

from .auth import GitHubAppAuth

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubAppClient:
    """
    Async GitHub REST API client authenticated as a GitHub App installation.

    Usage:
        client = GitHubAppClient(auth)
        repos = await client.list_repos()
        issues = await client.list_issues("owner", "repo")
        pr = await client.get_pr("owner", "repo", 42)
    """

    def __init__(self, auth: GitHubAppAuth) -> None:
        self.auth = auth

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> Any:
        headers = await self.auth.auth_headers()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{GITHUB_API}{path}", headers=headers, params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: dict) -> Any:
        headers = await self.auth.auth_headers()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{GITHUB_API}{path}", headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()

    async def _patch(self, path: str, body: dict) -> Any:
        headers = await self.auth.auth_headers()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.patch(f"{GITHUB_API}{path}", headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Repository
    # ------------------------------------------------------------------

    async def list_repos(self) -> list:
        """List all repositories accessible to this installation."""
        data = await self._get("/installation/repositories")
        return data.get("repositories", [])

    async def get_repo(self, owner: str, repo: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}")

    async def get_file(self, owner: str, repo: str, path: str, ref: str = "HEAD") -> str:
        """Return decoded file content (UTF-8) from a repository."""
        import base64
        data = await self._get(f"/repos/{owner}/{repo}/contents/{path}", {"ref": ref})
        raw = data.get("content", "")
        # GitHub returns base64 with newlines
        return base64.b64decode(raw.replace("\n", "")).decode("utf-8")

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def list_issues(
        self, owner: str, repo: str, state: str = "open", per_page: int = 20
    ) -> list:
        return await self._get(
            f"/repos/{owner}/{repo}/issues",
            {"state": state, "per_page": per_page},
        )

    async def get_issue(self, owner: str, repo: str, number: int) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/issues/{number}")

    async def create_issue_comment(
        self, owner: str, repo: str, number: int, body: str
    ) -> dict:
        return await self._post(
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            {"body": body},
        )

    async def close_issue(self, owner: str, repo: str, number: int) -> dict:
        return await self._patch(
            f"/repos/{owner}/{repo}/issues/{number}",
            {"state": "closed"},
        )

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    async def list_prs(
        self, owner: str, repo: str, state: str = "open", per_page: int = 20
    ) -> list:
        return await self._get(
            f"/repos/{owner}/{repo}/pulls",
            {"state": state, "per_page": per_page},
        )

    async def get_pr(self, owner: str, repo: str, number: int) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/pulls/{number}")

    async def get_pr_diff(self, owner: str, repo: str, number: int) -> str:
        """Return the unified diff of a pull request."""
        token = await self.auth.get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.diff",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            resp.raise_for_status()
            return resp.text

    async def create_pr_review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
    ) -> dict:
        return await self._post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            {
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
            },
        )

    async def submit_pr_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",  # APPROVE / REQUEST_CHANGES / COMMENT
    ) -> dict:
        return await self._post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            {"body": body, "event": event},
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_issues(self, query: str, per_page: int = 10) -> list:
        data = await self._get("/search/issues", {"q": query, "per_page": per_page})
        return data.get("items", [])

    async def search_code(self, query: str, per_page: int = 10) -> list:
        data = await self._get("/search/code", {"q": query, "per_page": per_page})
        return data.get("items", [])

    # ------------------------------------------------------------------
    # Webhooks (list / create)
    # ------------------------------------------------------------------

    async def list_webhooks(self, owner: str, repo: str) -> list:
        return await self._get(f"/repos/{owner}/{repo}/hooks")

    async def create_webhook(
        self,
        owner: str,
        repo: str,
        url: str,
        events: list | None = None,
        secret: str = "",
    ) -> dict:
        return await self._post(
            f"/repos/{owner}/{repo}/hooks",
            {
                "name": "web",
                "active": True,
                "events": events or ["push", "pull_request", "issues"],
                "config": {
                    "url": url,
                    "content_type": "json",
                    "secret": secret,
                    "insecure_ssl": "0",
                },
            },
        )

    # ------------------------------------------------------------------
    # Convenience: app/installation info
    # ------------------------------------------------------------------

    async def app_info(self) -> dict:
        return await self.auth.app_info()

    async def whoami(self) -> str:
        """Return a quick one-liner identifying the authenticated GitHub App."""
        info = await self.app_info()
        return f"{info.get('name', '?')} (id={info.get('id')}, slug={info.get('slug')})"
