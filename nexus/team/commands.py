"""
nexus/team/commands.py
CLI + gateway /team command dispatcher.

Commands:
  /team                              — show help
  /team roles                        — list all available agent roles
  /team presets                      — list named preset teams
  /team run <task>                   — run default team (dev preset, pipeline)
  /team run --preset <name> <task>   — run a named preset (pipeline mode)
  /team run --parallel <task>        — run default roles in parallel
  /team run --roles <r1,r2,...> <task>  — run specific roles in pipeline
  /team run --roles <r1,r2,...> --parallel <task>
  /team ask <role_id> <task>         — ask a single agent
  /team last                         — show results of last team run
"""

from __future__ import annotations

import logging
from typing import List

from .manager import TeamManager, PRESET_TEAMS
from .agent import BUILTIN_ROLES, BUILTIN_ROLES_BY_ID

logger = logging.getLogger(__name__)

HELP_TEXT = """👥 **AI-Team Commands:**
  `/team roles`                              — list all agent roles
  `/team presets`                            — list preset teams
  `/team run <task>`                         — run `dev` preset (pipeline)
  `/team run --preset <name> <task>`         — run named preset
  `/team run --parallel <task>`              — all roles run simultaneously
  `/team run --roles coder,reviewer <task>`  — custom role list (pipeline)
  `/team run --roles coder,tester --parallel <task>`
  `/team ask <role> <task>`                  — single agent
  `/team last`                               — show last run results

**Preset teams:** dev · fulldev · audit · docs · analysis · review"""


async def handle_team_command(args: List[str], send, llm_client) -> None:
    """
    Dispatch a /team subcommand.
    `args`       — tokens after "/team"
    `send`       — async callable(text: str)
    `llm_client` — NexusAgent LLMClient instance
    """
    if not args:
        await send(HELP_TEXT)
        return

    sub = args[0].lower()

    if sub == "roles":
        lines = ["👥 **Available Agent Roles:**\n"]
        for role in BUILTIN_ROLES:
            lines.append(f"  {role.emoji} `{role.id:<12}` — {role.description}")
        await send("\n".join(lines))
        return

    if sub == "presets":
        lines = ["🎭 **Preset Teams:**\n"]
        for name, roles in PRESET_TEAMS.items():
            lines.append(f"  `{name:<10}` → {' → '.join(roles)}")
        lines.append("\nUsage: `/team run --preset <name> <task>`")
        await send("\n".join(lines))
        return

    if sub == "last":
        # Can't store last_run across send calls without manager instance,
        # just return a hint
        await send("ℹ️ `/team last` shows the last run result in the CLI session. Use `/team run` to start a new one.")
        return

    if sub == "ask":
        # /team ask <role_id> <task...>
        if len(args) < 3:
            await send("Usage: `/team ask <role_id> <task>`\nExample: `/team ask coder write a fibonacci function in Python`")
            return
        role_id = args[1].lower()
        task = " ".join(args[2:])
        if role_id not in BUILTIN_ROLES_BY_ID:
            await send(f"❌ Unknown role `{role_id}`. Run `/team roles` to see available roles.")
            return
        role = BUILTIN_ROLES_BY_ID[role_id]
        await send(f"{role.emoji} **{role.name}** is thinking…")
        manager = TeamManager(llm_client)
        run = await manager.run_single(task=task, role_id=role_id)
        result = run.results.get(role_id, run.error or "No output.")
        await send(f"{role.emoji} **{role.name}** says:\n\n{result}")
        return

    if sub == "run":
        rest = args[1:]
        preset = "dev"
        mode = "pipeline"
        custom_roles: List[str] = []
        task_parts: List[str] = []

        # Parse flags
        i = 0
        while i < len(rest):
            token = rest[i].lower()
            if token == "--preset" and i + 1 < len(rest):
                preset = rest[i + 1].lower()
                i += 2
            elif token == "--parallel":
                mode = "parallel"
                i += 1
            elif token == "--roles" and i + 1 < len(rest):
                custom_roles = [r.strip() for r in rest[i + 1].split(",")]
                i += 2
            else:
                task_parts.append(rest[i])
                i += 1

        task = " ".join(task_parts).strip()
        if not task:
            await send("❌ Please provide a task.\nExample: `/team run build a REST API for user authentication`")
            return

        # Determine roles
        if custom_roles:
            # Validate
            invalid = [r for r in custom_roles if r not in BUILTIN_ROLES_BY_ID]
            if invalid:
                await send(f"❌ Unknown roles: {', '.join(invalid)}\nRun `/team roles` to see valid options.")
                return
            roles = custom_roles
            team_label = " + ".join(roles)
        else:
            roles_list = PRESET_TEAMS.get(preset)
            if not roles_list:
                await send(f"❌ Unknown preset `{preset}`. Available: {', '.join(PRESET_TEAMS)}")
                return
            roles = roles_list
            team_label = f"{preset} preset"

        mode_label = "parallel" if mode == "parallel" else "pipeline"
        await send(
            f"🚀 **AI-Team starting** [{team_label}] [{mode_label}]\n"
            f"📋 Task: {task[:200]}\n"
            f"⏳ This may take a moment…"
        )

        manager = TeamManager(llm_client)
        completed_parts: List[str] = []

        async def on_progress(role_id: str, result: str):
            role = BUILTIN_ROLES_BY_ID.get(role_id)
            emoji = role.emoji if role else "🤖"
            name = role.name if role else role_id
            snippet = result.strip()[:300] + ("…" if len(result) > 300 else "")
            await send(f"{emoji} **{name}** ✓\n```\n{snippet}\n```")

        if mode == "parallel":
            run = await manager.run_parallel(task, roles, progress_cb=on_progress)
        else:
            run = await manager.run_pipeline(task, roles, progress_cb=on_progress)

        await send(
            f"✅ **AI-Team done** in {run.elapsed_s:.1f}s · "
            f"{len(run.results)} agents · {mode_label} mode"
        )
        return

    await send(f"Unknown subcommand `{sub}`.\n\n{HELP_TEXT}")
