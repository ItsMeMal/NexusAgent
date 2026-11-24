import uuid
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from ..core.llm import LLMClient
from ..core.agent import NexusAgent
from ..memory import SQLiteMemory
from ..skills import SkillManager
from ..tools.base import ToolRegistry
from ..tools.filesystem import get_filesystem_tools
from ..tools.terminal import get_terminal_tools
from ..tools.web import get_web_tools
from ..tools.memory_tools import get_memory_tools
from ..tools.skill_tools import get_skill_tools
from ..config import config

class SubagentManager:
    def __init__(
        self,
        llm: LLMClient,
        memory: SQLiteMemory,
        skill_manager: SkillManager,
        root_dir: Path,
        on_subagent_event: Optional[Callable[[str, str], None]] = None
    ):
        self.llm = llm
        self.memory = memory
        self.skill_manager = skill_manager
        self.root_dir = root_dir
        self.on_subagent_event = on_subagent_event

    def build_scoped_registry(self, toolset_names: Optional[List[str]] = None) -> ToolRegistry:
        registry = ToolRegistry()
        all_toolsets = {
            "filesystem": lambda: get_filesystem_tools(self.root_dir),
            "file_ops": lambda: get_filesystem_tools(self.root_dir),
            "terminal": lambda: get_terminal_tools(self.root_dir),
            "web": lambda: get_web_tools(),
            "memory": lambda: get_memory_tools(self.memory),
            "skills": lambda: get_skill_tools(self.skill_manager),
        }

        # If not specified, leaf subagent gets filesystem, terminal, and web
        if not toolset_names:
            toolset_names = ["filesystem", "terminal", "web"]

        for name in toolset_names:
            factory = all_toolsets.get(name.lower())
            if factory:
                for tool in factory():
                    registry.register(tool)

        return registry

    async def delegate(
        self,
        parent_session_id: str,
        goal: str,
        context: str = "",
        toolsets: Optional[List[str]] = None,
        role: str = "leaf",
        max_steps: int = 15
    ) -> str:
        """Spawn an isolated subagent worker to execute a delegated goal."""
        sub_id = f"{parent_session_id}-sub-{uuid.uuid4().hex[:6]}"
        scoped_registry = self.build_scoped_registry(toolset_names=toolsets)

        if self.on_subagent_event:
            self.on_subagent_event("start", f"Spawning Subagent [{role}] for goal: {goal}")

        subagent_soul = f"""# Scoped Subagent Worker (Role: {role})

You are a dedicated specialist subagent dispatched by the primary orchestrator to accomplish a focused goal.
Your Goal: {goal}
Additional Context from Orchestrator:
{context}

Rules:
1. Focus strictly on executing the delegated goal.
2. Use your tools directly to investigate, edit, test, or search.
3. When finished, provide a concise, factual summary of findings and actions taken.
"""
        # Create dedicated subagent
        subagent = NexusAgent(
            llm_client=self.llm,
            memory=self.memory,
            skill_manager=self.skill_manager,
            registry=scoped_registry,
            max_steps=max_steps,
            session_id=sub_id,
            on_thought=lambda t: self.on_subagent_event("thought", t) if self.on_subagent_event else None,
            on_tool_call=lambda name, args: self.on_subagent_event("tool_call", f"[{sub_id}] Tool {name}: {args}") if self.on_subagent_event else None,
            on_tool_result=lambda name, res: self.on_subagent_event("tool_result", f"[{sub_id}] Result {name}: {res[:200]}") if self.on_subagent_event else None,
        )

        # Override soul prompt for this focused task
        original_build = subagent.build_system_prompt
        subagent.build_system_prompt = lambda: subagent_soul + "\n" + original_build()

        try:
            result = await subagent.run(f"Execute the delegated task: {goal}")
            if self.on_subagent_event:
                self.on_subagent_event("finish", f"Subagent [{sub_id}] completed work.")
            return f"[Subagent '{role}' Result]:\n{result}"
        except Exception as e:
            err_msg = f"Subagent error: {str(e)}"
            if self.on_subagent_event:
                self.on_subagent_event("error", err_msg)
            return err_msg
