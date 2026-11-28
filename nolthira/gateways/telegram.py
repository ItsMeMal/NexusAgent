import os
import asyncio
import datetime
import re
from typing import List, Optional, Dict, Any

import httpx

from .base import BaseGateway, GatewayMessage, chunk_text, parse_allow_list


class TelegramGateway(BaseGateway):
    """Telegram Bot API long-polling gateway adapter (zero external SDK required)."""

    platform_name = "telegram"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._update_tasks = set()

    @property
    def token(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    def is_configured(self) -> bool:
        t = self.token
        return bool(t and ":" in t and t != "your_telegram_bot_token")

    def get_allowed_users(self) -> List[str]:
        return parse_allow_list(os.getenv("TELEGRAM_ALLOWED_USERS", ""))

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    @staticmethod
    def _api_error(response) -> Optional[str]:
        if response.status_code != 200:
            return f"Telegram Bot API HTTP {response.status_code}: {response.text[:200]}"
        try:
            data = response.json()
        except ValueError:
            return "Telegram Bot API returned invalid JSON"
        if not isinstance(data, dict) or data.get("ok") is not True:
            description = data.get("description") if isinstance(data, dict) else ""
            return f"Telegram Bot API error: {description or 'ok=false'}"
        return None

    def _schedule_update(self, client: httpx.AsyncClient, update: Dict[str, Any]) -> None:
        task = asyncio.create_task(self._handle_update(client, update))
        self._update_tasks.add(task)

        def _finished(done_task):
            self._update_tasks.discard(done_task)
            try:
                error = done_task.exception()
            except asyncio.CancelledError:
                return
            if error:
                self.last_error = str(error)
                self.log("ERROR", f"Telegram update task failed: {error}")

        task.add_done_callback(_finished)

    async def _send_typing_loop(self, client: httpx.AsyncClient, chat_id: str, stop_evt: asyncio.Event):
        while not stop_evt.is_set():
            try:
                await client.post(
                    self._api_url("sendChatAction"),
                    json={"chat_id": chat_id, "action": "typing"},
                    timeout=5.0,
                )
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                continue

    async def send_text(self, chat_id: str, text: str) -> bool:
        if not self.is_configured() or not text:
            return False

        chunks = chunk_text(text, max_length=4000)
        ok = True
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                try:
                    resp = await client.post(
                        self._api_url("sendMessage"),
                        json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                    )
                    first_error = self._api_error(resp)
                    if first_error:
                        # Retry without Markdown because malformed Markdown entities are common.
                        resp2 = await client.post(
                            self._api_url("sendMessage"),
                            json={"chat_id": chat_id, "text": chunk},
                        )
                        second_error = self._api_error(resp2)
                        if second_error:
                            self.last_error = second_error
                            ok = False
                        else:
                            self.last_error = ""
                    else:
                        self.last_error = ""
                except Exception as e:
                    self.last_error = str(e)
                    ok = False
        return ok

    async def _handle_update(self, client: httpx.AsyncClient, update: Dict[str, Any]):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat", {})
        sender = msg.get("from", {})
        chat_id = str(chat.get("id", ""))
        user_id = str(sender.get("id", chat_id))
        username = sender.get("username", "") or ""
        display_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
        is_group = chat.get("type") in ("group", "supergroup")
        text = msg.get("text") or msg.get("caption") or ""

        # Voice-note / audio message auto-transcription
        if not text and (msg.get("voice") or msg.get("audio")) and client is not None:
            voice_obj = msg.get("voice") or msg.get("audio") or {}
            file_id = voice_obj.get("file_id")
            if file_id:
                try:
                    f_resp = await client.get(self._api_url("getFile"), params={"file_id": file_id}, timeout=10.0)
                    file_path = f_resp.json().get("result", {}).get("file_path") if f_resp.status_code == 200 else None
                    if file_path:
                        dl_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
                        audio_r = await client.get(dl_url, timeout=30.0)
                        if audio_r.status_code == 200:
                            transcript = await self.transcribe_audio(audio_r.content, filename=file_path.split("/")[-1])
                            if transcript:
                                text = f"[Voice transcript]: {transcript}"
                except Exception:
                    pass

        if not text or not chat_id:
            return

        # In groups, respond when mentioned or replied to, unless group messages are explicitly routed
        if is_group and self.identity:
            bot_handle = f"@{self.identity.lstrip('@').lower()}"
            reply_message = msg.get("reply_to_message") or {}
            reply_author = reply_message.get("from") or {}
            reply_to = str(reply_author.get("username", "")).lower()
            is_cmd = text.startswith("/")
            if not is_cmd and bot_handle not in text.lower() and reply_to != self.identity.lstrip("@").lower():
                return
            if bot_handle in text.lower():
                text = re.sub(re.escape(bot_handle), "", text, flags=re.IGNORECASE).strip()

        gmsg = GatewayMessage(
            platform="telegram",
            user_id=user_id,
            chat_id=chat_id,
            text=text,
            username=username,
            display_name=display_name,
            is_group=is_group,
            message_id=str(msg.get("message_id", "")),
            metadata={"raw": msg},
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(self._send_typing_loop(client, chat_id, stop_typing))
        reply: Optional[str] = None
        try:
            reply = await self.process_message(gmsg)
        except Exception as e:
            self.last_error = str(e)
            self.log("ERROR", f"Update handling failed: {e}")
            reply = f"❌ Agent Error: {e}"
        finally:
            stop_typing.set()
            typing_task.cancel()
            try:
                await typing_task
            except (asyncio.CancelledError, Exception):
                pass

        if reply:
            await self.send_text(chat_id, reply)

    async def start(self):
        if not self.is_configured():
            self.last_error = "Missing or invalid TELEGRAM_BOT_TOKEN"
            raise ValueError(self.last_error)

        self.running = True
        self.mode = "Long Polling"
        self.last_error = ""
        self.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        offset = 0

        async with httpx.AsyncClient(timeout=35.0) as client:
            # Verify identity via getMe
            try:
                me_resp = await client.get(self._api_url("getMe"), timeout=10.0)
                me_error = self._api_error(me_resp)
                if not me_error:
                    me_data = me_resp.json().get("result", {})
                    self.identity = f"@{me_data.get('username', 'nexus_bot')}"
                    self.log("INFO", f"Connected to Telegram as {self.identity}")
                else:
                    self.last_error = f"getMe failed: {me_error}"
                    self.running = False
                    self.log("ERROR", self.last_error)
                    return
            except Exception as e:
                self.last_error = str(e)
                self.running = False
                return

            while self.running:
                try:
                    resp = await client.get(
                        self._api_url("getUpdates"),
                        params={"offset": offset, "timeout": 25, "allowed_updates": '["message","edited_message"]'},
                        timeout=32.0,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if not isinstance(data, dict) or data.get("ok") is not True:
                            self.last_error = str((data or {}).get("description", "getUpdates returned ok=false"))
                            self.log("ERROR", self.last_error)
                            await asyncio.sleep(3.0)
                            continue
                        for upd in data.get("result", []):
                            offset = max(offset, upd.get("update_id", 0) + 1)
                            self._schedule_update(client, upd)
                    elif resp.status_code == 409:
                        self.last_error = "Conflict (409): Another bot instance or webhook is active"
                        await asyncio.sleep(5.0)
                    else:
                        self.last_error = f"HTTP {resp.status_code}"
                        await asyncio.sleep(3.0)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.last_error = str(e)
                    await asyncio.sleep(3.0)

        self.running = False

    async def stop(self):
        self.running = False
        for task in list(self._update_tasks):
            task.cancel()
        if self._update_tasks:
            await asyncio.gather(*self._update_tasks, return_exceptions=True)
