"""
nexus/team/manager.py
TeamManager — Real Autonomous AI-Team Orchestrator.

Instead of sequential text-only LLM calls ("pipeline"), orchestrates real
tool-using NexusAgent specialists around a Shared Task Board & Team Mailbox:
  1. Team Lead inspects workspace & creates concrete tasks with dependencies
  2. Wave Scheduler executes independent tasks in parallel & dependent tasks in order
  3. Reviewers / QA Testers inspect real files, run tests, and can request fixes
  4. Team Lead synthesizes verified results and touched files
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..config import config
from .agent import BUILTIN_ROLES, BUILTIN_ROLES_BY_ID, LEAD_ROLE, AgentRole, TeamAgent
from .board import TeamBoard, TeamTask

logger = logging.getLogger(__name__)


@dataclass
class TeamRun:
    """Result of a full AI-Team mission."""
    task: str
    mode: str                          # "team" | "parallel" | "sequential" | "single"
    roles_used: List[str]
    results: Dict[str, str] = field(default_factory=dict)
    elapsed_s: float = 0.0
    error: Optional[str] = None
    board: Optional[TeamBoard] = None

    def summary(self) -> str:
        """Return a structured summary string for CLI / messaging gateways."""
        if self.board and self.board.summary:
            lines = [
                f"👥 AI-Team [{self.mode}] · {self.elapsed_s:.1f}s",
                f"📋 Mission: {self.task}",
                "",
                self.board.summary.strip(),
            ]
            if self.board.files_touched:
                lines.append("\n📁 Files touched:")
                for f in self.board.files_touched:
                    lines.append(f"  • {f['path']} ({f['action']} by {f['by']})")
            return "\n".join(lines)

        lines = [
            f"👥 AI-Team [{self.mode}] · {self.elapsed_s:.1f}s",
            f"📋 Mission: {self.task}",
        ]
        for role_id, output in self.results.items():
            role = BUILTIN_ROLES_BY_ID.get(role_id)
            emoji = role.emoji if role else "🤖"
            name = role.name if role else role_id
            lines.append(f"\n{emoji} **{name}**\n{output.strip()}")
        return "\n".join(lines)


# Named preset squads
PRESET_TEAMS: Dict[str, List[str]] = {
    "dev":      ["planner", "coder", "reviewer", "tester"],
    "fulldev":  ["planner", "coder", "reviewer", "tester", "writer", "devops"],
    "audit":    ["security", "reviewer"],
    "docs":     ["writer"],
    "analysis": ["analyst"],
    "review":   ["reviewer", "security"],
}


def auto_mode(preset: str, custom_roles: List[str]) -> str:
    """
    Pick the best coordination strategy:
    - "parallel" when only independent read/audit/analysis roles run without build/plan steps
    - "team" (Lead-coordinated task graph with parallel waves where possible) for everything else
    """
    if preset in {"audit", "review", "analysis", "docs"} and not custom_roles:
        return "parallel"
    if custom_roles and not any(r in {"planner", "coder", "tester", "devops", "writer"} for r in custom_roles):
        return "parallel"
    return "team"


class TeamManager:
    """Coordinates an autonomous AI-Team using shared TeamBoard and real NexusAgent tools."""

    def __init__(
        self,
        llm_client,
        memory=None,
        skill_manager=None,
        root_dir: Optional[Path] = None,
        parent_registry=None,
    ) -> None:
        self.llm = llm_client
        self.memory = memory
        self.skill_manager = skill_manager
        self.root_dir = root_dir or config.ROOT_DIR
        self.parent_registry = parent_registry
        self._last_run: Optional[TeamRun] = None

    def _build_board(
        self,
        goal: str,
        preset: str,
        mode: str,
        roles: List[str],
        include_lead: bool = True,
    ) -> TeamBoard:
        run_id = uuid.uuid4().hex[:8]
        board = TeamBoard(
            run_id=run_id,
            goal=goal,
            preset=preset,
            mode=mode,
            roles=roles,
            workspace_dir=str(self.root_dir),
        )
        if include_lead:
            board.init_agent(
                LEAD_ROLE.id,
                LEAD_ROLE.name,
                LEAD_ROLE.description,
                is_lead=True,
            )
        for rid in roles:
            role = BUILTIN_ROLES_BY_ID.get(rid)
            board.init_agent(
                rid,
                role.name if role else rid,
                role.description if role else "",
                is_lead=False,
            )
        return board

    def _make_agent(self, role: AgentRole, board: TeamBoard, allow_task_creation: bool = False) -> TeamAgent:
        return TeamAgent(
            role=role,
            llm_client=self.llm,
            memory=self.memory,
            skill_manager=self.skill_manager,
            root_dir=self.root_dir,
            board=board,
            parent_registry=self.parent_registry,
            allow_task_creation=allow_task_creation,
        )

    def _format_context_for_task(self, board: TeamBoard, task: TeamTask) -> str:
        lines: List[str] = []
        if task.depends_on:
            lines.append("### Prerequisite Task Results:")
            for dep_id in task.depends_on:
                dep = next((t for t in board.tasks if t.id == dep_id), None)
                if dep:
                    lines.append(f"- [{dep.id}] {dep.title} (@{dep.assigned_to}):\n  {dep.result[:600]}")

        recent_msgs = board.get_messages(for_agent=task.assigned_to, limit=12)
        if recent_msgs:
            lines.append("\n### Recent Team Messages:")
            for m in recent_msgs:
                lines.append(f"- [{m.timestamp}] {m.sender} -> {m.recipient}: {m.content[:350]}")

        if board.files_touched:
            lines.append("\n### Files Already Created/Modified in Workspace:")
            for f in board.files_touched:
                lines.append(f"- {f['path']} ({f['action']} by @{f['by']})")

        return "\n".join(lines)

    async def _populate_fallback_tasks(self, board: TeamBoard, goal: str, roles: List[str], sequential: bool = False) -> None:
        """Create sensible tasks on the board if Lead did not emit tasks directly or mode is explicit."""
        if sequential:
            prev_id: Optional[str] = None
            for rid in roles:
                role = BUILTIN_ROLES_BY_ID.get(rid)
                t = await board.create_task(
                    title=f"{role.name if role else rid}: execute mission step",
                    description=f"Handle your specialist responsibilities for the mission: {goal}",
                    assigned_to=rid,
                    depends_on=[prev_id] if prev_id else [],
                    created_by="lead",
                )
                prev_id = t.id
            return

        if board.mode == "parallel":
            for rid in roles:
                role = BUILTIN_ROLES_BY_ID.get(rid)
                await board.create_task(
                    title=f"{role.name if role else rid}: specialist execution",
                    description=f"Independently execute your role for: {goal}",
                    assigned_to=rid,
                    depends_on=[],
                    created_by="lead",
                )
            return

        # Smart default task graph: planner -> build roles (coder/devops/writer) -> verification roles (reviewer/tester/security/analyst)
        plan_ids: List[str] = []
        build_ids: List[str] = []

        if "planner" in roles:
            t = await board.create_task(
                title="Inspect workspace & design implementation plan",
                description=f"Inspect existing workspace files and produce a concrete architecture & file list for: {goal}",
                assigned_to="planner",
                depends_on=[],
                created_by="lead",
            )
            plan_ids.append(t.id)

        for rid in roles:
            if rid in ("coder", "devops", "writer", "analyst"):
                role = BUILTIN_ROLES_BY_ID.get(rid)
                t = await board.create_task(
                    title=f"{role.name if role else rid}: implement deliverables",
                    description=f"Build and write the concrete deliverables in the workspace for: {goal}",
                    assigned_to=rid,
                    depends_on=list(plan_ids),
                    created_by="lead",
                )
                build_ids.append(t.id)

        verify_deps = build_ids if build_ids else plan_ids
        for rid in roles:
            if rid in ("reviewer", "tester", "security"):
                role = BUILTIN_ROLES_BY_ID.get(rid)
                await board.create_task(
                    title=f"{role.name if role else rid}: inspect & verify deliverables",
                    description=f"Inspect the actual files in the workspace, run verification checks/tests if applicable, and report concrete findings for: {goal}",
                    assigned_to=rid,
                    depends_on=list(verify_deps),
                    created_by="lead",
                )

    async def _run_wave_loop(
        self,
        board: TeamBoard,
        roles: List[str],
        results: Dict[str, str],
        max_waves: int = 10,
    ) -> None:
        """Execute ready tasks wave-by-wave until all tasks are resolved."""
        stall_count = 0
        for _ in range(max_waves):
            ready = board.get_ready_tasks()
            if not ready:
                if board.has_open_tasks():
                    # Deadlock: pending tasks but none ready → unblock by clearing deps on the first pending task
                    unblocked = await board.unblock_stalled_tasks()
                    if unblocked:
                        stall_count += 1
                        if stall_count <= 3:
                            continue  # retry with cleared deps
                break

            stall_count = 0  # reset on successful wave

            async def _execute_task(t: TeamTask):
                target_role_id = t.assigned_to if t.assigned_to in BUILTIN_ROLES_BY_ID else (roles[0] if roles else "coder")
                role = BUILTIN_ROLES_BY_ID.get(target_role_id, BUILTIN_ROLES[1])
                await board.update_task(t.id, status="in_progress")
                ctx = self._format_context_for_task(board, t)
                # Allow reviewer/tester/coder to report bugs or follow-ups, capped against runaway creation
                can_create = len(board.tasks) < 14
                agent = self._make_agent(role, board, allow_task_creation=can_create)
                out = await agent.run(task=t.description, context=ctx, task_id=t.id)
                results[target_role_id] = out
                # Ensure task status transitions out of in_progress even if model didn't call team_update_task
                current_status = next((tk.status for tk in board.tasks if tk.id == t.id), "in_progress")
                if current_status == "in_progress":
                    final_status = "failed" if out.startswith("Error in ") else "completed"
                    await board.update_task(t.id, status=final_status, result=out[:1200])

            await asyncio.gather(*[_execute_task(t) for t in ready])

    async def run_team(
        self,
        task: str,
        roles: Optional[List[str]] = None,
        preset: str = "dev",
        mode: Optional[str] = None,
        board: Optional[TeamBoard] = None,
        progress_cb: Optional[Callable[[str, str], Any]] = None,
    ) -> TeamRun:
        """
        Execute a full AI-Team mission with a Shared Task Board, Team Mailbox, and real tools.
        """
        selected_roles = list(roles) if roles else list(PRESET_TEAMS.get(preset, PRESET_TEAMS["dev"]))
        resolved_mode = mode or auto_mode(preset, selected_roles if roles else [])
        # Normalize legacy "pipeline" flag into "sequential"
        if resolved_mode == "pipeline":
            resolved_mode = "sequential"

        if board is None:
            board = self._build_board(
                goal=task,
                preset=preset,
                mode=resolved_mode,
                roles=selected_roles,
                include_lead=(resolved_mode == "team"),
            )

        start = time.monotonic()
        results: Dict[str, str] = {}

        # Optional legacy progress bridge
        if progress_cb:
            async def _bridge(ev_type: str, payload: Dict[str, Any]):
                if ev_type == "agent_update":
                    ag = payload.get("agent", {})
                    if ag.get("state") == "done" and payload.get("role_id") != "lead":
                        res = progress_cb(payload["role_id"], ag.get("output", ""))
                        if asyncio.iscoroutine(res):
                            await res
            board.subscribe(_bridge)

        try:
            await board.post_message("user", "lead", task, kind="user")

            # Phase 1: Planning / Task Graph
            if resolved_mode == "team" and self.memory is not None and self.skill_manager is not None:
                board.status = "planning"
                await board.emit("board_update", {"run_id": board.id, "tasks": [t.to_dict() for t in board.tasks]})
                lead_agent = self._make_agent(LEAD_ROLE, board, allow_task_creation=True)
                roster_desc = ", ".join(
                    f"@{r} ({BUILTIN_ROLES_BY_ID[r].name})" for r in selected_roles if r in BUILTIN_ROLES_BY_ID
                )
                # Snapshot the workspace root so Lead doesn't waste tool budget
                try:
                    from ..tools.filesystem import get_filesystem_tools
                    fs_tools = get_filesystem_tools(self.root_dir)
                    list_dir_tool = next((t for t in fs_tools if t.name == "list_dir"), None)
                    if list_dir_tool:
                        import asyncio as _asyncio
                        ws_snapshot = await list_dir_tool.handler(path=".")
                        ws_snapshot = str(ws_snapshot)[:600]
                    else:
                        ws_snapshot = f"Workspace root: {self.root_dir}"
                except Exception:
                    ws_snapshot = f"Workspace root: {self.root_dir}"

                lead_prompt = (
                    f"User Mission: {task}\n\n"
                    f"Available Team Roster: {roster_desc}\n\n"
                    f"Workspace Snapshot:\n{ws_snapshot}\n\n"
                    "Plan this mission for the AI-Team by creating tasks on the Shared Task Board.\n\n"
                    "RULES (follow exactly):\n"
                    "1. Call `team_create_task` for each task. Example:\n"
                    "   team_create_task(title='Scaffold HTML structure', description='Create index.html with nav, hero, about, contact sections', assigned_to='coder', depends_on=[])\n"
                    "2. `depends_on` must contain ONLY exact task IDs like ['T1'] or ['T1','T2'].\n"
                    "   NEVER put the task title or description in depends_on. NEVER put a role name.\n"
                    "   Tasks that don't need prior output: depends_on=[]\n"
                    "   Tasks that need T1's files: depends_on=['T1']\n"
                    "3. Create 3-5 tasks total. Keep descriptions concrete and actionable.\n"
                    "4. After creating tasks, post a kickoff via team_send_message(recipient='all', content='...', kind='handoff').\n"
                    "5. Do NOT ask the user questions. Make sensible decisions and create the tasks NOW."
                )
                await lead_agent.run(lead_prompt)

            if not board.tasks:
                await self._populate_fallback_tasks(
                    board,
                    goal=task,
                    roles=selected_roles,
                    sequential=(resolved_mode == "sequential"),
                )

            # Phase 2: Wave Execution
            board.status = "executing"
            await board.emit("board_update", {"run_id": board.id, "tasks": [t.to_dict() for t in board.tasks]})
            await self._run_wave_loop(board, selected_roles, results)

            # Phase 3: Lead Final Synthesis
            if resolved_mode == "team" and self.memory is not None and self.skill_manager is not None:
                board.status = "reviewing"
                lead_agent = self._make_agent(LEAD_ROLE, board, allow_task_creation=False)
                synth_prompt = (
                    f"All team tasks for mission '{task}' have finished.\n"
                    "Call `team_read_board` and `team_read_messages`, then produce a concise, factual final report "
                    "listing what the team actually built, which files were created/modified, and any test/verification outputs."
                )
                summary = await lead_agent.run(synth_prompt)
                # Fallback: build summary from task results if Lead returned empty
                if not summary or summary.strip() in ("", "No output.", f"{LEAD_ROLE.name} completed assigned actions."):
                    completed = [t for t in board.tasks if t.status == "completed"]
                    if completed:
                        lines = [f"Mission: {task}\n"]
                        for t in completed:
                            lines.append(f"✓ [{t.id}] {t.title} (@{t.assigned_to})")
                            if t.result:
                                lines.append(f"  → {t.result[:300]}")
                        if board.files_touched:
                            lines.append("\nFiles created/modified:")
                            for f in board.files_touched:
                                lines.append(f"  • {f['path']} ({f['action']} by @{f['by']})")
                        summary = "\n".join(lines)
                    else:
                        summary = f"Mission '{task}' completed. {len(board.tasks)} tasks processed."
                board.summary = summary
                await board.post_message("lead", "all", summary, kind="status")
            else:
                board.summary = "\n\n".join(
                    f"### {BUILTIN_ROLES_BY_ID[r].name if r in BUILTIN_ROLES_BY_ID else r}\n{txt}"
                    for r, txt in results.items()
                )

            board.status = "completed"
            board.done = True
            board.total_elapsed = round(time.monotonic() - start, 1)
            await board.emit("run_done", {"run": board.to_dict()})

            run = TeamRun(
                task=task,
                mode=resolved_mode,
                roles_used=selected_roles,
                results=results,
                elapsed_s=board.total_elapsed,
                board=board,
            )
            self._last_run = run
            return run

        except asyncio.CancelledError:
            board.status = "cancelled"
            board.done = True
            board.total_elapsed = round(time.monotonic() - start, 1)
            for t in board.tasks:
                if t.status in ("pending", "in_progress"):
                    await board.update_task(t.id, status="blocked", result="Cancelled by user")
            await board.post_message("lead", "all", "Team mission cancelled by user.", kind="status")
            await board.emit("run_done", {"run": board.to_dict()})
            raise

        except Exception as exc:
            board.status = "failed"
            board.error = str(exc)
            board.done = True
            board.total_elapsed = round(time.monotonic() - start, 1)
            await board.emit("error", {"msg": str(exc)})
            await board.emit("run_done", {"run": board.to_dict()})
            return TeamRun(
                task=task,
                mode=resolved_mode,
                roles_used=selected_roles,
                results=results,
                elapsed_s=board.total_elapsed,
                error=str(exc),
                board=board,
            )

    async def handle_followup(self, board: TeamBoard, prompt: str) -> TeamRun:
        """Steer or assign follow-up work to the team on an existing board/workspace."""
        text = prompt.strip()
        target_role: Optional[str] = None
        if text.startswith("@"):
            first, _, rest = text.partition(" ")
            candidate = first[1:].strip().lower()
            if candidate in BUILTIN_ROLES_BY_ID:
                target_role = candidate
                text = rest.strip() or text

        board.done = False
        board.status = "executing"
        await board.post_message("user", target_role or "lead", prompt, kind="user")

        if target_role:
            await board.create_task(
                title=f"Follow-up: {text[:60]}",
                description=text,
                assigned_to=target_role,
                depends_on=[],
                created_by="user",
            )
        elif self.memory is not None and self.skill_manager is not None:
            lead_agent = self._make_agent(LEAD_ROLE, board, allow_task_creation=True)
            await lead_agent.run(
                f"User follow-up request: {text}\n\n"
                "Inspect `team_read_board` and create follow-up task(s) via `team_create_task` assigned to the right teammate(s)."
            )
            if not board.get_ready_tasks():
                fallback_role = "coder" if "coder" in board.roles else board.roles[0]
                await board.create_task(
                    title=f"Follow-up: {text[:60]}",
                    description=text,
                    assigned_to=fallback_role,
                    depends_on=[],
                    created_by="user",
                )
        else:
            fallback_role = "coder" if "coder" in board.roles else board.roles[0]
            await board.create_task(
                title=f"Follow-up: {text[:60]}",
                description=text,
                assigned_to=fallback_role,
                depends_on=[],
                created_by="user",
            )

        results: Dict[str, str] = {}
        start = time.monotonic()
        await self._run_wave_loop(board, board.roles, results)
        board.status = "completed"
        board.done = True
        board.total_elapsed = round(time.monotonic() - board._start_mono, 1)
        summary = "\n\n".join(results.values()) or "Follow-up completed."
        board.summary = summary
        await board.post_message("lead", "all", summary, kind="status")
        await board.emit("run_done", {"run": board.to_dict()})

        run = TeamRun(
            task=text,
            mode=board.mode,
            roles_used=board.roles,
            results=results,
            elapsed_s=round(time.monotonic() - start, 1),
            board=board,
        )
        self._last_run = run
        return run

    # ------------------------------------------------------------------
    # Backwards-compatible methods (delegate to unified run_team engine)
    # ------------------------------------------------------------------

    async def run_pipeline(self, task: str, roles: List[str], progress_cb=None) -> TeamRun:
        return await self.run_team(task=task, roles=roles, mode="sequential", progress_cb=progress_cb)

    async def run_parallel(self, task: str, roles: List[str], progress_cb=None) -> TeamRun:
        return await self.run_team(task=task, roles=roles, mode="parallel", progress_cb=progress_cb)

    async def run_single(self, task: str, role_id: str) -> TeamRun:
        start = time.monotonic()
        board = self._build_board(goal=task, preset="single", mode="single", roles=[role_id], include_lead=False)
        role = BUILTIN_ROLES_BY_ID.get(role_id)
        if not role:
            return TeamRun(task=task, mode="single", roles_used=[role_id], error=f"Unknown role: `{role_id}`")
        agent = self._make_agent(role, board, allow_task_creation=False)
        result = await agent.run(task=task)
        elapsed = round(time.monotonic() - start, 1)
        run = TeamRun(task=task, mode="single", roles_used=[role_id], results={role_id: result}, elapsed_s=elapsed, board=board)
        self._last_run = run
        return run

    async def run_preset(self, task: str, preset: str, mode: Optional[str] = None, progress_cb=None) -> TeamRun:
        roles = PRESET_TEAMS.get(preset.lower())
        if not roles:
            return TeamRun(
                task=task,
                mode=mode or "team",
                roles_used=[],
                error=f"Unknown preset: `{preset}`. Available: {', '.join(PRESET_TEAMS)}",
            )
        return await self.run_team(task=task, roles=roles, preset=preset.lower(), mode=mode, progress_cb=progress_cb)

    @staticmethod
    def list_roles() -> List[AgentRole]:
        return BUILTIN_ROLES

    @staticmethod
    def list_presets() -> Dict[str, List[str]]:
        return PRESET_TEAMS

    @property
    def last_run(self) -> Optional[TeamRun]:
        return self._last_run
