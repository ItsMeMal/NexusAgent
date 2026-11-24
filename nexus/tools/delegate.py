from typing import List, Dict, Any, Optional
from .base import Tool

def get_orchestration_tools(subagent_manager: Any, current_session_getter):
    async def delegate_task(
        goal: str,
        context: str = "",
        toolsets: Optional[List[str]] = None,
        role: str = "leaf"
    ) -> str:
        """Delegate a sub-task or parallel investigation to an isolated subagent worker."""
        parent_session = current_session_getter()
        return await subagent_manager.delegate(
            parent_session_id=parent_session,
            goal=goal,
            context=context,
            toolsets=toolsets,
            role=role
        )

    return [
        Tool(
            name="delegate_task",
            description=(
                "Spawn an isolated subagent worker to execute a specific sub-task in parallel or deep-dive, "
                "keeping your primary context window clean and focused. Essential for large code refactors, "
                "multi-file investigations, or external research."
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
                        "description": "List of toolsets to grant (options: 'filesystem', 'terminal', 'web', 'memory', 'skills')",
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
