import os
import json
import asyncio
import datetime
from typing import List, Optional, Dict, Any

import httpx

from .base import BaseGateway, GatewayMessage, chunk_text, parse_allow_list


class WhatsAppGateway(BaseGateway):
    """WhatsApp Gateway supporting Meta Cloud API and Baileys/Evolution Local Bridges."""

    platform_name = "whatsapp"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._server = None

    @property
    def api_token(self) -> str:
        return os.getenv("WHATSAPP_API_TOKEN", "").strip()

    @property
    def phone_number_id(self) -> str:
        return os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()

    @property
    def verify_token(self) -> str:
        return os.getenv("WHATSAPP_VERIFY_TOKEN", "nexus_verify_token").strip()

    @property
    def bridge_url(self) -> str:
        return os.getenv("WHATSAPP_BRIDGE_URL", "").strip()

    @property
    def bridge_token(self) -> str:
        return os.getenv("WHATSAPP_BRIDGE_TOKEN", "").strip()

    @property
    def host(self) -> str:
        return os.getenv("WHATSAPP_HOST", "0.0.0.0").strip()

    @property
    def port(self) -> int:
        try:
            return int(os.getenv("WHATSAPP_PORT", "8090"))
        except Exception:
            return 8090

    def is_cloud_api(self) -> bool:
        return bool(self.api_token and self.phone_number_id)

    def is_bridge(self) -> bool:
        return bool(self.bridge_url)

    def is_configured(self) -> bool:
        enabled = os.getenv("WHATSAPP_ENABLED", "false").lower() in ("true", "1", "yes")
        return self.is_cloud_api() or self.is_bridge() or enabled

    def get_allowed_users(self) -> List[str]:
        return parse_allow_list(os.getenv("WHATSAPP_ALLOWED_NUMBERS", ""))

    @staticmethod
    def normalize_phone(raw: str) -> str:
        """Strip WhatsApp JID suffix (@s.whatsapp.net, @c.us) and '+' signs."""
        s = str(raw or "").strip()
        if "@" in s:
            s = s.split("@", 1)[0]
        return s.lstrip("+")

    def is_authorized(self, user_id: str, username: str = "") -> bool:
        if self.is_allow_all():
            return True
        norm_uid = self.normalize_phone(user_id).lower()
        allowed = [self.normalize_phone(x).lower() for x in self.get_allowed_users()]
        if not allowed:
            return False
        return norm_uid in allowed or user_id.lower() in allowed

    async def send_text(self, chat_id: str, text: str) -> bool:
        if not text:
            return False
        chunks = chunk_text(text, max_length=4000)
        ok = True

        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                try:
                    if self.is_cloud_api():
                        url = f"https://graph.facebook.com/v21.0/{self.phone_number_id}/messages"
                        headers = {
                            "Authorization": f"Bearer {self.api_token}",
                            "Content-Type": "application/json",
                        }
                        payload = {
                            "messaging_product": "whatsapp",
                            "recipient_type": "individual",
                            "to": self.normalize_phone(chat_id),
                            "type": "text",
                            "text": {"preview_url": False, "body": chunk},
                        }
                        resp = await client.post(url, headers=headers, json=payload)
                        if resp.status_code not in (200, 201):
                            self.last_error = f"Meta Cloud API {resp.status_code}: {resp.text[:200]}"
                            ok = False
                    elif self.is_bridge():
                        headers = {"Content-Type": "application/json"}
                        if self.bridge_token:
                            headers["Authorization"] = f"Bearer {self.bridge_token}"
                            headers["apikey"] = self.bridge_token
                        # Compatible with standard Baileys / Evolution / custom bridge POST formats
                        payload = {
                            "to": chat_id,
                            "number": self.normalize_phone(chat_id),
                            "chatId": chat_id,
                            "text": chunk,
                            "message": chunk,
                            "textMessage": {"text": chunk},
                        }
                        resp = await client.post(self.bridge_url, headers=headers, json=payload)
                        if resp.status_code not in (200, 201, 202):
                            self.last_error = f"Bridge API {resp.status_code}: {resp.text[:200]}"
                            ok = False
                    else:
                        self.log("WARN", f"No outbound WhatsApp Cloud API or Bridge URL configured; reply to {chat_id}: {chunk[:80]}")
                        ok = False
                except Exception as e:
                    self.last_error = str(e)
                    ok = False
        return ok

    def extract_incoming_messages(self, payload: Dict[str, Any]) -> List[GatewayMessage]:
        """Parse incoming messages from Meta Cloud API, Evolution API, Baileys, or generic bridge JSON."""
        extracted: List[GatewayMessage] = []

        # 1. Meta WhatsApp Cloud API webhook payload
        if "entry" in payload and isinstance(payload["entry"], list):
            for entry in payload["entry"]:
                for change in entry.get("changes", []):
                    val = change.get("value", {})
                    contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in val.get("contacts", [])}
                    for m in val.get("messages", []):
                        m_type = m.get("type", "")
                        if m_type == "text":
                            body = m.get("text", {}).get("body", "")
                        elif m_type == "button":
                            body = m.get("button", {}).get("text", "")
                        elif m_type == "interactive":
                            inter = m.get("interactive", {})
                            body = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
                        else:
                            body = ""
                        sender = str(m.get("from", ""))
                        if sender and body:
                            extracted.append(GatewayMessage(
                                platform="whatsapp",
                                user_id=self.normalize_phone(sender),
                                chat_id=sender,
                                text=body,
                                display_name=contacts.get(sender, ""),
                                message_id=str(m.get("id", "")),
                                metadata={"source": "meta_cloud", "raw": m},
                            ))
            return extracted

        # 2. Evolution API / Baileys nested webhook format
        data = payload.get("data")
        if isinstance(data, dict) and "key" in data:
            key = data.get("key", {})
            if key.get("fromMe"):
                return extracted
            remote_jid = str(key.get("remoteJid", ""))
            msg_obj = data.get("message", {})
            body = (
                msg_obj.get("conversation")
                or msg_obj.get("extendedTextMessage", {}).get("text")
                or msg_obj.get("imageMessage", {}).get("caption")
                or ""
            )
            if remote_jid and body:
                extracted.append(GatewayMessage(
                    platform="whatsapp",
                    user_id=self.normalize_phone(remote_jid),
                    chat_id=remote_jid,
                    text=body,
                    display_name=data.get("pushName", ""),
                    is_group=remote_jid.endswith("@g.us"),
                    message_id=str(key.get("id", "")),
                    metadata={"source": "baileys", "raw": payload},
                ))
            return extracted

        # 3. Generic local bridge format: {"from": "...", "text": "..."} or {"sender": "...", "message": "..."}
        sender = str(payload.get("from") or payload.get("sender") or payload.get("chatId") or payload.get("number") or "")
        body = str(payload.get("text") or payload.get("message") or payload.get("body") or "")
        if sender and body:
            extracted.append(GatewayMessage(
                platform="whatsapp",
                user_id=self.normalize_phone(sender),
                chat_id=sender,
                text=body,
                display_name=str(payload.get("name") or payload.get("pushName") or ""),
                is_group="@g.us" in sender,
                metadata={"source": "bridge", "raw": payload},
            ))

        return extracted

    async def _handle_parsed_message(self, gmsg: GatewayMessage) -> Optional[str]:
        reply = await self.process_message(gmsg)
        if reply:
            await self.send_text(gmsg.chat_id, reply)
        return reply

    async def start(self):
        if not self.is_configured():
            self.last_error = "WhatsApp not configured (set WHATSAPP_API_TOKEN + WHATSAPP_PHONE_NUMBER_ID or WHATSAPP_BRIDGE_URL)"
            raise ValueError(self.last_error)

        from fastapi import FastAPI, Request, Response, Query
        from fastapi.responses import PlainTextResponse, JSONResponse
        import uvicorn

        app = FastAPI(title="Nexus WhatsApp Gateway")

        @app.get("/health")
        async def health():
            return {"status": "online", "platform": "whatsapp", "mode": self.mode, "handled": self.messages_handled}

        @app.get("/webhook")
        @app.get("/webhook/whatsapp")
        async def verify_webhook(
            hub_mode: Optional[str] = Query(None, alias="hub.mode"),
            hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
            hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
        ):
            if hub_mode == "subscribe" and hub_verify_token == self.verify_token:
                return PlainTextResponse(content=hub_challenge or "", status_code=200)
            return Response(status_code=403)

        @app.post("/webhook")
        @app.post("/webhook/whatsapp")
        async def receive_webhook(request: Request):
            try:
                payload = await request.json()
            except Exception:
                return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

            msgs = self.extract_incoming_messages(payload)
            # If caller asks synchronous reply (e.g. local bridge testing), wait & return reply
            sync_mode = payload.get("sync") is True
            if sync_mode and msgs:
                reply = await self.process_message(msgs[0])
                return JSONResponse({"ok": True, "reply": reply})

            for m in msgs:
                asyncio.create_task(self._handle_parsed_message(m))

            return JSONResponse({"ok": True, "queued": len(msgs)})

        class _NoSignalServer(uvicorn.Server):
            def install_signal_handlers(self):
                pass

        self.running = True
        self.mode = "Cloud API + Webhook" if self.is_cloud_api() else ("Bridge Webhook" if self.is_bridge() else "Webhook Server")
        self.identity = f"http://{self.host}:{self.port}/webhook"
        self.last_error = ""
        self.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        uv_config = uvicorn.Config(app, host=self.host, port=self.port, log_level="error")
        self._server = _NoSignalServer(uv_config)
        self.log("INFO", f"WhatsApp webhook listening on {self.identity}")

        try:
            await self._server.serve()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.last_error = str(e)
        finally:
            self.running = False

    async def stop(self):
        self.running = False
        if self._server:
            self._server.should_exit = True
