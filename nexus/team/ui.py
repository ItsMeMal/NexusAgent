"""
nexus/team/ui.py
Rich live Terminal TUI for AI-Team runs.

Subscribes directly to the single TeamBoard instance run by DashboardState
(so CLI and Web Dashboard reflect the EXACT same execution without running twice).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich import box
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import config
from .agent import BUILTIN_ROLES_BY_ID
from .board import TeamBoard
from .manager import TeamManager, TeamRun

console = Console()

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _render_board_panel(
    board: Optional[TeamBoard],
    task: str,
    roles: List[str],
    mode: str,
    total_elapsed: float,
    spinner_frame: int,
    dashboard_url: str = "",
) -> Panel:
    """Build a crisp live Rich Panel showing Roster + Shared Task Board + recent activity."""
    outer = Table.grid(expand=True, padding=(0, 0))
    outer.add_column()

    # 1. Roster Table
    roster_tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    roster_tbl.add_column("agent", min_width=16, no_wrap=True)
    roster_tbl.add_column("status", min_width=14, no_wrap=True)
    roster_tbl.add_column("activity", ratio=1)
    roster_tbl.add_column("tools", justify="right", width=9)
    roster_tbl.add_column("time", justify="right", width=7)

    frame = SPINNER_FRAMES[spinner_frame % len(SPINNER_FRAMES)]

    if board and board.agents:
        ordered_ids = sorted(board.agents.keys(), key=lambda x: (0 if x == "lead" else 1))
        for rid in ordered_ids:
            ag = board.agents[rid]
            name = ag.get("name", rid)
            st = ag.get("state", "waiting")
            tcount = ag.get("tool_count", 0)
            elapsed = ag.get("elapsed", 0.0)
            activity = ag.get("current_tool") or ag.get("current_task") or ("Coordinating" if rid == "lead" else "Standby")

            if st in ("thinking", "tool"):
                st_txt = Text(f"{frame} {st}", style="bold cyan")
            elif st == "done":
                st_txt = Text("✓ done", style="bold #22c55e")
            elif st in ("error", "cancelled"):
                st_txt = Text(f"✗ {st}", style="bold red")
            else:
                st_txt = Text("· waiting", style="dim")

            act_style = "cyan" if st == "tool" else "dim"
            roster_tbl.add_row(
                f"[bold]{name}[/bold]",
                st_txt,
                Text(str(activity)[:52], style=act_style),
                Text(f"{tcount} tools", style="dim"),
                Text(f"{elapsed:.1f}s" if elapsed else "", style="dim"),
            )
    else:
        for rid in roles:
            role = BUILTIN_ROLES_BY_ID.get(rid)
            roster_tbl.add_row(
                f"[bold]{role.name if role else rid}[/bold]",
                Text("· starting", style="dim"),
                Text("", style="dim"),
                Text("0 tools", style="dim"),
                Text("", style="dim"),
            )

    outer.add_row(roster_tbl)

    # 2. Shared Task Board summary (when tasks exist)
    if board and board.tasks:
        outer.add_row(Text(""))
        task_tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
        task_tbl.add_column("id", width=5)
        task_tbl.add_column("state", width=4)
        task_tbl.add_column("owner", width=12)
        task_tbl.add_column("title", ratio=1)

        for t in board.tasks[:8]:
            if t.status == "completed":
                icon = Text("✓", style="bold #22c55e")
            elif t.status == "in_progress":
                icon = Text(frame, style="bold cyan")
            elif t.status in ("failed", "blocked"):
                icon = Text("✗", style="bold red")
            else:
                icon = Text("○", style="dim")

            task_tbl.add_row(
                Text(t.id, style="dim bold"),
                icon,
                Text(f"@{t.assigned_to}", style="#38bdf8"),
                Text(t.title[:60], style="white" if t.status == "in_progress" else "dim"),
            )
        outer.add_row(task_tbl)

    task_short = task[:68] + ("…" if len(task) > 68 else "")
    status_label = board.status if board else "starting"
    title = f"[bold #14f1d9]AI-Team[/bold #14f1d9] [dim]({mode} · {status_label})[/dim]  ·  {total_elapsed:.1f}s"
    sub = f"[dim]{task_short}[/dim]"
    if dashboard_url:
        sub += f"  [dim]|[/dim]  [bold #38bdf8]{dashboard_url}[/bold #38bdf8]"

    return Panel(
        outer,
        title=title,
        subtitle=sub,
        border_style="#334155",
        box=box.ROUNDED,
        padding=(0, 1),
    )


async def run_team_with_ui(
    task: str,
    roles: List[str],
    mode: str,
    llm_client,
    preset: str = "dev",
    memory=None,
    skill_manager=None,
    root_dir: Optional[Path] = None,
    parent_registry=None,
    use_dashboard_state: bool = True,
) -> Optional[TeamRun]:
    """
    Execute ONE AI-Team run and render the live Rich Terminal TUI from its TeamBoard.
    """
    start_total = time.monotonic()
    spinner_frame = 0
    board_holder: Dict[str, Optional[TeamBoard]] = {"board": None}
    dashboard_url = ""

    async def _launch() -> Optional[TeamRun]:
        if use_dashboard_state:
            from .server import state as dash_state
            nonlocal dashboard_url
            dashboard_url = f"http://127.0.0.1:{dash_state.port}"
            dash_state.configure(
                llm_client=llm_client,
                memory=memory,
                skill_manager=skill_manager,
                root_dir=root_dir or config.ROOT_DIR,
                parent_registry=parent_registry,
            )

            def _capture_board(b: TeamBoard):
                board_holder["board"] = b

            return await dash_state.run_team(
                task=task,
                preset=preset,
                roles=roles,
                mode_override=mode,
                board_ready_cb=_capture_board,
            )

        mgr = TeamManager(
            llm_client=llm_client,
            memory=memory,
            skill_manager=skill_manager,
            root_dir=root_dir or config.ROOT_DIR,
            parent_registry=parent_registry,
        )
        b = mgr._build_board(goal=task, preset=preset, mode=mode, roles=roles, include_lead=(mode == "team"))
        board_holder["board"] = b
        return await mgr.run_team(task=task, roles=roles, preset=preset, mode=mode, board=b)

    agent_task = asyncio.create_task(_launch())

    try:
        with Live(
            _render_board_panel(None, task, roles, mode, 0.0, 0, dashboard_url),
            console=console,
            refresh_per_second=8,
            transient=False,
        ) as live:
            while not agent_task.done():
                spinner_frame += 1
                elapsed = time.monotonic() - start_total
                live.update(
                    _render_board_panel(
                        board_holder["board"], task, roles, mode, elapsed, spinner_frame, dashboard_url
                    )
                )
                await asyncio.sleep(0.12)

            elapsed = time.monotonic() - start_total
            live.update(
                _render_board_panel(
                    board_holder["board"], task, roles, mode, elapsed, spinner_frame, dashboard_url
                )
            )
    except asyncio.CancelledError:
        if not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass
        console.print("\n  [bold #f59e0b]AI-Team mission cancelled by user.[/bold #f59e0b]\n")
        raise

    run = agent_task.result()
    board = board_holder["board"]

    console.print()
    if board and board.files_touched:
        console.rule("[bold #38bdf8]Files Touched[/bold #38bdf8]", style="#334155")
        for f in board.files_touched:
            console.print(f"  [bold #14f1d9]{f['path']}[/bold #14f1d9] [dim]({f['action']} by @{f['by']})[/dim]")
        console.print()

    if board and board.summary:
        console.rule("[bold #38bdf8]Team Lead Summary[/bold #38bdf8]", style="#334155")
        console.print(Markdown(board.summary))
        console.print()
    elif run and run.results:
        for role_id, result in run.results.items():
            role = BUILTIN_ROLES_BY_ID.get(role_id)
            name = role.name if role else role_id
            console.rule(f"[bold #38bdf8]{name}[/bold #38bdf8]", style="#334155")
            console.print(Markdown(result))
            console.print()

    total = time.monotonic() - start_total
    tools_total = len(board.tool_events) if board else 0
    files_total = len(board.files_touched) if board else 0
    console.print(
        f"  [bold #22c55e]AI-Team completed[/bold #22c55e]  "
        f"[dim]{len(roles)} specialists · {tools_total} tool calls · {files_total} files · {total:.1f}s[/dim]\n"
    )
    return run
