"""
nolthira/team/commands.py
Shared /team command dispatcher for gateways & CLI help.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from ..config import config
from .agent import BUILTIN_ROLES, BUILTIN_ROLES_BY_ID
from .manager import PRESET_TEAMS, TeamManager, auto_mode

logger = logging.getLogger(__name__)

HELP_TEXT = """👥 **AI-Team Commands:**
  `/team roles`                              — list all specialist roles
  `/team presets`                            — list squad presets
  `/team run <task>`                         — launch Lead-coordinated AI-Team (`dev` squad)
  `/team run --preset <name> <task>`         — launch a named squad (`dev`, `fulldev`, `audit`, `review`, `docs`, `analysis`)
  `/team run --parallel <task>`              — run specialists simultaneously
  `/team run --roles coder,reviewer <task>`  — run custom specialists
  `/team ask <role> <task>`                  — dispatch a single specialist with tools
  `/team open`                               — open the always-on web dashboard in browser
  `/team stop`                               — stop active team mission"""


async def handle_team_command(
    args: List[str],
    send,
    llm_client,
    memory=None,
    skill_manager=None,
    root_dir: Optional[Path] = None,
    parent_registry=None,
) -> None:
    """Dispatch a /team subcommand."""
    if not args or args[0].lower() in ("help", "--help"):
        await send(HELP_TEXT)
        return

    sub = args[0].lower()

    if sub == "roles":
        lines = ["👥 **Available Specialist Roles:**\n"]
        for role in BUILTIN_ROLES:
            tools_lbl = ", ".join(role.toolsets)
            lines.append(f"  {role.emoji} `{role.id:<10}` — {role.description} `[{tools_lbl}]`")
        await send("\n".join(lines))
        return

    if sub == "presets":
        lines = ["🎭 **Squad Presets:**\n"]
        for name, roles in PRESET_TEAMS.items():
            lines.append(f"  `{name:<10}` → {', '.join(roles)}")
        lines.append("\nUsage: `/team run --preset <name> <task>`")
        await send("\n".join(lines))
        return

    if sub == "ask":
        if len(args) < 3:
            await send("Usage: `/team ask <role_id> <task>`")
            return
        role_id = args[1].lower()
        task = " ".join(args[2:])
        if role_id not in BUILTIN_ROLES_BY_ID:
            await send(f"❌ Unknown role `{role_id}`. Run `/team roles` to see valid options.")
            return
        role = BUILTIN_ROLES_BY_ID[role_id]
        manager = TeamManager(
            llm_client=llm_client,
            memory=memory,
            skill_manager=skill_manager,
            root_dir=root_dir or config.ROOT_DIR,
            parent_registry=parent_registry,
        )
        run = await manager.run_single(task=task, role_id=role_id)
        result = run.results.get(role_id, run.error or "No output.")
        await send(f"{role.emoji} **{role.name}** ({run.elapsed_s:.1f}s):\n\n{result}")
        return

    if sub == "run":
        rest = args[1:]
        preset = "dev"
        mode_override = None
        custom_roles: List[str] = []
        task_parts: List[str] = []

        i = 0
        while i < len(rest):
            token = rest[i].lower()
            if token == "--preset" and i + 1 < len(rest):
                preset = rest[i + 1].lower()
                i += 2
            elif token == "--parallel":
                mode_override = "parallel"
                i += 1
            elif token in ("--pipeline", "--sequential"):
                mode_override = "sequential"
                i += 1
            elif token == "--roles" and i + 1 < len(rest):
                custom_roles = [r.strip() for r in rest[i + 1].split(",") if r.strip()]
                i += 2
            else:
                task_parts.append(rest[i])
                i += 1

        task = " ".join(task_parts).strip()
        if not task:
            await send("❌ Please provide a task.\nExample: `/team run build a REST API for user authentication`")
            return

        if custom_roles:
            invalid = [r for r in custom_roles if r not in BUILTIN_ROLES_BY_ID]
            if invalid:
                await send(f"❌ Unknown roles: {', '.join(invalid)}\nRun `/team roles` to see valid options.")
                return
            roles = custom_roles
        else:
            roles_list = PRESET_TEAMS.get(preset)
            if not roles_list:
                await send(f"❌ Unknown preset `{preset}`. Available: {', '.join(PRESET_TEAMS)}")
                return
            roles = roles_list

        mode = mode_override or auto_mode(preset, custom_roles)
        manager = TeamManager(
            llm_client=llm_client,
            memory=memory,
            skill_manager=skill_manager,
            root_dir=root_dir or config.ROOT_DIR,
            parent_registry=parent_registry,
        )
        run = await manager.run_team(task=task, roles=roles, preset=preset, mode=mode)
        await send(run.summary())
        return

    await send(f"Unknown subcommand `{sub}`.\n\n{HELP_TEXT}")
