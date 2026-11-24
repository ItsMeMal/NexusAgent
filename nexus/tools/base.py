from typing import Callable, Dict, Any, List, Optional
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
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        if not name:
            return None
        # 1. Exact match
        if name in self._tools:
            return self._tools[name]

        # 2. Common LLM alias dictionary
        aliases = {
            "websearch": "web_search",
            "search_web": "web_search",
            "search": "web_search",
            "google_search": "web_search",
            "webextract": "web_extract",
            "extract_web": "web_extract",
            "fetch_url": "web_extract",
            "curl": "web_extract",
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
            "recallmemory": "recall_memory",
            "storememory": "store_memory",
            "delegatetask": "delegate_task",
            "delegate": "delegate_task",
            "subagent": "delegate_task",
            "scheduletask": "schedule_task",
            "cron": "schedule_task"
        }
        low = name.lower().strip()
        if low in aliases and aliases[low] in self._tools:
            return self._tools[aliases[low]]

        # 3. Normalized match (strip underscores, dashes, spaces)
        norm = low.replace("_", "").replace("-", "").replace(" ", "")
        for t_name, tool in self._tools.items():
            t_norm = t_name.lower().replace("_", "").replace("-", "").replace(" ", "")
            if t_norm == norm:
                return tool

        return None

    def get_all(self) -> List[Tool]:
        return list(self._tools.values())

    def to_openai_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self._tools.values()]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        tool = self.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found."
        try:
            res = await tool.execute(**arguments)
            if isinstance(res, (dict, list)):
                return json.dumps(res, indent=2)
            return str(res)
        except Exception as e:
            return f"Error executing tool '{name}': {str(e)}"
