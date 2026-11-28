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
    skills_count: int = 0

class PluginManager:
    """Discovers and manages modular plugins located in plugins/ or .plugins/ directory."""

    def __init__(self, workspace_dir: Path = config.WORKSPACE_DIR, codebase_dir: Path = config.CODEBASE_DIR):
        self.plugin_dirs = [
            workspace_dir / "plugins",
            workspace_dir / ".plugins",
            config.NOLTHIRA_HOME / "plugins",
            codebase_dir / "plugins"
        ]
        self.plugins: Dict[str, PluginInfo] = {}
        self.plugin_tools: List[Tool] = []
        self._discover_plugins()

    def _discover_plugins(self):
        for pdir in self.plugin_dirs:
            if not pdir.exists() or not pdir.is_dir():
                continue
            for item in sorted(pdir.iterdir()):
                if not item.is_dir():
                    continue
                manifest_path = item / "plugin.json"
                if not manifest_path.exists():
                    manifest_path = item / ".claude-plugin" / "plugin.json"
                if manifest_path.exists():
                    try:
                        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
                        p_name = meta.get("name", item.name)
                        if p_name in self.plugins:
                            continue
                        raw_author = meta.get("author", "Community")
                        if isinstance(raw_author, dict):
                            author_str = raw_author.get("name", "Community")
                        else:
                            author_str = str(raw_author or "Community")

                        skills_rel = meta.get("skills", "skills")
                        skills_sub = item / skills_rel if isinstance(skills_rel, str) else item / "skills"
                        skills_cnt = 0
                        if skills_sub.exists() and skills_sub.is_dir():
                            skills_cnt = len(list(skills_sub.glob("*/SKILL.md")) + list(skills_sub.glob("*.md")))

                        self.plugins[p_name] = PluginInfo(
                            name=p_name,
                            version=meta.get("version", "1.0.0"),
                            description=meta.get("description", "Nexus Agent Extension Plugin"),
                            path=item,
                            author=author_str,
                            enabled=True,
                            skills_count=skills_cnt,
                        )
                    except Exception:
                        pass

    def list_plugins(self) -> List[PluginInfo]:
        return list(self.plugins.values())

    def register_plugin_tools(self, registry: ToolRegistry):
        for t in self.plugin_tools:
            registry.register(t, toolset="plugins")
