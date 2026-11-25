import os
import uuid
import asyncio
import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

from ..config import config
from ..core.agent import NexusAgent
from ..core.llm import LLMClient
from ..memory import SQLiteMemory
from ..skills import SkillManager
from ..tools.base import ToolRegistry
from ..providers.manager import ProviderManager


def parse_allow_list(raw: str) -> List[str]:
    """Parse comma-separated allowlist IDs or usernames cleanly."""
    if not raw:
        return []
    return [item.strip().lstrip("@") for item in raw.split(",") if item.strip()]


def chunk_text(text: str, max_length: int = 4000) -> List[str]:
    """Split long agent responses along newline/whitespace boundaries for messaging platforms."""
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at <= 0:
            split_at = max_length

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return [c for c in chunks if c]


@dataclass
class GatewayMessage:
    """Normalized incoming message from any messaging gateway platform."""
    platform: str
    user_id: str
    chat_id: str
    text: str
    username: str = ""
    display_name: str = ""
    is_group: bool = False
    message_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewayStatus:
    """Runtime telemetry and configuration state for a messaging gateway."""
    platform: str
    configured: bool
    running: bool
    identity: str = ""
    messages_handled: int = 0
    allowed_users_count: int = 0
    allow_all: bool = False
    started_at: str = ""
    last_error: str = ""
    mode: str = ""


