import json
import importlib.util
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from ..tools.base import Tool, ToolRegistry
from ..config import config

@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    path: Path
    author: str = ""
    enabled: bool = True
    tools_count: int = 0

class PluginManager:
    """Discovers and manages modular plugins located in plugins/ or .plugins/ directory."""

    def __init__(self, workspace_dir: Path = config.WORKSPACE_DIR, codebase_dir: Path = config.CODEBASE_DIR):
        self.plugin_dirs = [
            workspace_dir / "plugins",
            workspace_dir / ".plugins",
            codebase_dir / "plugins"
        ]
        self.plugins: Dict[str, PluginInfo] = {}
        self.plugin_tools: List[Tool] = []
        self._discover_plugins()

    def _discover_plugins(self):
        for pdir in self.plugin_dirs:
            if not pdir.exists() or not pdir.is_dir():
                continue
            for item in pdir.iterdir():
                if item.is_dir():
                    manifest_path = item / "plugin.json"
                    if manifest_path.exists():
                        try:
                            meta = json.loads(manifest_path.read_text(encoding="utf-8"))
                            p_name = meta.get("name", item.name)
                            self.plugins[p_name] = PluginInfo(
                                name=p_name,
                                version=meta.get("version", "1.0.0"),
                                description=meta.get("description", "Nexus Agent Extension Plugin"),
                                path=item,
                                author=meta.get("author", "Community"),
                                enabled=True
                            )
                        except Exception:
                            pass

    def list_plugins(self) -> List[PluginInfo]:
        return list(self.plugins.values())

    def register_plugin_tools(self, registry: ToolRegistry):
        for t in self.plugin_tools:
            registry.register(t)
