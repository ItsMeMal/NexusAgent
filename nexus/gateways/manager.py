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
    """Create the gateway_send tool matching Nolthira's Pydantic Tool pattern."""
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
        toolset_manager: Optional[Any] = None,
    ):
        self.on_log = on_log
        self.toolset_manager = toolset_manager

        def _registry_for(platform: str) -> ToolRegistry:
            if self.toolset_manager is None:
                return registry
            scoped = registry.clone()
            profile = self.toolset_manager.profile_for_platform(platform)
            self.toolset_manager.apply(scoped, profile=profile)
            return scoped

        self.gateways: Dict[str, BaseGateway] = {
            "telegram": TelegramGateway(llm_client, memory, skill_manager, _registry_for("telegram"), soul_path, max_steps, on_log=on_log),
            "discord": DiscordGateway(llm_client, memory, skill_manager, _registry_for("discord"), soul_path, max_steps, on_log=on_log),
            "whatsapp": WhatsAppGateway(llm_client, memory, skill_manager, _registry_for("whatsapp"), soul_path, max_steps, on_log=on_log),
            "slack": SlackGateway(llm_client, memory, skill_manager, _registry_for("slack"), soul_path, max_steps, on_log=on_log),
            "email": EmailGateway(llm_client, memory, skill_manager, _registry_for("email"), soul_path, max_steps, on_log=on_log),
        }
        self._tasks: Dict[str, asyncio.Task] = {}
        self._start_lock = asyncio.Lock()

    def register_tools(self, registry: ToolRegistry):
        registry.register(create_gateway_send_tool(self), toolset="gateway")

    def _apply_platform_profile(self, platform: str) -> None:
        """Refresh one stopped gateway's tool policy before its next start."""
        if self.toolset_manager is None:
            return
        gateway = self.gateways.get(platform)
        if gateway is None:
            return
        profile = self.toolset_manager.profile_for_platform(platform)
        self.toolset_manager.apply(gateway.registry, profile=profile)

    def get_statuses(self) -> List[GatewayStatus]:
        return [gw.get_status() for gw in self.gateways.values()]

    def _on_gateway_task_done(self, key: str, task: asyncio.Task) -> None:
        gateway = self.gateways.get(key)
        if gateway is None:
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            gateway.last_error = str(error)
            gateway.running = False
            if self.on_log:
                try:
                    self.on_log(key, f"[ERROR] Gateway task terminated: {error}")
                except Exception:
                    pass

    async def start_gateway(self, name: str = "all") -> Dict[str, str]:
        """Start one or all configured gateways and report immediate startup failures."""
        targets = list(self.gateways.keys()) if name == "all" else [name.lower()]
        results: Dict[str, str] = {}

        async with self._start_lock:
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

                self._apply_platform_profile(key)
                gw.last_error = ""
                task = asyncio.create_task(gw.start(), name=f"nolthira-gateway-{key}")
                task.add_done_callback(
                    lambda completed, gateway_key=key: self._on_gateway_task_done(gateway_key, completed)
                )
                self._tasks[key] = task
                results[key] = "started"

        # Give adapters a short window to perform token checks/handshakes.
        if any(value == "started" for value in results.values()):
            await asyncio.sleep(0.8)
            for key, value in list(results.items()):
                if value != "started":
                    continue
                task = self._tasks.get(key)
                gateway = self.gateways[key]
                if task and task.done():
                    try:
                        error = task.exception()
                    except asyncio.CancelledError:
                        error = None
                    if error or gateway.last_error:
                        results[key] = "failed"
                    else:
                        results[key] = "stopped"

        return results

    async def stop_gateway(self, name: str = "all") -> Dict[str, str]:
        """Stop one or all gateway tasks and consume any task exception."""
        targets = list(self.gateways.keys()) if name == "all" else [name.lower()]
        results: Dict[str, str] = {}

        for key in targets:
            gateway = self.gateways.get(key)
            task = self._tasks.pop(key, None)
            if gateway:
                try:
                    await gateway.stop()
                except Exception as exc:
                    gateway.last_error = str(exc)
                    results[key] = "failed"
                    continue
            if task:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    if gateway:
                        gateway.last_error = str(exc)
                    results[key] = "failed"
                    continue
                results.setdefault(key, "stopped")
            else:
                results.setdefault(key, "not_running")

        return results

    async def run_foreground(self, target: str = "all"):
        """Run configured gateways in the foreground while isolating per-gateway failures."""
        targets = list(self.gateways.keys()) if target == "all" else [target.lower()]
        active_tasks: List[asyncio.Task] = []

        for key in targets:
            gateway = self.gateways.get(key)
            if gateway and gateway.is_configured():
                self._apply_platform_profile(key)
                gateway.last_error = ""
                task = asyncio.create_task(gateway.start(), name=f"nolthira-gateway-{key}")
                task.add_done_callback(
                    lambda completed, gateway_key=key: self._on_gateway_task_done(gateway_key, completed)
                )
                self._tasks[key] = task
                active_tasks.append(task)

        if not active_tasks:
            return False

        try:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        finally:
            await self.stop_gateway("all")
        return True
