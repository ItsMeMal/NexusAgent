import os
import json
import asyncio
import hashlib
import hmac
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
        self._message_tasks = set()
        self._seen_message_ids = {}

    @property
    def api_token(self) -> str:
        return os.getenv("WHATSAPP_API_TOKEN", "").strip()

    @property
    def phone_number_id(self) -> str:
        return os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()

    @property
    def verify_token(self) -> str:
        return os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip

    @property
    def app_secret(self) -> str:
        return os.getenv("WHATSAPP_APP_SECRET", "").strip()

    @property
    def require_signature(self) -> bool:
        return os.getenv("WHATSAPP_REQUIRE_SIGNATURE", "true").strip().lower() in ("true", "1", "yes")

    @staticmethod
    def verify_meta_signature(app_secret: str, body: bytes, signature: str) -> bool:
        """Verify Meta's X-Hub-Signature-256 HMAC before parsing a Cloud API webhook."""
        if not app_secret or not signature or not signature.startswith("sha256="):
            return False
        digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[len("sha256="):].strip(), digest)

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
        toggle = os.getenv("WHATSAPP_ENABLED", "").strip().lower()
        if toggle in ("false", "0", "no"):
            return False
        # An enable flag cannot replace the credentials/transport required to send replies.
        return self.is_cloud_api() or self.is_bridge()

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

        if not isinstance(payload, dict):
            return extracted

        # 1. Meta WhatsApp Cloud API webhook payload
        if isinstance(payload.get("entry"), list):
            for entry in payload.get("entry", []):
                if not isinstance(entry, dict):
                    continue
                for change in entry.get("changes", []):
                    if not isinstance(change, dict):
                        continue
                    val = change.get("value") or {}
                    if not isinstance(val, dict):
                        continue
                    contacts = {
                        str(c.get("wa_id", "")): str((c.get("profile") or {}).get("name", ""))
                        for c in val.get("contacts", []) if isinstance(c, dict)
                    }
                    for message in val.get("messages", []):
                        if not isinstance(message, dict):
                            continue
                        msg_type = message.get("type", "")
                        if msg_type == "text":
                            body = (message.get("text") or {}).get("body", "")
                        elif msg_type == "button":
                            body = (message.get("button") or {}).get("text", "")
                        elif msg_type == "interactive":
                            interactive = message.get("interactive") or {}
                            reply_obj = interactive.get("button_reply") or interactive.get("list_reply") or {}
                            body = reply_obj.get("title", "") if isinstance(reply_obj, dict) else ""
                        else:
                            body = ""
                        sender = str(message.get("from", ""))
                        if sender and body:
                            extracted.append(GatewayMessage(
                                platform="whatsapp",
                                user_id=self.normalize_phone(sender),
                                chat_id=sender,
                                text=str(body),
                                display_name=contacts.get(sender, ""),
                                message_id=str(message.get("id", "")),
                                metadata={"source": "meta_cloud", "raw": message},
                            ))
            return extracted

        # 2. Evolution API / Baileys nested webhook format
        data = payload.get("data")
        if isinstance(data, dict) and "key" in data:
            key = data.get("key") or {}
            if not isinstance(key, dict) or key.get("fromMe"):
                return extracted
            remote_jid = str(key.get("remoteJid", ""))
            is_group = remote_jid.endswith("@g.us")
            participant = str(key.get("participant") or data.get("participant") or "")
            sender = participant if is_group and participant else remote_jid
            msg_obj = data.get("message") or {}
            if not isinstance(msg_obj, dict):
                msg_obj = {}
            extended = msg_obj.get("extendedTextMessage") or {}
            image = msg_obj.get("imageMessage") or {}
            body = (
                msg_obj.get("conversation")
                or (extended.get("text") if isinstance(extended, dict) else "")
                or (image.get("caption") if isinstance(image, dict) else "")
                or ""
            )
            if remote_jid and body:
                extracted.append(GatewayMessage(
                    platform="whatsapp",
                    user_id=self.normalize_phone(sender),
                    chat_id=remote_jid,
                    text=str(body),
                    display_name=str(data.get("pushName", "")),
                    is_group=is_group,
                    message_id=str(key.get("id", "")),
                    metadata={"source": "baileys", "raw": payload},
                ))
            return extracted

        # 3. Generic bridge format. For group messages, authorize the participant, not the group JID.
        chat_id = str(payload.get("chatId") or payload.get("remoteJid") or payload.get("from") or payload.get("sender") or "")
        is_group = chat_id.endswith("@g.us")
        sender = str(
            payload.get("participant")
            or payload.get("senderId")
            or (payload.get("from") if is_group else "")
            or payload.get("sender")
            or payload.get("from")
            or payload.get("number")
            or chat_id
        )
        body = str(payload.get("text") or payload.get("message") or payload.get("body") or "")
        if chat_id and body:
            extracted.append(GatewayMessage(
                platform="whatsapp",
                user_id=self.normalize_phone(sender),
                chat_id=chat_id,
                text=body,
                display_name=str(payload.get("name") or payload.get("pushName") or ""),
                is_group=is_group,
                message_id=str(payload.get("messageId") or payload.get("id") or ""),
                metadata={"source": "bridge", "raw": payload},
            ))

        return extracted

    def _is_duplicate_message(self, message: GatewayMessage) -> bool:
        if not message.message_id:
            return False
        key = f"{message.platform}:{message.message_id}"
        if key in self._seen_message_ids:
            return True
        self._seen_message_ids[key] = None
        if len(self._seen_message_ids) > 5000:
            self._seen_message_ids.pop(next(iter(self._seen_message_ids)))
        return False

    async def _handle_parsed_message(self, gmsg: GatewayMessage) -> Optional[str]:
        try:
            reply = await self.process_message(gmsg)
            if reply and not await self.send_text(gmsg.chat_id, reply):
                self.log("ERROR", f"Reply delivery failed for message {gmsg.message_id or '(no id)'}: {self.last_error or 'unknown error'}")
            return reply
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            self.log("ERROR", f"Incoming message processing failed: {exc}")
            return None

    def _schedule_message(self, gmsg: GatewayMessage) -> None:
        if self._is_duplicate_message(gmsg):
            self.log("WARN", f"Duplicate WhatsApp message ignored: {gmsg.message_id}")
            return
        task = asyncio.create_task(self._handle_parsed_message(gmsg))
        self._message_tasks.add(task)

        def _finished(done_task):
            self._message_tasks.discard(done_task)
            try:
                error = done_task.exception()
            except asyncio.CancelledError:
                return
            if error:
                self.last_error = str(error)
                self.log("ERROR", f"Background message task failed: {error}")

        task.add_done_callback(_finished)

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
            if self.verify_token and hub_mode == "subscribe" and hmac.compare_digest(hub_verify_token or "", self.verify_token):
                return PlainTextResponse(content=hub_challenge or "", status_code=200)
            return Response(status_code=403)

        @app.post("/webhook")
        @app.post("/webhook/whatsapp")
        async def receive_webhook(request: Request):
            body = await request.body()
            if self.is_cloud_api() and self.require_signature:
                if not self.app_secret:
                    self.last_error = "WHATSAPP_APP_SECRET is required when WHATSAPP_REQUIRE_SIGNATURE=true."
                    return JSONResponse({"ok": False, "error": self.last_error}, status_code=503)
                signature = request.headers.get("X-Hub-Signature-256", "")
                if not self.verify_meta_signature(self.app_secret, body, signature):
                    self.last_error = "Invalid Meta webhook signature."
                    self.log("WARN", self.last_error)
                    return JSONResponse({"ok": False, "error": "Invalid webhook signature"}, status_code=403)

            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
            if not isinstance(payload, dict):
                return JSONResponse({"ok": False, "error": "Webhook body must be a JSON object"}, status_code=400)

            msgs = self.extract_incoming_messages(payload)
            # Sync replies are reserved for trusted local bridge test clients.
            sync_mode = payload.get("sync") is True and not self.is_cloud_api()
            if sync_mode and msgs:
                reply = await self.process_message(msgs[0])
                return JSONResponse({"ok": True, "reply": reply})

            for message in msgs:
                self._schedule_message(message)

            return JSONResponse({"ok": True, "queued": len(msgs)})

        class _NoSignalServer(uvicorn.Server):
            def install_signal_handlers(self):
                pass

        self.running = True
        self.mode = "Cloud API + Webhook" if self.is_cloud_api() else "Bridge Webhook"
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
        for task in list(self._message_tasks):
            task.cancel()
        if self._message_tasks:
            await asyncio.gather(*self._message_tasks, return_exceptions=True)
