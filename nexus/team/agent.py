"""
nexus/team/agent.py
TeamAgent — an autonomous tool-using NexusAgent specialist in an AI-Team.

Each TeamAgent runs a real ReAct loop via NexusAgent with:
  - Role persona & system prompt
  - Role-scoped real tools (filesystem, terminal, web, memory, skills, MCP)
  - Shared Team Board & Mailbox tools (team_read_board, team_send_message, team_update_task, team_request_fix)
  - Live callbacks streaming thoughts and tool calls to TeamBoard (Web Dashboard + Terminal TUI)
"""

from __future__ import annotations

import json
import uuid
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.agent import NexusAgent
from ..config import config
from .board import TeamBoard
from .team_tools import build_team_agent_registry

logger = logging.getLogger(__name__)


@dataclass
class AgentRole:
    """Definition of a specialized team member role."""
    id: str                   # unique slug e.g. "coder", "reviewer", "tester"
    name: str                 # display name e.g. "Code Writer"
    emoji: str                # kept for CLI/chat display
    system_prompt: str        # role specialization
    description: str = ""     # one-liner shown in /team roles
    toolsets: List[str] = field(default_factory=lambda: ["filesystem", "terminal", "web"])
    read_only_fs: bool = False
    max_steps: int = 12


LEAD_ROLE = AgentRole(
    id="lead",
    name="Team Lead",
    emoji="🧭",
    description="Coordinates the AI-Team, plans shared board tasks, and synthesizes verified work",
    toolsets=["filesystem", "web", "memory", "skills"],
    read_only_fs=True,
    max_steps=10,
    system_prompt=(
        "You are the Team Lead orchestrating an autonomous AI-Team working in a real workspace. "
        "Inspect the workspace if relevant, break the user's goal into clear concrete tasks on the Shared Task Board "
        "using `team_create_task`, coordinate teammates with `team_send_message`, and synthesize verified outcomes."
    ),
)


# ------------------------------------------------------------------
# Built-in roles
# ------------------------------------------------------------------

BUILTIN_ROLES: List[AgentRole] = [
    AgentRole(
        id="planner",
        name="Planner",
        emoji="🗺️",
        description="Inspects workspace & breaks down complex tasks into actionable architecture",
        toolsets=["filesystem", "web", "skills", "memory"],
        read_only_fs=True,
        max_steps=8,
        system_prompt=(
            "You are the Planner agent in a collaborative AI-Team. "
            "Inspect the workspace first with `list_dir`/`read_file` if files exist, then produce a crisp, concrete "
            "architecture and file plan so teammates can build immediately."
        ),
    ),
    AgentRole(
        id="coder",
        name="Code Writer",
        emoji="💻",
        description="Writes & modifies real files in the workspace cleanly",
        toolsets=["filesystem", "terminal", "web", "skills"],
        read_only_fs=False,
        max_steps=16,
        system_prompt=(
            "You are the Code Writer agent in a collaborative AI-Team. "
            "Implement clean, production-ready code directly in the workspace using `write_file` and `patch_file`, "
            "inspecting existing files first with `list_dir`/`read_file` and running build/lint checks via `run_command` when useful."
        ),
    ),
    AgentRole(
        id="reviewer",
        name="Code Reviewer",
        emoji="🔍",
        description="Inspects actual workspace files for bugs, security, and craft",
        toolsets=["filesystem", "terminal"],
        read_only_fs=True,
        max_steps=10,
        system_prompt=(
            "You are the Code Reviewer agent in a collaborative AI-Team. "
            "Read the actual workspace files with `read_file`/`list_dir` (never guess), check for bugs, edge cases, "
            "and quality issues. If a real bug needs fixing by another role, call `team_request_fix` or report findings clearly."
        ),
    ),
    AgentRole(
        id="tester",
        name="QA Tester",
        emoji="🧪",
        description="Writes & executes real tests and verifies runtime behavior",
        toolsets=["filesystem", "terminal"],
        read_only_fs=False,
        max_steps=12,
        system_prompt=(
            "You are the QA Tester agent in a collaborative AI-Team. "
            "Read the created files, write or run real verification/tests using `write_file` and `run_command`, "
            "and report exact command outputs. If tests fail, call `team_request_fix` assigned to `coder`."
        ),
    ),
    AgentRole(
        id="writer",
        name="Technical Writer",
        emoji="📝",
        description="Writes clear documentation and READMEs grounded in actual files",
        toolsets=["filesystem", "web"],
        read_only_fs=False,
        max_steps=8,
        system_prompt=(
            "You are the Technical Writer agent in a collaborative AI-Team. "
            "Inspect actual files with `read_file` and write concise, accurate documentation using `write_file` or summarize usage."
        ),
    ),
    AgentRole(
        id="analyst",
        name="Data Analyst",
        emoji="📊",
        description="Analyzes workspace data, logs, and web research for insights",
        toolsets=["filesystem", "terminal", "web"],
        read_only_fs=True,
        max_steps=10,
        system_prompt=(
            "You are the Data Analyst agent in a collaborative AI-Team. "
            "Use your tools (`read_file`, `search_files`, `run_command`, `web_search`) to gather real evidence, "
            "find patterns, and present structured, factual insights."
        ),
    ),
    AgentRole(
        id="devops",
        name="DevOps Engineer",
        emoji="⚙️",
        description="Handles CI/CD, Docker, scripts, and runtime configuration",
        toolsets=["filesystem", "terminal", "web"],
        read_only_fs=False,
        max_steps=12,
        system_prompt=(
            "You are the DevOps Engineer agent in a collaborative AI-Team. "
            "Inspect project setup and create/verify real configs, scripts, Dockerfiles, or CI workflows using tools."
        ),
    ),
    AgentRole(
        id="security",
        name="Security Auditor",
        emoji="🛡️",
        description="Audits actual codebase & configs for vulnerabilities",
        toolsets=["filesystem", "terminal", "web"],
        read_only_fs=True,
        max_steps=10,
        system_prompt=(
            "You are the Security Auditor agent in a collaborative AI-Team. "
            "Inspect actual files with `search_files` and `read_file` for vulnerabilities (OWASP Top 10, injection, secrets, auth). "
            "Use `team_request_fix` if critical vulnerabilities are found."
        ),
    ),
]

