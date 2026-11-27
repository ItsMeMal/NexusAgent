import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

from ..config import config
from ..core.llm import LLMClient
from ..memory import SQLiteMemory
from ..skills import SkillManager
from ..tools.base import Tool, ToolRegistry
from .base import BaseGateway, GatewayStatus
from .telegram import TelegramGateway
from .discord import DiscordGateway
from .whatsapp import WhatsAppGateway
from .slack import SlackGateway
from .email_gw import EmailGateway


def create_gateway_send_tool(manager: "GatewayManager") -> Tool:
    """Create the gateway_send tool matching Nexus's Pydantic Tool pattern."""
    async def gateway_send(platform: str, target: str, message: str) -> str:
        gw = manager.gateways.get(platform.lower())
        if not gw:
            return f"Unknown gateway platform '{platform}'. Available: telegram, discord, whatsapp, slack, email."
        if not gw.is_configured():
            return f"Gateway '{platform}' is not configured in .env. Run /gateway setup first."
        ok = await gw.send_text(target, message)
        if ok:
            return f"Message sent via {platform} to {target}."
        return f"Failed to send via {platform}: {gw.last_error or 'unknown error'}"

    return Tool(
        name="gateway_send",
        description=(
            "Send a proactive message to a user, channel, or address via configured messaging gateways "
            "(telegram, discord, whatsapp, slack, email). Useful for notifications, alerts, or cross-platform replies."
        ),
        parameters={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["telegram", "discord", "whatsapp", "slack", "email"],
                    "description": "Target messaging platform."
                },
                "target": {
                    "type": "string",
                    "description": "Recipient chat ID (Telegram), channel ID (Discord), or phone number/JID (WhatsApp)."
                },
                "message": {
                    "type": "string",
                    "description": "Text content to send."
                }
            },
            "required": ["platform", "target", "message"]
        },
        handler=gateway_send,
    )


class GatewayManager:
    """Orchestrates Telegram, Discord, and WhatsApp messaging gateways (Hermes-style)."""

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
        self.on_log = on_log
        self.gateways: Dict[str, BaseGateway] = {
            "telegram": TelegramGateway(llm_client, memory, skill_manager, registry, soul_path, max_steps, on_log=on_log),
            "discord": DiscordGateway(llm_client, memory, skill_manager, registry, soul_path, max_steps, on_log=on_log),
            "whatsapp": WhatsAppGateway(llm_client, memory, skill_manager, registry, soul_path, max_steps, on_log=on_log),
            "slack": SlackGateway(llm_client, memory, skill_manager, registry, soul_path, max_steps, on_log=on_log),
            "email": EmailGateway(llm_client, memory, skill_manager, registry, soul_path, max_steps, on_log=on_log),
        }
        self._tasks: Dict[str, asyncio.Task] = {}

    def register_tools(self, registry: ToolRegistry):
        registry.register(create_gateway_send_tool(self))

    def get_statuses(self) -> List[GatewayStatus]:
        return [gw.get_status() for gw in self.gateways.values()]

    async def start_gateway(self, name: str = "all") -> Dict[str, str]:
        """Start one or all configured gateways as background tasks."""
        targets = list(self.gateways.keys()) if name == "all" else [name.lower()]
        results: Dict[str, str] = {}

        for key in targets:
            gw = self.gateways.get(key)
            if not gw:
                results[key] = "unknown"
                continue
            if not gw.is_configured():
                results[key] = "not_configured"
                continue
            existing = self._tasks.get(key)
            if existing and not existing.done():
                results[key] = "already_running"
                continue

            task = asyncio.create_task(gw.start(), name=f"nexus-gateway-{key}")
            self._tasks[key] = task
            results[key] = "started"

        # Brief yield to allow initial handshakes / binding to start
        if any(v == "started" for v in results.values()):
            await asyncio.sleep(0.8)

        return results

    async def stop_gateway(self, name: str = "all") -> Dict[str, str]:
        """Stop one or all running gateway tasks."""
        targets = list(self.gateways.keys()) if name == "all" else [name.lower()]
        results: Dict[str, str] = {}

        for key in targets:
            gw = self.gateways.get(key)
            if gw:
                await gw.stop()
            task = self._tasks.pop(key, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                results[key] = "stopped"
            else:
                results[key] = "not_running"

        return results

    async def run_foreground(self, target: str = "all"):
        """Run gateway daemon in foreground (for `nexus --gateway`)."""
        targets = list(self.gateways.keys()) if target == "all" else [target.lower()]
        active_tasks: List[asyncio.Task] = []

        for key in targets:
            gw = self.gateways.get(key)
            if gw and gw.is_configured():
                active_tasks.append(asyncio.create_task(gw.start(), name=f"nexus-gateway-{key}"))

        if not active_tasks:
            return False

        try:
            await asyncio.gather(*active_tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop_gateway("all")
        return True
