"""
nexus/gateways/email_gw.py
IMAP + SMTP Email Gateway adapter built with Python stdlib (imaplib, smtplib, email).
"""

import asyncio
import datetime
import email
import imaplib
import os
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from typing import List, Optional

from .base import BaseGateway, GatewayMessage, parse_allow_list


class EmailGateway(BaseGateway):
    platform_name = "email"

    @property
    def email_user(self) -> str:
        return os.getenv("EMAIL_USER", "").strip()

    @property
    def email_pass(self) -> str:
        return os.getenv("EMAIL_PASS", "").strip()

    @property
    def imap_host(self) -> str:
        return os.getenv("EMAIL_IMAP_HOST", "").strip()

    @property
    def smtp_host(self) -> str:
        return os.getenv("EMAIL_SMTP_HOST", "").strip()

    def is_configured(self) -> bool:
        return bool(self.email_user and self.email_pass and self.imap_host and self.smtp_host)

    def get_allowed_users(self) -> List[str]:
        return parse_allow_list(os.getenv("EMAIL_ALLOWED_SENDERS", ""))

    def _smtp_send_sync(self, to_addr: str, subject: str, body: str) -> None:
        port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        msg = EmailMessage()
        msg["From"] = self.email_user
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)
        if port == 465:
            with smtplib.SMTP_SSL(self.smtp_host, port, timeout=20) as s:
                s.login(self.email_user, self.email_pass)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.smtp_host, port, timeout=20) as s:
                s.starttls()
                s.login(self.email_user, self.email_pass)
                s.send_message(msg)

    async def send_text(self, chat_id: str, text: str) -> bool:
        if not self.is_configured() or not text or not chat_id:
            return False
        try:
            await asyncio.to_thread(self._smtp_send_sync, chat_id, "Re: Nexus Agent", text)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def _imap_fetch_unseen_sync(self) -> List[tuple[str, str, str]]:
        """Return list of (sender_addr, subject, body_text) for unseen messages."""
        port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
        out: List[tuple[str, str, str]] = []
        with imaplib.IMAP4_SSL(self.imap_host, port) as M:
            M.login(self.email_user, self.email_pass)
            M.select("INBOX")
            typ, data = M.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                return out
            for num in data[0].split()[:10]:
                res_t, msg_data = M.fetch(num, "(RFC822)")
                if res_t != "OK" or not msg_data:
                    continue
                raw_bytes = msg_data[0][1]
                if not isinstance(raw_bytes, bytes):
                    continue
                parsed = email.message_from_bytes(raw_bytes)
                _, sender_addr = parseaddr(parsed.get("From", ""))
                subj = parsed.get("Subject", "(no subject)")
                body = ""
                if parsed.is_multipart():
                    for part in parsed.walk():
                        if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode(errors="replace")
                                break
                else:
                    payload = parsed.get_payload(decode=True)
                    if payload:
                        body = payload.decode(errors="replace")
                if sender_addr and (body or subj):
                    out.append((sender_addr, subj, body.strip() or subj))
                M.store(num, "+FLAGS", "\\Seen")
        return out

    async def start(self):
        await self.run_forever()

    async def stop(self):
        self.running = False

    async def run_forever(self):
        if not self.is_configured():
            self.last_error = "EMAIL_USER/PASS/IMAP_HOST/SMTP_HOST missing in .env."
            return
        self.running = True
        self.mode = "IMAP/SMTP"
        self.identity = self.email_user
        self.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            while self.running:
                try:
                    items = await asyncio.to_thread(self._imap_fetch_unseen_sync)
                    for sender_addr, subj, body in items:
                        gmsg = GatewayMessage(
                            platform="email",
                            user_id=sender_addr,
                            chat_id=sender_addr,
                            text=f"[Subject: {subj}]\n{body}",
                            username=sender_addr,
                        )
                        reply = await self.process_message(gmsg)
                        if reply:
                            await asyncio.to_thread(self._smtp_send_sync, sender_addr, f"Re: {subj}", reply)
                except Exception as exc:
                    self.last_error = str(exc)
                await asyncio.sleep(12.0)
        except asyncio.CancelledError:
            raise
        finally:
            self.running = False
