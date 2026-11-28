from typing import Callable, Dict, Any, List, Optional, Set
from pydantic import BaseModel
import inspect
import json


class Tool(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Any = None

    class Config:
        arbitrary_types_allowed = True

    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    async def execute(self, **kwargs) -> Any:
        sig = inspect.signature(self.handler)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if not has_var_keyword:
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        else:
            filtered_kwargs = kwargs

        if inspect.iscoroutinefunction(self.handler):
            return await self.handler(**filtered_kwargs)
        return self.handler(**filtered_kwargs)


class ToolRegistry:
    """Tool registry with optional runtime toolset and per-tool access policies."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._toolsets: Dict[str, str] = {}
        self._enabled_toolsets: Optional[Set[str]] = None
        self._disabled_tools: Set[str] = set()

    def register(self, tool: Tool, toolset: str = "custom"):
        self._tools[tool.name] = tool
        self._toolsets[tool.name] = (toolset or "custom").strip().lower()

    def set_toolset_policy(self, enabled_toolsets=None, disabled_tools=None) -> None:
        """Restrict this registry to enabled toolsets and explicitly disabled tool names."""
        self._enabled_toolsets = (
            {str(name).strip().lower() for name in enabled_toolsets}
            if enabled_toolsets is not None else None
        )
        self._disabled_tools = {
            str(name).strip().lower() for name in (disabled_tools or [])
        }

    def clone(self):
        """Copy registry metadata while reusing immutable Tool definitions/handlers."""
        cloned = ToolRegistry()
        for name, tool in self._tools.items():
            cloned.register(tool, toolset=self._toolsets.get(name, "custom"))
        cloned.set_toolset_policy(
            enabled_toolsets=self._enabled_toolsets,
            disabled_tools=self._disabled_tools,
        )
        return cloned

    def _is_enabled(self, name: str) -> bool:
        if name.lower() in self._disabled_tools:
            return False
        toolset = self._toolsets.get(name, "custom")
        return self._enabled_toolsets is None or toolset in self._enabled_toolsets

    def _resolve_unfiltered(self, name: str) -> Optional[Tool]:
        if not name:
            return None
        if name in self._tools:
            return self._tools[name]

        aliases = {
            "websearch": "web_search",
            "search_web": "web_search",
            "search": "web_search",
            "google_search": "web_search",
            "webextract": "web_extract",
            "extract_web": "web_extract",
            "fetch_url": "web_extract",
            "curl": "web_extract",
            "read": "read_file",
            "cat": "read_file",
            "readfile": "read_file",
            "writefile": "write_file",
            "patchfile": "patch_file",
            "listdir": "list_dir",
            "searchfiles": "search_files",
            "search_file": "search_files",
            "grep": "search_files",
            "runcommand": "run_command",
            "bash": "run_command",
            "terminal": "run_command",
            "shell": "run_command",
            "cmd": "run_command",
            "viewimage": "view_image",
            "image": "view_image",
            "computer_use": "computer",
            "desktop": "computer",
            "gui": "computer",
            "mouse": "computer",
            "keyboard": "computer",
            "screenshot": "computer",
            "recallmemory": "recall_memory",
            "storememory": "store_memory",
            "delegatetask": "delegate_task",
            "delegate": "delegate_task",
            "subagent": "delegate_task",
            "scheduletask": "schedule_task",
            "cron": "schedule_task"
        }
        low = name.lower().strip()
        target = aliases.get(low)
        if target and target in self._tools:
            return self._tools[target]

        norm = low.replace("_", "").replace("-", "").replace(" ", "")
        for tool_name, tool in self._tools.items():
            candidate = tool_name.lower().replace("_", "").replace("-", "").replace(" ", "")
            if candidate == norm:
                return tool
        return None

    def get(self, name: str) -> Optional[Tool]:
        tool = self._resolve_unfiltered(name)
        if tool is None or not self._is_enabled(tool.name):
            return None
        return tool

    def get_all(self, include_inactive: bool = False) -> List[Tool]:
        if include_inactive:
            return list(self._tools.values())
        return [tool for name, tool in self._tools.items() if self._is_enabled(name)]

    def to_openai_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self.get_all()]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        tool = self.get(name)
        if not tool:
            # Distinguish disabled tools from unknown tools without leaking hidden schemas.
            hidden = self._resolve_unfiltered(name)
            if hidden:
                return f"Access denied: Tool '{hidden.name}' is disabled by the active toolset profile."
            return f"Error: Tool '{name}' not found."
        try:
            res = await tool.execute(**arguments)
            if isinstance(res, (dict, list)):
                return json.dumps(res, indent=2)
            return str(res)
        except Exception as e:
            return f"Error executing tool '{name}': {str(e)}"
