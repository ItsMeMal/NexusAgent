"""
nexus/team/team_tools.py
Builds role-scoped ToolRegistry instances for Team Lead and Team Agents.

Combines real Nexus workspace tools (filesystem, terminal, web, memory, skills, MCP)
with live AI-Team coordination tools (Shared Task Board, Mailbox, Fix Requests).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..tools.base import Tool, ToolRegistry
from ..tools.filesystem import get_filesystem_tools
from ..tools.terminal import get_terminal_tools
from ..tools.web import get_web_tools
from ..tools.memory_tools import get_memory_tools
from ..tools.skill_tools import get_skill_tools
from .board import TeamBoard


def _wrap_file_tracker(tool: Tool, board: TeamBoard, agent_id: str) -> Tool:
    """Wrap write_file / patch_file so successful edits automatically register on TeamBoard."""
    orig_handler = tool.handler

    async def tracked_handler(**kwargs) -> Any:
        if asyncio.iscoroutinefunction(orig_handler):
            res = await orig_handler(**kwargs)
        else:
            res = orig_handler(**kwargs)

        res_str = str(res)
        path = kwargs.get("path", "")
        if path and res_str.startswith("Successfully"):
            action = "written" if tool.name == "write_file" else "patched"
            await board.record_file(path=path, action=action, agent_id=agent_id)
        return res

    return Tool(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
        handler=tracked_handler,
    )


def get_team_collaboration_tools(
    board: TeamBoard,
    agent_id: str,
    allow_task_creation: bool = True,
) -> List[Tool]:
    """Create shared Task Board and Mailbox tools bound to a specific agent."""

    async def team_read_board() -> str:
        """Inspect all tasks on the shared AI-Team board and touched files."""
        lines = [f"Mission: {board.goal}", f"Status: {board.status}", ""]
        if not board.tasks:
            lines.append("Tasks: (none yet)")
        else:
            lines.append("Tasks:")
            for t in board.tasks:
                deps = f" (depends_on: {', '.join(t.depends_on)})" if t.depends_on else ""
                lines.append(f"- [{t.id}] ({t.status}) @{t.assigned_to}: {t.title}{deps}")
                if t.result:
                    lines.append(f"    Result: {t.result[:240]}")
        if board.files_touched:
            lines.append("\nFiles touched:")
            for f in board.files_touched:
                lines.append(f"- {f['path']} ({f['action']} by {f['by']})")
        return "\n".join(lines)

    async def team_update_task(task_id: str, status: str, result: str = "") -> str:
        """Update a task status on the shared board (completed | failed | blocked | in_progress)."""
        allowed = {"pending", "in_progress", "completed", "failed", "blocked"}
        norm_status = (status or "").strip().lower()
        if norm_status not in allowed:
            return f"Invalid status '{status}'. Must be one of: {', '.join(sorted(allowed))}."
        updated = await board.update_task(task_id=task_id.strip(), status=norm_status, result=result)
        if not updated:
            return f"Task '{task_id}' not found."
        return f"Updated {updated.id} -> {updated.status}"

    async def team_send_message(recipient: str, content: str, kind: str = "handoff") -> str:
        """Send a message to 'all', 'lead', or a teammate role ID (e.g. 'coder', 'reviewer')."""
        if not content or not content.strip():
            return "Error: message content cannot be empty."
        msg = await board.post_message(
            sender=agent_id,
            recipient=(recipient or "all").strip().lower(),
            content=content,
            kind=kind or "chat",
        )
        return f"Message sent to {msg.recipient} at {msg.timestamp}."

    async def team_read_messages(limit: int = 20) -> str:
        """Read recent messages addressed to you or broadcast to 'all'."""
        msgs = board.get_messages(for_agent=agent_id, limit=limit)
        if not msgs:
            return "No team messages yet."
        return "\n".join(
            f"[{m.timestamp}] {m.sender} -> {m.recipient} ({m.kind}): {m.content}"
            for m in msgs
        )

    async def team_request_fix(target_role: str, issue: str, file_path: str = "") -> str:
        """Create a follow-up fix task for another teammate when a bug or issue is found."""
        target = (target_role or "coder").strip().lower()
        desc = issue.strip()
        if file_path:
            desc = f"Target file: {file_path}\nIssue:\n{desc}"
        task = await board.create_task(
            title=f"Fix: {issue.strip()[:60]}",
            description=desc,
            assigned_to=target,
            depends_on=[],
            created_by=agent_id,
        )
        await board.post_message(
            sender=agent_id,
            recipient=target,
            content=f"Created {task.id} requesting fix: {desc}",
            kind="feedback",
        )
        return f"Created follow-up fix task {task.id} assigned to @{target}."

    tools = [
        Tool(
            name="team_read_board",
            description="Read all tasks, assignees, dependencies, statuses, and touched files on the Shared Team Board.",
            parameters={"type": "object", "properties": {}},
            handler=team_read_board,
        ),
        Tool(
            name="team_update_task",
            description="Update your assigned task status on the Shared Team Board with a concise summary of what you built/verified.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID such as T1"},
                    "status": {"type": "string", "description": "One of: completed, failed, blocked, in_progress"},
                    "result": {"type": "string", "description": "Concise summary of actions taken and results"},
                },
                "required": ["task_id", "status"],
            },
            handler=team_update_task,
        ),
        Tool(
            name="team_send_message",
            description="Send a message or handoff note to 'all', 'lead', or a specific teammate role ID.",
            parameters={
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "Target: 'all', 'lead', or role id ('coder', 'reviewer', 'tester', etc.)"},
                    "content": {"type": "string", "description": "Message content"},
                    "kind": {"type": "string", "description": "handoff | feedback | status | chat", "default": "handoff"},
                },
                "required": ["recipient", "content"],
            },
            handler=team_send_message,
        ),
        Tool(
            name="team_read_messages",
            description="Read recent messages from the Team Lead and teammates.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
            handler=team_read_messages,
        ),
        Tool(
            name="team_request_fix",
            description="Request another teammate (e.g. 'coder') to fix a verified bug or gap by creating a new fix task on the board.",
            parameters={
                "type": "object",
                "properties": {
                    "target_role": {"type": "string", "description": "Role ID responsible for fixing (e.g. 'coder', 'devops')"},
                    "issue": {"type": "string", "description": "Exact issue found and how to fix it"},
                    "file_path": {"type": "string", "description": "Relevant file path if applicable", "default": ""},
                },
                "required": ["target_role", "issue"],
            },
            handler=team_request_fix,
        ),
    ]

    if allow_task_creation:
        async def team_create_task(
            title: str,
            description: str,
            assigned_to: str,
            depends_on: Optional[List[str]] = None,
        ) -> str:
            """Create a new task on the Shared Team Board assigned to a specific teammate role."""
            task = await board.create_task(
                title=title,
                description=description,
                assigned_to=assigned_to,
                depends_on=depends_on or [],
                created_by=agent_id,
            )
            return f"Created task {task.id} assigned to @{task.assigned_to}: {task.title}"

        tools.append(
            Tool(
                name="team_create_task",
                description=(
                    "Create a concrete task on the Shared Team Board and assign it to a teammate role ID. "
                    "Use depends_on=['T1'] when a task depends on an earlier task's outputs/files; omit depends_on so independent tasks run in parallel."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short task title"},
                        "description": {"type": "string", "description": "Clear actionable instructions & target files"},
                        "assigned_to": {"type": "string", "description": "Role ID from the active team roster"},
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of prerequisite task IDs (e.g. ['T1'])",
                        },
                    },
                    "required": ["title", "description", "assigned_to"],
                },
                handler=team_create_task,
            )
        )

    return tools


def build_team_agent_registry(
    board: TeamBoard,
    agent_id: str,
    root_dir: Path,
    toolsets: List[str],
    memory=None,
    skill_manager=None,
    parent_registry: Optional[ToolRegistry] = None,
    read_only_fs: bool = False,
    allow_task_creation: bool = False,
) -> ToolRegistry:
    """Build a complete ToolRegistry for a Team Lead or Specialist Teammate."""
    registry = ToolRegistry()

    fs_tools = get_filesystem_tools(root_dir)
    if "filesystem" in toolsets:
        for t in fs_tools:
            if read_only_fs and t.name in ("write_file", "patch_file"):
                continue
            if t.name in ("write_file", "patch_file"):
                registry.register(_wrap_file_tracker(t, board, agent_id))
            else:
                registry.register(t)

    if "terminal" in toolsets:
        for t in get_terminal_tools(root_dir):
            registry.register(t)

    if "web" in toolsets:
        for t in get_web_tools():
            registry.register(t)

    if "memory" in toolsets and memory is not None:
        for t in get_memory_tools(memory):
            registry.register(t)

    if "skills" in toolsets and skill_manager is not None:
        for t in get_skill_tools(skill_manager):
            registry.register(t)

    # Forward active MCP tools from parent registry if available
    if parent_registry is not None:
        for t in parent_registry.get_all():
            if t.name.startswith("mcp_") and registry.get(t.name) is None:
                registry.register(t)

    # Inject shared team coordination tools
    for t in get_team_collaboration_tools(
        board=board,
        agent_id=agent_id,
        allow_task_creation=allow_task_creation,
    ):
        registry.register(t)

    return registry