BUILTIN_ROLES_BY_ID: Dict[str, AgentRole] = {r.id: r for r in BUILTIN_ROLES}


def _summarize_args(args: Any) -> str:
    if isinstance(args, dict):
        parts = []
        for k, v in args.items():
            s = str(v)
            if len(s) > 48:
                s = s[:45] + "..."
            parts.append(f"{k}={s}")
        return ", ".join(parts)
    return str(args)[:120]


class TeamAgent:
    """
    Autonomous specialist agent inside an AI-Team.
    When given `memory`, `skill_manager`, `root_dir`, and `board`, runs a full tool-using NexusAgent loop.
    """

    def __init__(
        self,
        role: AgentRole,
        llm_client,
        memory=None,
        skill_manager=None,
        root_dir: Optional[Path] = None,
        board: Optional[TeamBoard] = None,
        parent_registry=None,
        allow_task_creation: bool = False,
    ) -> None:
        self.role = role
        self.llm = llm_client
        self.memory = memory
        self.skill_manager = skill_manager
        self.root_dir = root_dir or config.ROOT_DIR
        self.board = board
        self.parent_registry = parent_registry
        self.allow_task_creation = allow_task_creation
        self.agent_id = f"{role.id}-{uuid.uuid4().hex[:6]}"
        self.total_runs: int = 0
        self.last_result: Optional[str] = None

    async def run(
        self,
        task: str,
        context: str = "",
        task_id: Optional[str] = None,
    ) -> str:
        """Execute a task autonomously using real NexusAgent tools."""
        self.total_runs += 1

        # Fallback minimal mode if no memory/board supplied (unit tests / isolated calls)
        if self.memory is None or self.skill_manager is None or self.board is None:
            messages = [{"role": "system", "content": self.role.system_prompt}]
            user_text = f"Context:\n{context}\n\nTask:\n{task}" if context else task
            messages.append({"role": "user", "content": user_text})
            response = await self.llm.chat_completion(messages)
            if isinstance(response, dict):
                result = response.get("content") or ""
                if not result and "choices" in response:
                    result = response.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            else:
                result = str(response)
            self.last_result = result.strip() or "No output."
            return self.last_result

        board = self.board
        role_id = self.role.id
        loop = asyncio.get_running_loop()

        def _schedule(coro):
            try:
                loop.create_task(coro)
            except Exception:
                pass

        def on_tool_call(tool_name: str, args: Dict[str, Any]):
            summary = _summarize_args(args)
            _schedule(board.set_agent_state(
                role_id,
                "tool",
                current_tool=f"{tool_name}({summary[:45]})",
                increment_tool=True,
            ))
            _schedule(board.record_tool_start(
                agent_id=role_id,
                role_name=self.role.name,
                tool_name=tool_name,
                args_summary=summary,
            ))

        def on_tool_result(tool_name: str, result_str: str, elapsed: float):
            is_err = str(result_str).startswith(("Error", "Security Guard"))
            _schedule(board.record_tool_end(
                agent_id=role_id,
                tool_name=tool_name,
                result_preview=str(result_str),
                elapsed=elapsed,
                is_error=is_err,
            ))
            _schedule(board.set_agent_state(role_id, "thinking"))

        scoped_registry = build_team_agent_registry(
            board=board,
            agent_id=role_id,
            root_dir=self.root_dir,
            toolsets=self.role.toolsets,
            memory=self.memory,
            skill_manager=self.skill_manager,
            parent_registry=self.parent_registry,
            read_only_fs=self.role.read_only_fs,
            allow_task_creation=self.allow_task_creation,
        )

        session_id = f"team-{board.id}-{role_id}-{uuid.uuid4().hex[:4]}"
        agent = NexusAgent(
            llm_client=self.llm,
            memory=self.memory,
            skill_manager=self.skill_manager,
            registry=scoped_registry,
            soul_path=config.SOUL_PATH,
            max_steps=self.role.max_steps,
            session_id=session_id,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )

        # Scope the agent's system prompt cleanly around its role & team context
        orig_prompt_fn = agent.build_system_prompt
        role_banner = (
            f"# AI-Team Member: {self.role.name} (@{self.role.id})\n"
            f"Mission ID: {board.id}\n"
            f"Overall Mission: {board.goal}\n"
            f"Workspace Directory: {self.root_dir}\n\n"
            f"## Your Role\n{self.role.system_prompt}\n\n"
            "## AI-Team Operating Rules\n"
            "- Act directly in the workspace using your real tools (`list_dir`, `read_file`, `write_file`, `patch_file`, `run_command`, `web_search`, etc.).\n"
            "- NEVER ask the user clarifying questions like a passive chatbot when you have an assigned team task — inspect the workspace, make sensible engineering choices, execute with tools, and report concrete results.\n"
            "- Check `team_read_board` / `team_read_messages` if you need context from teammates.\n"
            "- Use `team_send_message` to share important handoff notes (files written, endpoints, test findings) with `'all'` or specific teammates.\n"
            + (
                f"- When you finish task `{task_id}`, call `team_update_task(task_id='{task_id}', status='completed', result=...)` with a factual summary.\n"
                if task_id
                else ""
            )
        )
        agent.build_system_prompt = lambda: role_banner + "\n\n" + orig_prompt_fn()

        prompt_parts = [f"Assigned Task{f' [{task_id}]' if task_id else ''}:\n{task}"]
        if context:
            prompt_parts.append(f"Team Context & Recent Messages:\n{context}")
        full_prompt = "\n\n".join(prompt_parts)

        await board.set_agent_state(role_id, "thinking", current_task=task[:90])
        try:
            result = await agent.run(full_prompt)
            final_text = (result or "").strip() or "(Completed with tool actions)"
            self.last_result = final_text
            await board.set_agent_state(role_id, "done", output=final_text)
            return final_text
        except asyncio.CancelledError:
            await board.set_agent_state(role_id, "cancelled")
            raise
        except Exception as exc:
            err = f"Error in {self.role.name}: {exc}"
            self.last_result = err
            await board.set_agent_state(role_id, "error", output=err)
            logger.error("[Team:%s] Error: %s", role_id, exc)
            return err

    def __repr__(self) -> str:
        return f"<TeamAgent role={self.role.id} runs={self.total_runs}>"
