"""
nexus/team/ui.py
Rich live TUI for AI-Team pipeline / parallel runs.

Displays a live-updating panel per agent:
  ┌──────────────────────────────────────────────┐
  │  👥 AI-Team Pipeline — "build a login API"   │
  ├──────────────────────────────────────────────┤
  │  🗺️  Planner       ✓ done   (2.1s)           │
  │  💻  Code Writer   ⠸ running...              │
  │  🔍  Reviewer      ░ waiting                 │
  │  🧪  QA Tester     ░ waiting                 │
  └──────────────────────────────────────────────┘

After each agent finishes, its output is printed below the panel.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.markdown import Markdown

from .agent import AgentRole, BUILTIN_ROLES_BY_ID
from .manager import TeamManager, TeamRun

console = Console()

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


@dataclass
class AgentStatus:
    role_id: str
    state: str = "waiting"   # waiting | running | done | error
    elapsed: float = 0.0
    started_at: float = 0.0
    result_snippet: str = ""


def _make_panel(
    task: str,
    statuses: List[AgentStatus],
    mode: str,
    total_elapsed: float,
    spinner_frame: int,
) -> Panel:
    """Build the live-updating Rich panel showing all agent statuses."""
    table = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    table.add_column("icon", width=3)
    table.add_column("name", min_width=16)
    table.add_column("status", min_width=12)
    table.add_column("time", justify="right", width=8)

    for s in statuses:
        role = BUILTIN_ROLES_BY_ID.get(s.role_id)
        emoji = role.emoji if role else "🤖"
        name = role.name if role else s.role_id

        if s.state == "waiting":
            status_txt = Text("░ waiting", style="dim")
            time_txt = Text("")
        elif s.state == "running":
            frame = SPINNER_FRAMES[spinner_frame % len(SPINNER_FRAMES)]
            status_txt = Text(f"{frame} running…", style="bold cyan")
            elapsed = time.monotonic() - s.started_at
            time_txt = Text(f"{elapsed:.1f}s", style="dim cyan")
        elif s.state == "done":
            status_txt = Text("✓ done", style="bold #22c55e")
            time_txt = Text(f"{s.elapsed:.1f}s", style="dim #22c55e")
        else:  # error
            status_txt = Text("✗ error", style="bold red")
            time_txt = Text(f"{s.elapsed:.1f}s", style="dim red")

        table.add_row(emoji, f"[bold]{name}[/bold]", status_txt, time_txt)

    mode_label = "→ sequential" if mode == "pipeline" else "⚡ parallel"
    task_short = task[:70] + ("…" if len(task) > 70 else "")

    title = f"[bold #00ffd7]👥 AI-Team[/bold #00ffd7]  [dim]{mode_label}[/dim]  ·  {total_elapsed:.1f}s"
    subtitle = f"[dim]📋 {task_short}[/dim]"

    return Panel(
        table,
        title=title,
        subtitle=subtitle,
        border_style="#334155",
        box=box.ROUNDED,
        padding=(0, 1),
    )


async def run_team_with_ui(
    task: str,
    roles: List[str],
    mode: str,
    llm_client,
) -> TeamRun:
    """
    Run an AI-Team with a live Rich TUI panel.
    Prints each agent's full output below the panel as they complete.
    Returns the final TeamRun.
    """
    statuses = [AgentStatus(role_id=r) for r in roles]
    status_map: Dict[str, AgentStatus] = {s.role_id: s for s in statuses}
    start_total = time.monotonic()
    spinner_frame = 0

    manager = TeamManager(llm_client)
    results_printed: List[str] = []
    pending_prints: asyncio.Queue = asyncio.Queue()

    async def on_progress(role_id: str, result: str):
        s = status_map.get(role_id)
        if s:
            s.state = "done"
            s.elapsed = time.monotonic() - (s.started_at or start_total)
        await pending_prints.put((role_id, result))

    async def run_agents():
        if mode == "parallel":
            # Mark all as running immediately
            for s in statuses:
                s.state = "running"
                s.started_at = time.monotonic()
            return await manager.run_parallel(task, roles, progress_cb=on_progress)
        else:
            # Pipeline — mark one at a time
            async def _pipeline_progress(role_id: str, result: str):
                # Find next role and mark it running
                idx = roles.index(role_id) if role_id in roles else -1
                if idx + 1 < len(roles):
                    next_s = status_map.get(roles[idx + 1])
                    if next_s and next_s.state == "waiting":
                        next_s.state = "running"
                        next_s.started_at = time.monotonic()
                await on_progress(role_id, result)

            # Mark first role as running
            if statuses:
                statuses[0].state = "running"
                statuses[0].started_at = time.monotonic()

            return await manager.run_pipeline(task, roles, progress_cb=_pipeline_progress)

    agent_task = asyncio.create_task(run_agents())

    with Live(
        _make_panel(task, statuses, mode, 0, 0),
        console=console,
        refresh_per_second=10,
        transient=False,
    ) as live:
        while not agent_task.done():
            spinner_frame += 1
            elapsed = time.monotonic() - start_total
            live.update(_make_panel(task, statuses, mode, elapsed, spinner_frame))

            # Drain pending prints (shown AFTER the live panel completes)
            while not pending_prints.empty():
                role_id, result = await pending_prints.get()
                results_printed.append((role_id, result))

            await asyncio.sleep(0.1)

        # Final panel update
        elapsed = time.monotonic() - start_total
        live.update(_make_panel(task, statuses, mode, elapsed, spinner_frame))

    # Drain any remaining
    while not pending_prints.empty():
        role_id, result = await pending_prints.get()
        results_printed.append((role_id, result))

    run = agent_task.result()

    # Print each agent result as a nicely-formatted section
    console.print()
    for role_id, result in results_printed:
        role = BUILTIN_ROLES_BY_ID.get(role_id)
        emoji = role.emoji if role else "🤖"
        name = role.name if role else role_id
        console.rule(f"{emoji} [bold #38bdf8]{name}[/bold #38bdf8]", style="#334155")
        console.print(Markdown(result))
        console.print()

    total = time.monotonic() - start_total
    console.print(
        f"  [bold #22c55e]✅ AI-Team done[/bold #22c55e]  "
        f"[dim]{len(roles)} agents · {mode} · {total:.1f}s[/dim]\n"
    )

    return run