class BaseGateway(ABC):
    """Abstract base class for Nexus messaging gateways (Hermes-style unified bridge)."""

    platform_name: str = "base"

    def __init__(
        self,
        llm_client: LLMClient,
        memory: SQLiteMemory,
        skill_manager: SkillManager,
        registry: ToolRegistry,
        soul_path: Path = config.SOUL_PATH,
        max_steps: int = config.MAX_STEPS,
        on_log: Optional[Callable[[str, str], None]] = None,
    ):
        self.llm = llm_client
        self.memory = memory
        self.skill_manager = skill_manager
        self.registry = registry
        self.soul_path = soul_path
        self.max_steps = max_steps
        self.on_log = on_log

        self.running: bool = False
        self.identity: str = ""
        self.messages_handled: int = 0
        self.started_at: str = ""
        self.last_error: str = ""
        self.mode: str = ""

        self._session_map: Dict[str, str] = {}
        self._chat_locks: Dict[str, asyncio.Lock] = {}

    def log(self, level: str, message: str):
        if self.on_log:
            try:
                self.on_log(self.platform_name, f"[{level}] {message}")
            except Exception:
                pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required credentials/config are present."""

    @abstractmethod
    def get_allowed_users(self) -> List[str]:
        """Return configured allow-list of user IDs/usernames."""

    def is_allow_all(self) -> bool:
        return os.getenv("GATEWAY_ALLOW_ALL_USERS", "false").lower() in ("true", "1", "yes")

    def is_authorized(self, user_id: str, username: str = "") -> bool:
        """Enforce Hermes-style allow-list security by default."""
        if self.is_allow_all():
            return True
        allowed = [a.lower() for a in self.get_allowed_users()]
        if not allowed:
            return False
        uid = str(user_id).strip().lower()
        uname = str(username).strip().lstrip("@").lower()
        return uid in allowed or (uname and uname in allowed)

    def get_session_id(self, chat_id: str) -> str:
        """Return persistent session ID scoped to platform + chat_id."""
        key = f"{self.platform_name}_{chat_id}"
        if key not in self._session_map:
            self._session_map[key] = key
        return self._session_map[key]

    def reset_session(self, chat_id: str) -> str:
        """Start a fresh isolated session context for the chat."""
        key = f"{self.platform_name}_{chat_id}"
        new_sid = f"{key}_{uuid.uuid4().hex[:6]}"
        self._session_map[key] = new_sid
        return new_sid

    def _get_lock(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

    async def process_message(self, msg: GatewayMessage) -> Optional[str]:
        """Authorize, normalize, execute NexusAgent reasoning, and return formatted reply."""
        if not self.is_authorized(msg.user_id, msg.username):
            self.log("WARN", f"Unauthorized access blocked from user={msg.user_id} (@{msg.username})")
            return (
                f"🔒 *Access Denied (Nexus Security Guard)*\n"
                f"Your {self.platform_name.capitalize()} ID `{msg.user_id}` is not on the allow-list.\n"
                f"Add `{msg.user_id}` to your gateway allow-list in `.env` or set `GATEWAY_ALLOW_ALL_USERS=true`."
            )

        text = (msg.text or "").strip()
        if not text:
            return None

        cmd = text.lower().split()[0]

        if cmd in ("/start", "/help"):
            return (
                f"⚡ *Nexus Agent* · `{self.platform_name.capitalize()}` Gateway\n\n"
                f"Model: `{self.llm.model}`\n"
                f"User ID: `{msg.user_id}`\n"
                f"Session: `{self.get_session_id(msg.chat_id)}`\n\n"
                f"*📋 Commands:*\n"
                f"• `/new` · `/reset` · `/clear` — Fresh conversation context\n"
                f"• `/status` — Runtime telemetry\n"
                f"• `/model [id]` — Show or switch active model\n"
                f"• `/memory [n]` — Recent memories (default 10)\n"
                f"• `/skills` — Loaded skills list\n"
                f"• `/tools` — Available tools list\n"
                f"• `/config` — Active configuration\n"
                f"• `/sessions` — Active sessions\n"
                f"• `/help` — This menu\n\n"
                f"Send any message to chat with Nexus!"
            )

        if cmd in ("/new", "/reset", "/clear"):
            new_sid = self.reset_session(msg.chat_id)
            return f"✨ Fresh session started: `{new_sid}`"

        if cmd == "/status":
            skills_count = len(self.skill_manager.load_all_skills())
            tools_count = len(self.registry.get_all())
            return (
                f"📊 *Nexus Gateway Status*\n"
                f"• Platform: `{self.platform_name.capitalize()}`\n"
                f"• Model: `{self.llm.model}`\n"
                f"• Session: `{self.get_session_id(msg.chat_id)}`\n"
                f"• Tools: `{tools_count}` | Skills: `{skills_count}`\n"
                f"• Messages Handled: `{self.messages_handled}`\n"
                f"• Running Since: `{self.started_at or 'unknown'}`"
            )

        if cmd == "/model":
            parts = text.split(maxsplit=1)
            if len(parts) >= 2:
                # Switch model
                new_model = parts[1].strip()
                self.llm.model = new_model
                config.MODEL = new_model
                return f"✔ Switched to `{new_model}`"
            # List available models
            try:
                provider = ProviderManager.detect_active_provider(config.API_BASE)
                models = await ProviderManager.get_models_for_provider(
                    provider, api_key=config.API_KEY, api_base=config.API_BASE
                )
                current = self.llm.model
                lines = [f"🤖 *Available Models* (active: `{current}`)\n"]
                for m in models[:25]:
                    marker = "▶" if m.id == current else "•"
                    ctx = f" [{m.context}]" if m.context and m.context != "Auto" else ""
                    tag = f" `{m.tag}`" if m.tag else ""
                    lines.append(f"{marker} `{m.id}`{tag}{ctx}")
                lines.append(f"\nUsage: `/model <id>` to switch")
                return "\n".join(lines)
            except Exception as e:
                return f"🤖 Active model: `{self.llm.model}`\n❌ Could not fetch model list: {e}"

        if cmd == "/memory":
            parts = text.split(maxsplit=1)
            limit = 10
            try:
                limit = int(parts[1].strip())
            except Exception:
                pass
            try:
                session_id = self.get_session_id(msg.chat_id)
                memories = self.memory.get_history(session_id, limit=limit)
                if not memories:
                    return "🧠 No memories in this session yet."
                lines = [f"🧠 *Last {min(limit, len(memories))} messages:*"]
                for i, m in enumerate(memories[-limit:], 1):
                    role = m.get("role", "?")
                    content_text = (m.get("content") or "")[:80].replace("\n", " ")
                    suffix = "…" if len(m.get("content", "")) > 80 else ""
                    lines.append(f"{i}. [{role}] {content_text}{suffix}")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Memory error: {e}"

        if cmd == "/skills":
            try:
                skills = self.skill_manager.load_all_skills()
                if not skills:
                    return "📚 No skills loaded."
                lines = [f"📚 *Loaded Skills ({len(skills)}):*"]
                for s in skills:
                    name = getattr(s, "name", None) or getattr(s, "id", None) or str(s)
                    desc = (getattr(s, "description", "") or "")[:60]
                    lines.append(f"• `{name}` — {desc}" if desc else f"• `{name}`")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Skills error: {e}"

        if cmd == "/tools":
            try:
                tools = self.registry.get_all()
                if not tools:
                    return "🔧 No tools registered."
                lines = [f"🔧 *Available Tools ({len(tools)}):*"]
                for t in tools:
                    name = getattr(t, "name", None) or str(t)
                    desc = (getattr(t, "description", "") or "")[:60]
                    lines.append(f"• `{name}` — {desc}" if desc else f"• `{name}`")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Tools error: {e}"

        if cmd == "/config":
            try:
                session_id = self.get_session_id(msg.chat_id)
                tools_count = len(self.registry.get_all())
                skills_count = len(self.skill_manager.load_all_skills())
                api_base = getattr(self.llm, "api_base", None) or config.API_BASE
                return (
                    f"⚙️ *Active Config*\n"
                    f"• Model: `{self.llm.model}`\n"
                    f"• API Base: `{api_base}`\n"
                    f"• Platform: `{self.platform_name.capitalize()}`\n"
                    f"• Session: `{session_id}`\n"
                    f"• Tools: `{tools_count}` | Skills: `{skills_count}`\n"
                    f"• Max Steps: `{self.max_steps}`\n"
                    f"• Allow All Users: `{self.is_allow_all()}`\n"
                    f"• Allowed Users: `{len(self.get_allowed_users())}`"
                )
            except Exception as e:
                return f"❌ Config error: {e}"

        if cmd == "/sessions":
            try:
                sessions = list(self._session_map.items())
                if not sessions:
                    return "📂 No active sessions yet."
                lines = [f"📂 *Active Sessions ({len(sessions)}):*"]
                for key, sid in sessions[-10:]:
                    lines.append(f"• `{sid}`")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Sessions error: {e}"

        lock = self._get_lock(msg.chat_id)
        async with lock:
            session_id = self.get_session_id(msg.chat_id)
            agent = NexusAgent(
                llm_client=self.llm,
                memory=self.memory,
                skill_manager=self.skill_manager,
                registry=self.registry,
                soul_path=self.soul_path,
                max_steps=self.max_steps,
                session_id=session_id,
            )
            self.log("INFO", f"Handling message from {msg.username or msg.user_id} in chat {msg.chat_id}")
            try:
                reply = await agent.run(text)
                self.messages_handled += 1
                return reply or "(No text output generated)"
            except Exception as e:
                self.last_error = str(e)
                self.log("ERROR", f"Agent run failed: {e}")
                return f"❌ Agent Error: {e}"

    def get_status(self) -> GatewayStatus:
        return GatewayStatus(
            platform=self.platform_name,
            configured=self.is_configured(),
            running=self.running,
            identity=self.identity,
            messages_handled=self.messages_handled,
            allowed_users_count=len(self.get_allowed_users()),
            allow_all=self.is_allow_all(),
            started_at=self.started_at,
            last_error=self.last_error,
            mode=self.mode,
        )

    @abstractmethod
    async def start(self):
        """Start listening for incoming messages."""

    @abstractmethod
    async def stop(self):
        """Gracefully stop the gateway."""

    @abstractmethod
    async def send_text(self, chat_id: str, text: str) -> bool:
        """Proactively send a text message to a chat/channel/number."""
