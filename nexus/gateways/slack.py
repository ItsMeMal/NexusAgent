"""
nexus/gateways/slack.py
Slack Web API Gateway adapter (zero external SDK required).
Polls configured channel IDs via conversations.history and posts replies via chat.postMessage.
"""

import asyncio
import datetime
import os
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseGateway, GatewayMessage, chunk_text, parse_allow_list


class SlackGateway(BaseGateway):
    platform_name = "slack"

    @property
    def token(self) -> str:
        return os.getenv("SLACK_BOT_TOKEN", "").strip()

    @property
    def channels(self) -> List[str]:
        return [c.strip() for c in os.getenv("SLACK_CHANNEL_IDS", "").split(",") if c.strip()]

    def is_configured(self) -> bool:
        t = self.token
        return bool(t and t.startswith("xoxb-"))

    def get_allowed_users(self) -> List[str]:
        return parse_allow_list(os.getenv("SLACK_ALLOWED_USERS", ""))

    async def send_text(self, chat_id: str, text: str) -> bool:
        if not self.is_configured() or not text:
            return False
        ok = True
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunk_text(text, max_length=3500):
                try:
                    resp = await client.post(
                        "https://slack.com/api/chat.postMessage",
                        headers=headers,
                        json={"channel": chat_id, "text": chunk},
                    )
                    data = resp.json() if resp.status_code == 200 else {}
                    if not data.get("ok"):
                        self.last_error = str(data.get("error") or resp.status_code)
                        ok = False
                except Exception as exc:
                    self.last_error = str(exc)
                    ok = False
        return ok

    async def start(self):
        await self.run_forever()

    async def stop(self):
        self.running = False

    async def run_forever(self):
        if not self.is_configured():
            self.last_error = "SLACK_BOT_TOKEN missing or invalid (expected xoxb-...)."
            return

        self.running = True
        self.mode = "Web API Polling"
        self.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        headers = {"Authorization": f"Bearer {self.token}"}
        seen_ts: Dict[str, str] = {}
        bot_user_id = ""

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                auth_r = await client.get("https://slack.com/api/auth.test", headers=headers)
                if auth_r.status_code == 200 and auth_r.json().get("ok"):
                    bot_user_id = auth_r.json().get("user_id", "")
                    self.identity = f"@{auth_r.json().get('user', 'nexus')}"

                while self.running:
                    target_channels = self.channels
                    if not target_channels:
                        # Auto-discover channels bot is member of
                        try:
                            ch_r = await client.get(
                                "https://slack.com/api/conversations.list",
                                headers=headers,
                                params={"types": "public_channel,private_channel,im", "limit": 20},
                            )
                            if ch_r.status_code == 200 and ch_r.json().get("ok"):
                                target_channels = [
                                    c["id"] for c in ch_r.json().get("channels", [])
                                    if c.get("is_member") or c.get("is_im")
                                ]
                        except Exception:
                            target_channels = []

                    for ch_id in target_channels:
                        try:
                            params: Dict[str, Any] = {"channel": ch_id, "limit": 5}
                            if ch_id in seen_ts:
                                params["oldest"] = seen_ts[ch_id]
                            r = await client.get("https://slack.com/api/conversations.history", headers=headers, params=params)
                            data = r.json() if r.status_code == 200 else {}
                            msgs = list(reversed(data.get("messages", [])))
                            for m in msgs:
                                ts = str(m.get("ts", ""))
                                if not ts or ts == seen_ts.get(ch_id):
                                    continue
                                seen_ts[ch_id] = ts
                                uid = str(m.get("user", ""))
                                if not uid or uid == bot_user_id or m.get("bot_id"):
                                    continue
                                txt = (m.get("text") or "").strip()
                                if not txt:
                                    continue
                                gmsg = GatewayMessage(
                                    platform="slack",
                                    user_id=uid,
                                    chat_id=ch_id,
                                    text=txt,
                                    message_id=ts,
                                )
                                reply = await self.process_message(gmsg)
                                if reply:
                                    await self.send_text(ch_id, reply)
                        except Exception as exc:
                            self.last_error = str(exc)

                    await asyncio.sleep(3.5)
        except asyncio.CancelledError:
            raise
        finally:
            self.running = False
