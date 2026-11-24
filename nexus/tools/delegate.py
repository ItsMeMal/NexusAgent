import json
from typing import List, Dict, Any, Optional
from .base import Tool

def get_orchestration_tools(subagent_manager: Any, current_session_getter):
    async def delegate_task(
        goal: Optional[str] = None,
        task: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
        context: str = "",
        toolsets: Any = None,
        role: str = "leaf",
        **extra_kwargs
    ) -> str:
        """Delegate a sub-task or parallel investigation to an isolated subagent worker."""
        # 1. Resilient goal resolution across diverse LLM parameter habits
        final_goal = goal or task or prompt or description
        if not final_goal:
            for k in ("query", "instruction", "objective", "message"):
                if k in extra_kwargs and isinstance(extra_kwargs[k], str) and extra_kwargs[k].strip():
                    final_goal = extra_kwargs[k].strip()
                    break

        if not final_goal:
            return "Error: A 'goal' or 'task' description must be provided for the subagent worker."

        # 2. Resilient toolsets resolution (handles list, string, or json array)
        resolved_toolsets: Optional[List[str]] = None
        if isinstance(toolsets, str):
            t_str = toolsets.strip()
            if t_str.startswith("[") and t_str.endswith("]"):
                try:
                    parsed = json.loads(t_str)
                    if isinstance(parsed, list):
                        resolved_toolsets = [str(x).strip(" '\"\\") for x in parsed if str(x).strip(" '\"\\")]
                except Exception:
                    cleaned = t_str.strip("[]'\"\\ ")
                    resolved_toolsets = [s.strip(" '\"\\") for s in cleaned.split(",") if s.strip(" '\"\\")]
            elif "," in t_str:
                resolved_toolsets = [s.strip(" '\"\\") for s in t_str.split(",") if s.strip(" '\"\\")]
            elif t_str:
                resolved_toolsets = [t_str.strip(" '\"\\")]
        elif isinstance(toolsets, list):
            resolved_toolsets = [str(x).strip(" '\"\\") for x in toolsets if str(x).strip(" '\"\\")]

        parent_session = current_session_getter()
        return await subagent_manager.delegate(
            parent_session_id=parent_session,
            goal=final_goal,
            context=context,
            toolsets=resolved_toolsets,
            role=role or "leaf"
        )

    return [
        Tool(
            name="delegate_task",
            description=(
                "Spawn an isolated subagent worker to execute a specific sub-task in parallel or deep-dive, "
                "keeping your primary context window clean and focused. Essential for large code refactors, "
                "multi-file investigations, external research, or batch testing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The exact goal or problem the subagent must investigate or solve"
                    },
                    "context": {
                        "type": "string",
                        "description": "Background context, relevant file paths, or constraints for the subagent",
                        "default": ""
                    },
                    "toolsets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of toolsets to grant (options: 'filesystem', 'terminal', 'web', 'memory', 'skills', 'computer')",
                        "default": ["filesystem", "terminal", "web"]
                    },
                    "role": {
                        "type": "string",
                        "description": "Role label for the subagent (e.g. 'researcher', 'debugger', 'refactorer')",
                        "default": "leaf"
                    }
                },
                "required": ["goal"]
            },
            handler=delegate_task
        )
    ]
