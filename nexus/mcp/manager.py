import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from ..tools.base import Tool, ToolRegistry
from ..config import config

@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    active: bool = True

class MCPManager:
    """Manages Model Context Protocol (MCP) server configurations and integrations."""

    def __init__(self, workspace_dir: Path = config.WORKSPACE_DIR, codebase_dir: Path = config.CODEBASE_DIR):
        self.workspace_dir = workspace_dir
        self.codebase_dir = codebase_dir
        self.servers: Dict[str, MCPServerConfig] = {}
        self.loaded_tools: List[Tool] = []
        self._load_configs()

    def _get_config_files(self) -> List[Path]:
        candidates = [
            self.workspace_dir / ".mcp.json",
            self.workspace_dir / "mcp.json",
            self.workspace_dir / "mcp_servers.json",
            self.codebase_dir / ".mcp.json",
            self.codebase_dir / "mcp_servers.json"
        ]
        return [p for p in candidates if p.exists()]

    def _load_configs(self):
        """Parse MCP server definitions from json files."""
        for cfg_path in self._get_config_files():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                servers_dict = data.get("mcpServers", data.get("servers", {}))
                for s_name, s_info in servers_dict.items():
                    if isinstance(s_info, dict):
                        self.servers[s_name] = MCPServerConfig(
                            name=s_name,
                            command=s_info.get("command", ""),
                            args=s_info.get("args", []),
                            env=s_info.get("env", {})
                        )
            except Exception:
                pass

    def list_servers(self) -> List[MCPServerConfig]:
        return list(self.servers.values())

    def register_mcp_tools(self, registry: ToolRegistry):
        """Register MCP proxy tools into the primary registry."""
        for tool in self.loaded_tools:
            registry.register(tool)
