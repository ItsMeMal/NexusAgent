"""
nexus/team/manager.py
TeamManager — orchestrates a squad of TeamAgents.

Supports:
  - Sequential pipeline   : agents run one after another, each gets previous output as context
  - Parallel fan-out      : all agents run simultaneously on the same task, results merged
  - Single agent dispatch : run one specific role
  - Custom team config    : define a named team with a list of roles in order

Teams are ephemeral — no persistent state between /team run calls (but results are shown and
can be saved to memory via /team save).
"""

from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .agent import TeamAgent, AgentRole, BUILTIN_ROLES, BUILTIN_ROLES_BY_ID

logger = logging.getLogger(__name__)


@dataclass
class TeamRun:
    """Result of a full team execution."""
    task: str
    mode: str                          # "pipeline" | "parallel" | "single"
    roles_used: List[str]
    results: Dict[str, str] = field(default_factory=dict)   # role_id → output
    elapsed_s: float = 0.0
    error: Optional[str] = None

    def summary(self) -> str:
        """Return a compact multi-section summary string for display."""
        lines = [
            f"{'='*60}",
            f"🏁 AI-Team Run  [{self.mode.upper()}]  ({self.elapsed_s:.1f}s)",
            f"📋 Task: {self.task[:120]}{'...' if len(self.task)>120 else ''}",
            f"{'='*60}",
        ]
        for role_id, output in self.results.items():
            role = BUILTIN_ROLES_BY_ID.get(role_id)
            emoji = role.emoji if role else "🤖"
            name = role.name if role else role_id
            lines.append(f"\n{emoji} **{name}**")
            lines.append("-" * 40)
            lines.append(output.strip())
        return "\n".join(lines)


# Named preset teams
PRESET_TEAMS: Dict[str, List[str]] = {
    "dev":      ["planner", "coder", "reviewer", "tester"],
    "fulldev":  ["planner", "coder", "reviewer", "tester", "writer", "devops"],
    "audit":    ["security", "reviewer"],
    "docs":     ["writer"],
    "analysis": ["analyst"],
    "review":   ["reviewer", "security"],
}

# Presets that benefit from sequential context passing (pipeline)
# Everything else defaults to parallel
PIPELINE_PRESETS = {"dev", "fulldev"}

def auto_mode(preset: str, custom_roles: list) -> str:
    """
    Auto-detect best execution mode:
    - Pipeline: roles where each step builds on the previous (plan → code → review → test)
    - Parallel: roles that are independent analyzers (review + security + docs at same time)
    """
    if preset in PIPELINE_PRESETS:
        return "pipeline"
    if custom_roles:
        # If roles include planner/coder they need sequential context
        sequential_roles = {"planner", "coder", "tester", "devops", "writer"}
        if any(r in sequential_roles for r in custom_roles):
            return "pipeline"
    return "parallel"


class TeamManager:
    """
    Manages AI-Team configurations and runs.

    Usage:
        manager = TeamManager(llm_client)
        run = await manager.run_pipeline("Write a FastAPI endpoint for user login", roles=["planner","coder","tester"])
        print(run.summary())
    """

    def __init__(self, llm_client) -> None:
        self.llm = llm_client
        self._last_run: Optional[TeamRun] = None

    # ------------------------------------------------------------------
    # Core execution modes
    # ------------------------------------------------------------------

    async def run_pipeline(
        self,
        task: str,
        roles: List[str],
        progress_cb=None,   # optional async callable(role_id, result)
    ) -> TeamRun:
        """
        Run agents sequentially — each agent receives the previous agent's output as context.
        Best for: code generation workflows (plan → code → review → test).
        """
        start = time.monotonic()
        run = TeamRun(task=task, mode="pipeline", roles_used=roles)

        context = ""
        for role_id in roles:
            role = BUILTIN_ROLES_BY_ID.get(role_id)
            if not role:
                run.results[role_id] = f"⚠️ Unknown role: `{role_id}`"
                continue

            agent = TeamAgent(role=role, llm_client=self.llm)
            logger.info("[Team] Pipeline step: %s", role_id)
            result = await agent.run(task=task, context=context)
            run.results[role_id] = result
            # Pass this output to the next agent as context
            context = f"[{role.name}]:\n{result}"

            if progress_cb:
                try:
                    await progress_cb(role_id, result)
                except Exception:
                    pass

        run.elapsed_s = time.monotonic() - start
        self._last_run = run
        return run

    async def run_parallel(
        self,
        task: str,
        roles: List[str],
        progress_cb=None,
    ) -> TeamRun:
        """
        Run all agents simultaneously on the same task.
        Best for: multi-angle analysis (review + security + docs at once).
        """
        start = time.monotonic()
        run = TeamRun(task=task, mode="parallel", roles_used=roles)

        async def _run_one(role_id: str):
            role = BUILTIN_ROLES_BY_ID.get(role_id)
            if not role:
                return role_id, f"⚠️ Unknown role: `{role_id}`"
            agent = TeamAgent(role=role, llm_client=self.llm)
            result = await agent.run(task=task)
            if progress_cb:
                try:
                    await progress_cb(role_id, result)
                except Exception:
                    pass
            return role_id, result

        results = await asyncio.gather(*[_run_one(r) for r in roles], return_exceptions=False)
        for role_id, result in results:
            run.results[role_id] = result

        run.elapsed_s = time.monotonic() - start
        self._last_run = run
        return run

    async def run_single(self, task: str, role_id: str) -> TeamRun:
        """Run a single agent role for a task."""
        start = time.monotonic()
        run = TeamRun(task=task, mode="single", roles_used=[role_id])
        role = BUILTIN_ROLES_BY_ID.get(role_id)
        if not role:
            run.error = f"Unknown role: `{role_id}`"
            run.elapsed_s = time.monotonic() - start
            return run
        agent = TeamAgent(role=role, llm_client=self.llm)
        result = await agent.run(task=task)
        run.results[role_id] = result
        run.elapsed_s = time.monotonic() - start
        self._last_run = run
        return run

    # ------------------------------------------------------------------
    # Preset helpers
    # ------------------------------------------------------------------

    async def run_preset(
        self,
        task: str,
        preset: str,
        mode: str = "pipeline",
        progress_cb=None,
    ) -> TeamRun:
        """Run a named preset team (dev, fulldev, audit, docs, analysis, review)."""
        roles = PRESET_TEAMS.get(preset.lower())
        if not roles:
            run = TeamRun(task=task, mode=mode, roles_used=[])
            run.error = f"Unknown preset: `{preset}`. Available: {', '.join(PRESET_TEAMS)}"
            return run
        if mode == "parallel":
            return await self.run_parallel(task, roles, progress_cb)
        return await self.run_pipeline(task, roles, progress_cb)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    @staticmethod
    def list_roles() -> List[AgentRole]:
        return BUILTIN_ROLES

    @staticmethod
    def list_presets() -> Dict[str, List[str]]:
        return PRESET_TEAMS

    @property
    def last_run(self) -> Optional[TeamRun]:
        return self._last_run
