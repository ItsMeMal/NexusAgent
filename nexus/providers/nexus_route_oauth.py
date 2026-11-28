"""Mallss Nexus Route OAuth 2.0 Authorization Code + PKCE client."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..config import NOLTHIRA_HOME

DEFAULT_BASE_URL = "https://ai-router.mallss-nexus.sbs"
CLIENT_ID = "nexusagent"
SCOPE = "models:read inference"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "OAuth request failed")
        if isinstance(error, str):
            return error
        return str(payload.get("message") or "OAuth request failed")
    return "OAuth request failed"


class NexusRouteOAuth:
    """Browser login client for the first-party Mallss Nexus Route gateway."""

    def __init__(self, store_path: Optional[Path] = None, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.store_path = store_path or (NOLTHIRA_HOME / "oauth" / "mallss_nexus_route.json")

    def _load(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("refresh_token"):
                return value
        except (OSError, ValueError, TypeError):
            pass
        return {}

    def has_session(self) -> bool:
        return bool(self._load().get("refresh_token"))

    def _save(self, value: Dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".mallss-oauth-", suffix=".tmp", dir=str(self.store_path.parent))
        temp_path = Path(temp_name)
        try:
            if os.name != "nt":
                os.chmod(temp_path, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.store_path)
            if os.name != "nt":
                os.chmod(self.store_path, 0o600)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    async def _post_form(self, path: str, data: Dict[str, str]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.post(self.base_url + path, data=data, headers={"Accept": "application/json"})
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(_error_message(payload) + f" (HTTP {response.status_code})")
        if not isinstance(payload, dict):
            raise RuntimeError("OAuth server returned an invalid token response.")
        return payload

    async def login(self, timeout: int = 240) -> Dict[str, Any]:
        """Open the first-party authorization page and complete a loopback PKCE exchange."""
        state = _b64url(secrets.token_bytes(32))
        verifier = _b64url(secrets.token_bytes(48))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        callback_result: asyncio.Future[Dict[str, str]] = asyncio.get_running_loop().create_future()

        async def handle_callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                request_line = (await asyncio.wait_for(reader.readline(), timeout=10)).decode("latin-1").strip()
                parts = request_line.split()
                target = parts[1] if len(parts) >= 2 else "/"
                while True:
                    header = await asyncio.wait_for(reader.readline(), timeout=5)
                    if header in (b"\r\n", b"\n", b""):
                        break
                parsed = urllib.parse.urlsplit(target)
                query = urllib.parse.parse_qs(parsed.query)
                result = {
                    "path": parsed.path,
                    "state": (query.get("state") or [""])[0],
                    "code": (query.get("code") or [""])[0],
                    "error": (query.get("error") or [""])[0],
                }
                if parsed.path != "/oauth/callback":
                    body, status = b"Invalid OAuth callback. Close this tab.", "404 Not Found"
                elif result["state"] != state:
                    body, status = b"OAuth state validation failed. Return to NexusAgent.", "400 Bad Request"
                    if not callback_result.done():
                        callback_result.set_exception(RuntimeError("OAuth state validation failed."))
                elif result["error"]:
                    body, status = b"Authorization was not completed. Return to NexusAgent.", "400 Bad Request"
                    if not callback_result.done():
                        callback_result.set_exception(RuntimeError("Authorization was denied or cancelled: " + result["error"]))
                elif result["code"]:
                    body, status = b"Account connected. You can close this browser tab.", "200 OK"
                    if not callback_result.done():
                        callback_result.set_result(result)
                else:
                    body, status = b"OAuth callback did not include an authorization code.", "400 Bad Request"
                    if not callback_result.done():
                        callback_result.set_exception(RuntimeError("OAuth callback did not include an authorization code."))
                writer.write(
                    f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                    f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode("ascii") + body
                )
                await writer.drain()
            except Exception as exc:
                if not callback_result.done():
                    callback_result.set_exception(exc)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        server = await asyncio.start_server(handle_callback, host="127.0.0.1", port=0)
        port = int(server.sockets[0].getsockname()[1])
        redirect_uri = f"http://127.0.0.1:{port}/oauth/callback"
        query = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        authorize_url = self.base_url + "/auth/oauth/authorize?" + query
        try:
            opened = await asyncio.to_thread(webbrowser.open, authorize_url, 2)
            if not opened:
                print("Open this Mallss Nexus Route authorization URL in your browser:")
                print(authorize_url)
            callback = await asyncio.wait_for(callback_result, timeout=max(30, min(int(timeout), 600)))
        finally:
            server.close()
            await server.wait_closed()

        payload = await self._post_form("/auth/oauth/token", {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": callback["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        })
        access_token = str(payload.get("access_token") or "")
        refresh_token = str(payload.get("refresh_token") or "")
        if not access_token or not refresh_token:
            raise RuntimeError("OAuth server did not return both access and refresh tokens.")
        now = time.time()
        saved = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": now + int(payload.get("expires_in") or 3600),
            "refresh_expires_at": now + int(payload.get("refresh_expires_in") or 2592000),
            "user": payload.get("user") if isinstance(payload.get("user"), dict) else {},
        }
        self._save(saved)
        return saved

    async def get_access_token(self) -> str:
        """Return a live access token and rotate its refresh token before expiry."""
        saved = self._load()
        if not saved:
            raise RuntimeError("No Mallss Nexus Route account session. Use /provider and sign in.")
        access_token = str(saved.get("access_token") or "")
        if access_token and float(saved.get("expires_at") or 0) > time.time() + 90:
            return access_token
        refresh_token = str(saved.get("refresh_token") or "")
        if not refresh_token or float(saved.get("refresh_expires_at") or 0) <= time.time():
            raise RuntimeError("Mallss Nexus Route login expired. Use /provider to sign in again.")
        payload = await self._post_form("/auth/oauth/token", {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        })
        next_access = str(payload.get("access_token") or "")
        next_refresh = str(payload.get("refresh_token") or "")
        if not next_access or not next_refresh:
            raise RuntimeError("OAuth refresh did not return rotated access and refresh tokens.")
        now = time.time()
        saved.update({
            "access_token": next_access,
            "refresh_token": next_refresh,
            "expires_at": now + int(payload.get("expires_in") or 3600),
            "refresh_expires_at": now + int(payload.get("refresh_expires_in") or 2592000),
            "user": payload.get("user") if isinstance(payload.get("user"), dict) else saved.get("user", {}),
        })
        self._save(saved)
        return next_access

    async def logout(self) -> None:
        saved = self._load()
        refresh_token = str(saved.get("refresh_token") or "")
        try:
            if refresh_token:
                await self._post_form("/auth/oauth/revoke", {
                    "client_id": CLIENT_ID,
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                })
        finally:
            self.store_path.unlink(missing_ok=True)
