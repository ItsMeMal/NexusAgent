import os
import json
import ssl
import hashlib
import hmac
import struct
import base64
import asyncio
import datetime
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse

import httpx

from .base import BaseGateway, GatewayMessage, chunk_text, parse_allow_list


class _AsyncWebSocket:
    """Lightweight RFC 6455 Async WebSocket client over Python stdlib asyncio + ssl."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.closed = False
        self._write_lock = asyncio.Lock()

    @classmethod
    async def connect(cls, url: str) -> "_AsyncWebSocket":
        parsed = urlparse(url)
        use_ssl = parsed.scheme == "wss"
        host = parsed.hostname or ""
        port = parsed.port or (443 if use_ssl else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        ssl_ctx = ssl.create_default_context() if use_ssl else None
        reader, writer = await asyncio.open_connection(host, port, ssl=ssl_ctx, limit=16 * 1024 * 1024)

        sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"User-Agent: NolthiraAgent/1.0\r\n\r\n"
        )
        writer.write(req.encode("ascii"))
        await writer.drain()

        # Validate the complete RFC 6455 upgrade handshake before trusting the socket.
        try:
            header_bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15.0)
            header_lines = header_bytes.decode("latin-1", errors="replace").split("\r\n")
            status_line = header_lines[0] if header_lines else ""
            headers = {}
            for line in header_lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().lower()] = value.strip()
            expected_accept = base64.b64encode(
                hashlib.sha1((sec_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            ).decode("ascii")
            if not status_line.startswith("HTTP/1.1 101 "):
                raise ConnectionError(f"WebSocket handshake failed: {status_line}")
            actual_accept = headers.get("sec-websocket-accept", "")
            if not actual_accept or not hmac.compare_digest(actual_accept, expected_accept):
                raise ConnectionError("WebSocket handshake failed: invalid Sec-WebSocket-Accept")
        except Exception:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            raise

        return cls(reader, writer)

    @staticmethod
    def build_frame(payload: bytes, opcode: int = 0x1) -> bytes:
        """Build a masked RFC 6455 client frame."""
        b1 = 0x80 | (opcode & 0x0F)
        length = len(payload)
        mask_key = os.urandom(4)

        if length < 126:
            header = struct.pack("!BB", b1, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", b1, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", b1, 0x80 | 127, length)

        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return header + mask_key + masked

    async def send_json(self, obj: Dict[str, Any]):
        await self.send_text(json.dumps(obj))

    async def send_text(self, text: str):
        if self.closed:
            return
        frame = self.build_frame(text.encode("utf-8"), opcode=0x1)
        async with self._write_lock:
            self.writer.write(frame)
            await self.writer.drain()

    async def send_pong(self, payload: bytes = b""):
        if self.closed:
            return
        frame = self.build_frame(payload, opcode=0xA)
        async with self._write_lock:
            self.writer.write(frame)
            await self.writer.drain()

    async def recv_message(self) -> Tuple[int, bytes]:
        """Read one complete WebSocket message (handling fragmentation & control frames)."""
        fragments: List[bytes] = []
        msg_opcode = 0x1

        while True:
            b1, b2 = await self.reader.readexactly(2)
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F

            if length == 126:
                (length,) = struct.unpack("!H", await self.reader.readexactly(2))
            elif length == 127:
                (length,) = struct.unpack("!Q", await self.reader.readexactly(8))

            mask_key = await self.reader.readexactly(4) if masked else b""
            payload = await self.reader.readexactly(length) if length > 0 else b""
            if masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:  # Close
                self.closed = True
                close_code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1000
                return (0x8, struct.pack("!H", close_code))
            if opcode == 0x9:  # Ping -> Pong
                await self.send_pong(payload)
                continue
            if opcode == 0xA:  # Pong
                continue

            if opcode != 0x0:
                msg_opcode = opcode
            fragments.append(payload)

            if fin:
                return (msg_opcode, b"".join(fragments))

    async def close(self):
        if not self.closed:
            self.closed = True
            try:
                async with self._write_lock:
                    self.writer.write(self.build_frame(b"", opcode=0x8))
                    await self.writer.drain()
            except Exception:
                pass
            try:
                self.writer.close()
            except Exception:
                pass


class DiscordGateway(BaseGateway):
    """Discord Bot Gateway v10 WebSocket + REST adapter (zero extra dependencies)."""

    platform_name = "discord"
    DISCORD_API = "https://discord.com/api/v10"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bot_user_id: str = ""
        self._ws: Optional[_AsyncWebSocket] = None
        self._seq: Optional[int] = None
        self._message_tasks = set()

    @property
    def token(self) -> str:
        return os.getenv("DISCORD_BOT_TOKEN", "").strip()

    def is_configured(self) -> bool:
        t = self.token
        return bool(t and len(t) > 20 and t != "your_discord_bot_token")

    def get_allowed_users(self) -> List[str]:
        return parse_allow_list(os.getenv("DISCORD_ALLOWED_USERS", ""))

    def get_allowed_channels(self) -> List[str]:
        return parse_allow_list(os.getenv("DISCORD_ALLOWED_CHANNELS", ""))

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "NolthiraAgent (https://github.com/ItsMeMal/NolthiraAgent, 1.0)",
        }

    async def _send_typing_loop(self, client: httpx.AsyncClient, channel_id: str, stop_evt: asyncio.Event):
        url = f"{self.DISCORD_API}/channels/{channel_id}/typing"
        while not stop_evt.is_set():
            try:
                await client.post(url, headers=self._headers(), timeout=5.0)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=7.0)
            except asyncio.TimeoutError:
                continue

    async def send_text(self, chat_id: str, text: str, reply_to_message_id: str = "") -> bool:
        if not self.is_configured() or not text:
            return False

        url = f"{self.DISCORD_API}/channels/{chat_id}/messages"
        chunks = chunk_text(text, max_length=1950)
        ok = True
        async with httpx.AsyncClient(timeout=15.0) as client:
            for idx, chunk in enumerate(chunks):
                payload: Dict[str, Any] = {"content": chunk}
                if idx == 0 and reply_to_message_id:
                    payload["message_reference"] = {"message_id": reply_to_message_id}
                try:
                    resp = await client.post(url, headers=self._headers(), json=payload)
                    if resp.status_code not in (200, 201):
                        self.last_error = f"Discord API HTTP {resp.status_code}: {resp.text[:200]}"
                        ok = False
                    else:
                        self.last_error = ""
                except Exception as e:
                    self.last_error = str(e)
                    ok = False
        return ok

    def _schedule_message_event(self, client: httpx.AsyncClient, data: Dict[str, Any]) -> None:
        task = asyncio.create_task(self._handle_message_event(client, data))
        self._message_tasks.add(task)

        def _finished(done_task):
            self._message_tasks.discard(done_task)
            try:
                error = done_task.exception()
            except asyncio.CancelledError:
                return
            if error:
                self.last_error = str(error)
                self.log("ERROR", f"Discord message task failed: {error}")

        task.add_done_callback(_finished)

    async def _handle_message_event(self, client: httpx.AsyncClient, data: Dict[str, Any]):
        author = data.get("author", {})
        if author.get("bot"):
            return

        user_id = str(author.get("id", ""))
        if not user_id or user_id == self._bot_user_id:
            return

        channel_id = str(data.get("channel_id", ""))
        guild_id = data.get("guild_id")
        is_group = bool(guild_id)
        content = (data.get("content") or "").strip()
        msg_id = str(data.get("id", ""))
        username = author.get("username", "") or ""
        display_name = author.get("global_name") or username

        allowed_channels = self.get_allowed_channels()
        respond_all = os.getenv("DISCORD_RESPOND_ALL", "false").lower() in ("true", "1", "yes")
        mentioned = False
        if self._bot_user_id:
            for pat in (f"<@{self._bot_user_id}>", f"<@!{self._bot_user_id}>"):
                if pat in content:
                    mentioned = True
                    content = content.replace(pat, "").strip()

        # In servers (guilds), reply if mentioned, channel whitelisted, or respond_all
        if is_group and not mentioned and not respond_all:
            if allowed_channels and channel_id not in allowed_channels:
                return
            if not allowed_channels and not content.startswith("/"):
                return

        if not content:
            return

        gmsg = GatewayMessage(
            platform="discord",
            user_id=user_id,
            chat_id=channel_id,
            text=content,
            username=username,
            display_name=display_name,
            is_group=is_group,
            message_id=msg_id,
            metadata={"raw": data},
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(self._send_typing_loop(client, channel_id, stop_typing))
        reply: Optional[str] = None
        try:
            reply = await self.process_message(gmsg)
        except Exception as e:
            self.last_error = str(e)
            self.log("ERROR", f"Message event failed: {e}")
            reply = f"❌ Agent Error: {e}"
        finally:
            stop_typing.set()
            typing_task.cancel()
            try:
                await typing_task
            except (asyncio.CancelledError, Exception):
                pass

        if reply:
            await self.send_text(channel_id, reply, reply_to_message_id=msg_id)

    async def _heartbeat_loop(self, ws: _AsyncWebSocket, interval_sec: float):
        try:
            while self.running and not ws.closed:
                await asyncio.sleep(interval_sec)
                await ws.send_json({"op": 1, "d": self._seq})
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.last_error = f"Discord heartbeat failed: {exc}"
            self.log("ERROR", self.last_error)

    async def start(self):
        if not self.is_configured():
            self.last_error = "Missing or invalid DISCORD_BOT_TOKEN"
            raise ValueError(self.last_error)

        self.running = True
        self.mode = "Gateway v10 WebSocket"
        self.last_error = ""
        self.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Try full intents first; fallback without privileged MESSAGE_CONTENT (32768) if portal rejected (4014)
        intents = 1 | (1 << 9) | (1 << 12) | (1 << 15)  # 37377

        async with httpx.AsyncClient(timeout=20.0) as client:
            # Verify REST token & get gateway URL
            gateway_url = "wss://gateway.discord.gg/?v=10&encoding=json"
            try:
                gw_resp = await client.get(f"{self.DISCORD_API}/gateway/bot", headers=self._headers())
                if gw_resp.status_code == 200:
                    gw_base = gw_resp.json().get("url", "wss://gateway.discord.gg")
                    gateway_url = f"{gw_base.rstrip('/')}/?v=10&encoding=json"
                else:
                    self.last_error = f"Discord gateway discovery failed (HTTP {gw_resp.status_code}): {gw_resp.text[:200]}"
                    self.running = False
                    self.log("ERROR", self.last_error)
                    return
            except Exception as e:
                self.last_error = str(e)

            while self.running:
                hb_task = None
                ws = None
                try:
                    ws = await _AsyncWebSocket.connect(gateway_url)
                    self._ws = ws

                    # Expect OP 10 HELLO
                    op, raw = await ws.recv_message()
                    if op == 0x8:
                        raise ConnectionError("Closed immediately on connect")
                    hello = json.loads(raw.decode("utf-8"))
                    hb_interval = hello.get("d", {}).get("heartbeat_interval", 41250) / 1000.0
                    hb_task = asyncio.create_task(self._heartbeat_loop(ws, hb_interval))

                    # Send OP 2 IDENTIFY
                    await ws.send_json({
                        "op": 2,
                        "d": {
                            "token": self.token,
                            "intents": intents,
                            "properties": {
                                "os": os.name,
                                "browser": "NolthiraAgent",
                                "device": "NolthiraAgent",
                            },
                        },
                    })

                    while self.running:
                        opcode, payload = await ws.recv_message()
                        if opcode == 0x8:
                            code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1000
                            if code == 4014:
                                # Privileged MESSAGE_CONTENT intent disabled in Discord Dev Portal -> fallback cleanly
                                intents = 1 | (1 << 9) | (1 << 12)  # 4609
                                self.log("WARN", "Disallowed MESSAGE_CONTENT intent (4014); falling back to DMs & @mentions")
                            raise ConnectionError(f"Discord Gateway closed with code {code}")

                        event = json.loads(payload.decode("utf-8"))
                        if event.get("s") is not None:
                            self._seq = event["s"]

                        ev_op = event.get("op")
                        ev_type = event.get("t")
                        ev_data = event.get("d") or {}

                        if ev_op == 0:
                            if ev_type == "READY":
                                user = ev_data.get("user", {})
                                self._bot_user_id = str(user.get("id", ""))
                                self.identity = f"@{user.get('username', 'nexus_discord')}"
                                self.last_error = ""
                                self.log("INFO", f"Connected to Discord as {self.identity}")
                            elif ev_type == "MESSAGE_CREATE":
                                self._schedule_message_event(client, ev_data)
                        elif ev_op == 7:  # RECONNECT
                            break
                        elif ev_op == 9:  # INVALID SESSION
                            await asyncio.sleep(2.0)
                            break

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.last_error = str(e)
                    await asyncio.sleep(4.0)
                finally:
                    if hb_task:
                        hb_task.cancel()
                    if ws:
                        await ws.close()

        self.running = False

    async def stop(self):
        self.running = False
        if self._ws:
            await self._ws.close()
        for task in list(self._message_tasks):
            task.cancel()
        if self._message_tasks:
            await asyncio.gather(*self._message_tasks, return_exceptions=True)
