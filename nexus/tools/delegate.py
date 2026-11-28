import json
from typing import List, Dict, Any, Optional
from .base import Tool


def _normalize_toolsets(toolsets: Any) -> Optional[List[str]]:
    if isinstance(toolsets, str):
        value = toolsets.strip()
        if not value:
            return None
        try:
            parsed = json.loads(value) if value.startswith("[") else None
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(toolsets, list):
        return [str(item).strip() for item in toolsets if str(item).strip()]
    return None


def get_orchestration_tools(subagent_manager: Any, current_session_getter):
    async def delegate_task(
        goal: Optional[str] = None,
        task: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
        context: str = "",
        toolsets: Any = None,
        role: str = "leaf",
        max_steps: int = 20,
        timeout_seconds: int = 600,
        **extra_kwargs
    ) -> str:
        """Delegate one focused sub-task to a role-scoped worker."""
        final_goal = goal or task or prompt or description
        if not final_goal:
            for key in ("query", "instruction", "objective", "message"):
                value = extra_kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    final_goal = value.strip()
                    break
        if not final_goal:
            return "Error: A non-empty 'goal' or 'task' description is required."

        return await subagent_manager.delegate(
            parent_session_id=current_session_getter(),
            goal=str(final_goal),
            context=context,
            toolsets=_normalize_toolsets(toolsets),
            role=role or "leaf",
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )

    async def delegate_tasks(tasks: Any, **kwargs) -> str:
        """Run several independent subagent tasks concurrently."""
        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except json.JSONDecodeError as exc:
                return f"Error: tasks must be a JSON array ({exc})."
        if not isinstance(tasks, list):
            return "Error: tasks must be an array of task objects."
        for item in tasks:
            if isinstance(item, dict) and "toolsets" in item:
                item["toolsets"] = _normalize_toolsets(item["toolsets"])
        return await subagent_manager.delegate_many(
            parent_session_id=current_session_getter(),
            tasks=tasks,
        )

    return [
        Tool(
            name="delegate_task",
            description=(
                "Spawn one isolated, role-scoped subagent for a focused investigation or implementation task. "
                "Use researcher/analyst for read-oriented work and coder/debugger/refactorer for code changes. "
                "Use delegate_tasks when several independent workstreams should run concurrently."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Exact objective for the subagent"},
                    "context": {"type": "string", "description": "Relevant background, paths, and constraints", "default": ""},
                    "toolsets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional narrower permission set. This can only reduce the role's configured access.",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["leaf", "researcher", "analyst", "coder", "debugger", "refactorer"],
                        "description": "Permission profile and specialist role",
                        "default": "leaf",
                    },
                    "max_steps": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    "timeout_seconds": {"type": "integer", "minimum": 5, "maximum": 3600, "default": 600},
                },
                "required": ["goal"],
            },
            handler=delegate_task,
        ),
        Tool(
            name="delegate_tasks",
            description=(
                "Dispatch 2-8 independent subtasks concurrently to isolated subagents. "
                "Each item accepts goal, context, role, toolsets, max_steps, and timeout_seconds. "
                "Do not split tasks that edit the same files or depend on each other's output."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "goal": {"type": "string"},
                                "context": {"type": "string"},
                                "role": {"type": "string", "enum": ["leaf", "researcher", "analyst", "coder", "debugger", "refactorer"]},
                                "toolsets": {"type": "array", "items": {"type": "string"}},
                                "max_steps": {"type": "integer", "minimum": 1, "maximum": 50},
                                "timeout_seconds": {"type": "integer", "minimum": 5, "maximum": 3600},
                            },
                            "required": ["goal"],
                        },
                    },
                },
                "required": ["tasks"],
            },
            handler=delegate_tasks,
        ),
    ]
