import sys
import os
import gc
import signal
import asyncio
import argparse
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from .config import config
from .toolsets import ToolsetManager, ToolsetConfigError
from .memory import SQLiteMemory
from .skills import SkillManager
from .cron import CronScheduler
from .orchestrator import SubagentManager
from .providers.manager import ProviderManager
from .mcp import MCPManager
from .plugins import PluginManager
from .gateways import GatewayManager
from .security import SecurityGuard
from .updater import check_for_update, perform_update
from .tools import create_default_registry
from .core import LLMClient, NexusAgent, get_mode, cycle_mode
from .ui import (
    render_banner,
    render_memories_table,
    render_skills_table,
    render_cron_table,
    render_tools_table,
    render_status_card,
    render_config_table,
    render_sessions_table,
    render_resumed_history,
    render_mcp_table,
    render_plugins_table,
    render_security_card,
    render_computer_card,
    render_update_alert,
    render_update_card,
    render_gateway_card,
    AgentUIController,
    NexusCommandCompleter,
    render_command_palette,
    interactive_select_provider,
    interactive_select_model,
    interactive_select_mode,
    interactive_resume_session,
    interactive_gateway_setup,
    interactive_mcp_add,
    interactive_onboarding_setup,
    console
)

pt_style = Style.from_dict({
    'box-top': '#475569',
    'app-name': '#38bdf8 bold',
    'dim': '#64748b',
    'model-badge': '#22c55e bold',
    'workspace': '#94a3b8',
    'git-branch': '#a78bfa',
    'mode-auto': 'bg:#042f2e #00ffd7 bold',
    'mode-plan': 'bg:#2e1065 #c4b5fd bold',
    'mode-code': 'bg:#0c4a6e #38bdf8 bold',
    'mode-ask': 'bg:#052e16 #4ade80 bold',
    'mode-turbo': 'bg:#451a03 #fbbf24 bold',
    'box-bottom': '#00ffd7 bold',
    'rprompt': '#64748b',
    'rprompt-key': '#38bdf8 bold',
    'bottom-toolbar': 'bg:#0f172a #94a3b8',
    'bottom-toolbar.key': '#00ffd7 bold',
    'bottom-toolbar.sep': '#334155',
    'completion-menu.completion': 'bg:#1e1e2e #cdd6f4',
    'completion-menu.completion.current': 'bg:#00d7af #11111b bold',
    'completion-menu.meta.completion': 'bg:#181825 #94a3b8',
    'completion-menu.meta.completion.current': 'bg:#00d7af #11111b',
})


def _detect_git_branch(root: Path) -> str:
    """Fast local .git HEAD reader without spawning subprocess."""
    try:
        cur = root.resolve()
        for parent in [cur, *cur.parents]:
            head_file = parent / ".git" / "HEAD"
            if head_file.exists():
                txt = head_file.read_text(encoding="utf-8", errors="ignore").strip()
                if txt.startswith("ref: "):
                    return txt.split("/")[-1]
                return txt[:7]
    except Exception:
        pass
    return ""


def build_prompt_fragments(model_name: str, mode_id: str, workspace_name: str = "", git_branch: str = ""):
    """Build sleek cyberpunk prompt header fragments with mode, model, workspace, and git pill."""
    spec = get_mode(mode_id)
    model_short = model_name.split("/")[-1] if "/" in model_name else model_name
    frags = [
        ('class:box-top', '╭─ '),
        ('class:app-name', '◈ nexus'),
        ('class:dim', ' · '),
        (f'class:mode-{spec.id}', f' {spec.icon} {spec.label} '),
        ('class:dim', ' · '),
        ('class:model-badge', model_short),
    ]
    if workspace_name:
        frags.extend([
            ('class:dim', ' · '),
            ('class:workspace', f'⌂ {workspace_name}'),
        ])
    if git_branch:
        frags.extend([
            ('class:dim', ' '),
            ('class:git-branch', f'({git_branch})'),
        ])
    frags.append(('class:box-bottom', '\n╰─❯ '))
    return frags


def build_bottom_toolbar(mode_id: str, provider_name: str, session_id: str):
    """Build clean single-line bottom HUD bar."""
    spec = get_mode(mode_id)
    return [
        ('class:bottom-toolbar', ' '),
        (f'class:mode-{spec.id}', f' {spec.icon} {spec.label} '),
        ('class:bottom-toolbar', f' {spec.short_desc} '),
        ('class:bottom-toolbar.sep', '│ '),
        ('class:bottom-toolbar.key', 'Shift+Tab'),
        ('class:bottom-toolbar', ' mode  '),
        ('class:bottom-toolbar.key', '/'),
        ('class:bottom-toolbar', ' cmds  '),
        ('class:bottom-toolbar.key', '/models'),
        ('class:bottom-toolbar', ' model  '),
        ('class:bottom-toolbar.sep', '│ '),
        ('class:bottom-toolbar', f'{provider_name} · #{session_id} '),
    ]

async def main_async():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Nexus Agent Orchestrator - Autonomous Multi-Agent AI CLI")
    parser.add_argument("-p", "--prompt", type=str, help="Single-shot execution prompt", default=None)
    parser.add_argument("-m", "--model", type=str, help="Model override", default=None)
    parser.add_argument("-M", "--mode", type=str, help="Agent mode override (auto|plan|code|ask|turbo)", default=None)
    parser.add_argument("-s", "--session", type=str, help="Session ID to resume or use", default=None)
    parser.add_argument("--setup", action="store_true", help="Run interactive Nexus setup wizard")
    parser.add_argument("-g", "--gateway", nargs="?", const="all", default=None, help="Run messaging gateway daemon (all|telegram|discord|whatsapp|slack|email)")
    parser.add_argument("subcommand", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args()

    run_setup_wizard = bool(args.setup or (args.subcommand and args.subcommand[0].lower() == "setup"))

    # Support `nexus gateway [all|telegram|discord|whatsapp|slack|email]` positional syntax
    gateway_target = args.gateway
    if not gateway_target and args.subcommand and args.subcommand[0].lower() == "gateway":
        gateway_target = args.subcommand[1].lower() if len(args.subcommand) > 1 else "all"

    # Active configuration .env path (workspace override or global ~/.nexus/.env)
    env_path = config.ENV_PATH

    # Initialize subsystems
    memory = SQLiteMemory(config.MEMORY_DB_PATH)
    skill_manager = SkillManager(config.SKILLS_DIR)
    toolset_manager = ToolsetManager(config.NEXUS_HOME / "toolsets.json")
    cron_scheduler = CronScheduler(config.MEMORY_DB_PATH)
    mcp_manager = MCPManager(workspace_dir=config.WORKSPACE_DIR, codebase_dir=config.CODEBASE_DIR)
    plugin_manager = PluginManager(workspace_dir=config.WORKSPACE_DIR, codebase_dir=config.CODEBASE_DIR)

    model_name = args.model or config.MODEL
    llm = LLMClient(
        api_key=config.API_KEY,
        api_base=config.API_BASE,
        model=model_name,
        temperature=config.TEMPERATURE
    )

    active_mode = get_mode(args.mode or config.AGENT_MODE).id

    # Dedicated UI controller for collision-free live streaming & spinners
    ui_controller = AgentUIController(model_name=llm.model, console_instance=console, mode_id=active_mode)

    # Subagent orchestrator manager
    subagent_manager = SubagentManager(
        llm=llm,
        memory=memory,
        skill_manager=skill_manager,
        root_dir=config.ROOT_DIR,
        on_subagent_event=ui_controller.on_subagent_event,
        toolset_manager=toolset_manager,
    )

    current_session = [args.session or os.urandom(4).hex()]

    # Wire all tools including Subagent Delegation & Web & Cron & Vision
    registry = create_default_registry(
        root_dir=config.ROOT_DIR,
        memory=memory,
        skill_manager=skill_manager,
        cron_scheduler=cron_scheduler,
        subagent_manager=subagent_manager,
        session_id_getter=lambda: current_session[0],
        llm_client=llm,
        toolset_manager=toolset_manager,
        profile=toolset_manager.default_profile,
    )
    if mcp_manager.servers:
        await mcp_manager.start_all()
    mcp_manager.register_mcp_tools(registry)
    plugin_manager.register_plugin_tools(registry)

    def _gateway_logger(platform: str, msg: str):
        if gateway_target:
            console.print(f"  [dim][{platform.upper()}][/dim] {msg}")

    gateway_manager = GatewayManager(
        llm_client=llm,
        memory=memory,
        skill_manager=skill_manager,
        registry=registry,
        soul_path=config.SOUL_PATH,
        max_steps=config.MAX_STEPS,
        on_log=_gateway_logger,
        toolset_manager=toolset_manager,
    )
    gateway_manager.register_tools(registry)

    agent = NexusAgent(
        llm_client=llm,
        memory=memory,
        skill_manager=skill_manager,
        registry=registry,
        soul_path=config.SOUL_PATH,
        max_steps=config.MAX_STEPS,
        session_id=current_session[0],
        mode=active_mode,
        on_thought=ui_controller.on_thought,
        on_token=ui_controller.on_token,
        on_tool_call=ui_controller.on_tool_call,
        on_tool_result=ui_controller.on_tool_result,
        on_retry=ui_controller.on_retry,
    )

    async def _cron_executor(job: dict) -> str:
        mode = (job.get("mode") or "agent").lower()
        instr = job.get("instruction") or ""
        if mode == "shell":
            cmd_tool = registry.get("run_command")
            if cmd_tool:
                return await cmd_tool.execute(command=instr)
            return "Error: run_command tool unavailable."
        cron_agent = NexusAgent(
            llm_client=llm,
            memory=memory,
            skill_manager=skill_manager,
            registry=registry,
            soul_path=config.SOUL_PATH,
            max_steps=min(config.MAX_STEPS, 15),
            session_id=f"cron-{job['id']}",
            mode="auto",
        )
        return await cron_agent.run(instr)

    async def _cron_notify(job: dict, result_text: str):
        preview = (result_text or "").strip().splitlines()[0][:120] if result_text else "Done"
        if not ui_controller.stream_started and not ui_controller._thinking_active:
            console.print(
                f"\n  [bold #38bdf8]⏰ Cron #{job['id']} ({job['name']}):[/bold #38bdf8] [white]{preview}[/white]"
            )
        target = (job.get("target") or "").lower()
        if target in ("telegram", "discord", "whatsapp"):
            gw_tool = registry.get("gateway_send")
            if gw_tool:
                try:
                    await gw_tool.execute(
                        platform=target,
                        message=f"⏰ *Cron #{job['id']} — {job['name']}*\n\n{(result_text or '')[:1200]}",
                    )
                except Exception:
                    pass

    # Headless Messaging Gateway Daemon Mode (`nexus --gateway` / `nexus gateway`)
    if gateway_target:
        console.print(f"\n  [bold #00ffd7]🌐 Starting Nexus Gateway Daemon[/bold #00ffd7] [dim](target: {gateway_target})[/dim]")
        started = await gateway_manager.start_gateway(gateway_target)
        cron_scheduler.start_runner(_cron_executor, on_complete=_cron_notify, poll_interval=5.0)
        render_gateway_card(gateway_manager.get_statuses())
        if not any(v in ("started", "already_running") for v in started.values()):
            await cron_scheduler.stop_runner()
            console.print("  [bold yellow]⚠ No configured gateways found for target.[/bold yellow] Run `nexus` and type `/gateway setup` first.\n")
            return
        console.print("  [bold #22c55e]✔ Gateway daemon + Cron runner active.[/bold #22c55e] [dim]Listening (Ctrl+C to stop)...[/dim]\n")
        try:
            while True:
                await asyncio.sleep(1.0)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("\n  [dim cyan]⠋ Shutting down messaging gateways & cron runner...[/dim cyan]")
            await cron_scheduler.stop_runner()
            await gateway_manager.stop_gateway("all")
            await mcp_manager.stop_all()
            console.print("  [bold #00ffd7]✔ Gateways offline.[/bold #00ffd7]\n")
        return

    # Unified Onboarding Wizard (`nexus setup` or `nexus --setup`)
    if run_setup_wizard:
        setup_sess = PromptSession(history=InMemoryHistory())
        await interactive_onboarding_setup(setup_sess, llm, agent, env_path)
        await mcp_manager.stop_all()
        return

    # If single-shot prompt provided
    if args.prompt:
        console.print(f"[bold #38bdf8]Running task:[/bold #38bdf8] {args.prompt}")
        ui_controller.start_thinking("Executing task...")
        try:
            await agent.run(args.prompt)
        finally:
            ui_controller.finish_stream()
            await mcp_manager.stop_all()
        return

    # Interactive REPL mode
    skills = skill_manager.load_all_skills()
    tools = registry.get_all()
    active_provider = ProviderManager.detect_active_provider(config.API_BASE)

    # Quick cached update check
    update_info = None
    try:
        update_info = await check_for_update(force=False)
    except Exception:
        pass

    render_banner(
        model_name=llm.model,
        session_id=agent.session_id,
        skills_count=len(skills),
        tools_count=len(tools),
        provider_name=active_provider.name,
        animate=True,
        update_info=update_info,
        mode_id=agent.mode,
    )

    # Optional auto-start gateways if configured in .env
    if os.getenv("GATEWAY_AUTO_START", "false").lower() in ("true", "1", "yes"):
        try:
            await gateway_manager.start_gateway("all")
        except Exception:
            pass

    # Start background Cron execution runner
    cron_scheduler.start_runner(_cron_executor, on_complete=_cron_notify, poll_interval=5.0)

    # Always-on AI-Team dashboard server (background)
    try:
        from nexus.team.server import start_dashboard_server
        dash_port = await start_dashboard_server(
            llm,
            port=7891,
            memory=memory,
            skill_manager=skill_manager,
            root_dir=config.ROOT_DIR,
            parent_registry=registry,
        )
        console.print(f"  [dim]👥 AI-Team dashboard → [bold #00ffd7]http://127.0.0.1:{dash_port}[/bold #00ffd7][/dim]\n")
    except Exception:
        pass  # Dashboard is optional, don't block CLI

    completer = NexusCommandCompleter()
    prompt_kb = KeyBindings()

    @prompt_kb.add("s-tab")
    def _cycle_mode_hotkey(event):
        spec = cycle_mode(agent.mode)
        agent.mode = spec.id
        config.AGENT_MODE = spec.id
        os.environ["NEXUS_AGENT_MODE"] = spec.id
        ui_controller.update_mode(spec.id)
        try:
            ProviderManager.update_env_file({"NEXUS_AGENT_MODE": spec.id}, env_path)
        except Exception:
            pass
        event.app.invalidate()

    session = PromptSession(
        history=InMemoryHistory(),
        completer=completer,
        complete_while_typing=True,
        key_bindings=prompt_kb,
    )

    workspace_name = config.ROOT_DIR.name

    while True:
        try:
            session.is_password = False
            git_branch = _detect_git_branch(config.ROOT_DIR)
            prov_name = ProviderManager.detect_active_provider(config.API_BASE).name.split("(")[0].strip()

            def _get_prompt():
                return build_prompt_fragments(
                    model_name=llm.model,
                    mode_id=agent.mode,
                    workspace_name=workspace_name,
                    git_branch=git_branch,
                )

            def _get_rprompt():
                return [
                    ('class:rprompt-key', 'Shift+Tab'),
                    ('class:rprompt', ' ⇄ mode '),
                ]

            def _get_toolbar():
                return build_bottom_toolbar(
                    mode_id=agent.mode,
                    provider_name=prov_name,
                    session_id=agent.session_id,
                )

            user_input = await session.prompt_async(
                _get_prompt,
                rprompt=_get_rprompt,
                bottom_toolbar=_get_toolbar,
                style=pt_style,
                is_password=False,
            )
            text = user_input.strip()
            if not text:
                continue

            if text.lower() in ("exit", "quit", "q"):
                await cron_scheduler.stop_runner()
                await gateway_manager.stop_gateway("all")
                await mcp_manager.stop_all()
                try:
                    from nexus.team.server import stop_dashboard_server
                    await stop_dashboard_server()
                except Exception:
                    pass
                console.print("\n  [dim cyan]⠋ Preserving orchestrator session & persistent memory (FTS5)...[/dim cyan]")
                await asyncio.sleep(0.15)
                gc.collect()
                await asyncio.sleep(0.05)
                console.print("  [bold #00ffd7]✔ Session preserved.[/bold #00ffd7] [dim]Nexus Orchestrator offline. Goodbye![/dim]\n")
                break

            # Handle slash commands & command palette
            if text == "/" or text.lower() in ("/help", "/?", "/commands", "/command"):
                render_command_palette()
                continue

            if text.startswith("/"):
                cmd = text.lower().split()[0]
                if cmd in ("/mode", "/modes"):
                    args_mode = text.split(maxsplit=1)
                    req_m = args_mode[1].strip() if len(args_mode) > 1 else None
                    new_m = await interactive_select_mode(agent, env_path, requested_mode=req_m)
                    if new_m:
                        ui_controller.update_mode(new_m)
                    continue
                elif cmd in ("/models", "/model"):
                    args_m = text.lower().split()[1:]
                    force_chk = any(a in ("check", "refresh", "--check", "--refresh") for a in args_m)
                    await interactive_select_model(session, llm, env_path, force_check=force_chk)
                    ui_controller.update_model(llm.model)
                    continue
                elif cmd in ("/provider", "/providers", "/connect"):
                    await interactive_select_provider(session, llm, env_path)
                    ui_controller.update_model(llm.model)
                    continue
                elif cmd in ("/tools", "/tool"):
                    render_tools_table(tools)
                    continue
                elif cmd in ("/toolsets", "/toolset"):
                    parts = text.strip().split()
                    action = parts[1].lower() if len(parts) > 1 else "list"
                    active_profile = toolset_manager.default_profile
                    try:
                        if action == "use" and len(parts) > 2:
                            toolset_manager.set_default_profile(parts[2])
                            active_profile = parts[2]
                            toolset_manager.apply(registry, active_profile)
                            tools = registry.get_all()
                            console.print(f"\\n  [bold #22c55e]✔ Active toolset profile: {active_profile}[/bold #22c55e]\\n")
                        elif action in ("enable", "disable") and len(parts) > 2:
                            state = toolset_manager.set_toolset(active_profile, parts[2], enabled=(action == "enable"))
                            toolset_manager.apply(registry, active_profile)
                            tools = registry.get_all()
                            status = "enabled" if action == "enable" else "disabled"
                            console.print(f"\\n  [bold #22c55e]✔ Toolset '{parts[2]}' {status} in profile '{active_profile}'.[/bold #22c55e]\\n")
                        elif action == "platform" and len(parts) > 3:
                            toolset_manager.set_platform_profile(parts[2], parts[3])
                            console.print(f"\\n  [bold #22c55e]✔ Platform '{parts[2]}' uses profile '{parts[3]}'. Restart its gateway to apply.[/bold #22c55e]\\n")
                        elif action == "role" and len(parts) > 3:
                            toolset_manager.set_role_profile(parts[2], parts[3])
                            console.print(f"\\n  [bold #22c55e]✔ Subagent role '{parts[2]}' uses profile '{parts[3]}'.[/bold #22c55e]\\n")
                        else:
                            profiles = toolset_manager.list_profiles()
                            console.print(f"\\n  [bold #38bdf8]Toolset Profiles · active: {active_profile}[/bold #38bdf8]")
                            for item in profiles:
                                enabled = ", ".join(item["enabled_toolsets"])
                                denied = ", ".join(item["disabled_tools"]) or "none"
                                marker = " [bold #22c55e](active)[/bold #22c55e]" if item["name"] == active_profile else ""
                                console.print(f"  [white]{item['name']}[/white]{marker}\\n    [dim]Enabled: {enabled}\\n    Disabled tools: {denied}[/dim]")
                            console.print("\\n  [dim]/toolsets use <profile> · /toolsets enable|disable <toolset> · /toolsets platform <gateway> <profile> · /toolsets role <role> <profile>[/dim]\\n")
                    except ToolsetConfigError as exc:
                        console.print(f"  [bold red]Toolset configuration error:[/bold red] {exc}\\n")
                    continue
                elif cmd in ("/status", "/info"):
                    active_prov = ProviderManager.detect_active_provider(config.API_BASE)
                    all_mems = memory.get_all_memories(limit=100)
                    cron_tasks = cron_scheduler.list_tasks()
                    render_status_card(
                        model_name=llm.model,
                        provider_name=active_prov.name,
                        session_id=agent.session_id,
                        tools_count=len(tools),
                        skills_count=len(skills),
                        mem_count=len(all_mems),
                        cron_count=len(cron_tasks),
                        mode_id=agent.mode,
                    )
                    continue
                elif cmd in ("/config", "/env", "/settings"):
                    cfg_dict = {
                        "Agent Mode": agent.mode.upper(),
                        "Active Model": llm.model,
                        "Inference API Base": config.API_BASE,
                        "API Key": config.API_KEY,
                        "Sampling Temperature": config.TEMPERATURE,
                        "Max ReAct Loop Steps": config.MAX_STEPS,
                        "Working Directory": str(config.ROOT_DIR),
                        "SQLite Memory DB": str(config.MEMORY_DB_PATH),
                        "Learned Skills Path": skill_manager.get_search_paths_summary(),
                        "Persona SOUL Path": str(config.SOUL_PATH),
                    }
                    render_config_table(cfg_dict)
                    continue
                elif cmd in ("/sessions", "/history"):
                    sess_list = memory.list_sessions(limit=15)
                    render_sessions_table(sess_list, agent.session_id)
                    continue
                elif cmd in ("/resume", "/restore"):
                    parts = text.split()
                    if len(parts) > 1:
                        target_id = parts[1].strip()
                        current_session[0] = target_id
                        agent.session_id = target_id
                        history = memory.get_session_history(target_id)
                        sess_meta = memory.get_session(target_id) if hasattr(memory, "get_session") else None
                        sess_title = (sess_meta or {}).get("title") or ""
                        render_resumed_history(history, target_id, title=sess_title)
                    else:
                        await interactive_resume_session(memory, current_session, agent)
                    continue
                elif cmd in ("/rename",):
                    new_title = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
                    if not new_title:
                        console.print("  [yellow]Usage: /rename <session title>[/yellow]\n")
                    elif memory.rename_session(agent.session_id, new_title):
                        console.print(f"\n  [bold #22c55e]✔ Renamed session #{agent.session_id} →[/bold #22c55e] [bold #00ffd7]{new_title}[/bold #00ffd7]\n")
                    else:
                        console.print("  [red]Could not rename session.[/red]\n")
                    continue
                elif cmd in ("/mcp", "/servers"):
                    parts = text.strip().split()
                    sub = parts[1].lower() if len(parts) > 1 else ""
                    if sub == "add":
                        await interactive_mcp_add(session, mcp_manager, registry)
                        tools = registry.get_all()
                    elif sub in ("remove", "rm", "del") and len(parts) > 2:
                        target_name = parts[2].strip()
                        if await mcp_manager.remove_server(target_name, registry):
                            tools = registry.get_all()
                            console.print(f"\n  [bold #22c55e]✔ Removed MCP server '{target_name}'.[/bold #22c55e]\n")
                        else:
                            console.print(f"\n  [yellow]MCP server '{target_name}' not found.[/yellow]\n")
                    elif sub == "reload":
                        console.print("\n  [dim cyan]⠋ Reloading MCP servers...[/dim cyan]")
                        await mcp_manager.reload(registry)
                        tools = registry.get_all()
                        render_mcp_table(mcp_manager.get_status())
                    else:
                        render_mcp_table(mcp_manager.get_status())
                    continue
                elif cmd in ("/plugins", "/plugin"):
                    render_plugins_table(plugin_manager.list_plugins())
                    continue
                elif cmd == "/github":
                    from nexus.github_app.commands import handle_github_command, HELP_TEXT
                    gh_args = text.strip().split()[1:]
                    _gh_replies = []
                    async def _gh_send(t):
                        _gh_replies.append(t)
                    await handle_github_command(gh_args, _gh_send)
                    output_text = "\n\n".join(_gh_replies) if _gh_replies else HELP_TEXT
                    from rich.markdown import Markdown
                    console.print(Markdown(output_text))
                    continue
                elif cmd in ("/team", "/ai-team"):
                    from nexus.team.commands import HELP_TEXT as TEAM_HELP
                    from nexus.team.ui import run_team_with_ui
                    from nexus.team.agent import BUILTIN_ROLES_BY_ID, BUILTIN_ROLES
                    from nexus.team.manager import PRESET_TEAMS, TeamManager, auto_mode
                    from rich.markdown import Markdown

                    team_args = text.strip().split()[1:]

                    if not team_args or team_args[0].lower() in ("help", "--help"):
                        console.print(Markdown(TEAM_HELP))
                        continue

                    sub_t = team_args[0].lower()

                    if sub_t == "roles":
                        console.print("\n  [bold #00ffd7]👥 AI-Team Roles[/bold #00ffd7]\n")
                        for role in BUILTIN_ROLES:
                            console.print(f"    {role.emoji}  [bold #38bdf8]{role.id:<12}[/bold #38bdf8] [dim]→[/dim]  {role.description}")
                        console.print()
                        continue

                    if sub_t == "presets":
                        console.print("\n  [bold #00ffd7]🎭 Preset Teams[/bold #00ffd7]\n")
                        for name, roles in PRESET_TEAMS.items():
                            mode_hint = auto_mode(name, [])
                            console.print(f"    [bold #38bdf8]{name:<12}[/bold #38bdf8] [dim]→[/dim]  {', '.join(roles)}  [dim]({mode_hint})[/dim]")
                        console.print()
                        continue

                    if sub_t == "open":
                        import webbrowser
                        from nexus.team.server import state as _dash_state
                        url = f"http://127.0.0.1:{_dash_state.port}"
                        webbrowser.open(url)
                        console.print(f"\n  [bold #14f1d9]Opened AI-Team dashboard:[/bold #14f1d9] {url}\n")
                        continue

                    if sub_t == "stop":
                        from nexus.team.server import state as _dash_state
                        stopped = await _dash_state.stop_active_run()
                        msg = "Stopped active AI-Team mission." if stopped else "No active AI-Team mission running."
                        console.print(f"\n  [yellow]{msg}[/yellow]\n")
                        continue

                    if sub_t == "ask":
                        if len(team_args) < 3:
                            console.print("  [yellow]Usage: /team ask <role_id> <task>[/yellow]\n")
                            continue
                        role_id = team_args[1].lower()
                        task_text = " ".join(team_args[2:])
                        if role_id not in BUILTIN_ROLES_BY_ID:
                            console.print(f"  [red]Unknown role `{role_id}`. Run /team roles.[/red]\n")
                            continue
                        role = BUILTIN_ROLES_BY_ID[role_id]
                        console.print(f"\n  {role.emoji} [bold cyan]{role.name}[/bold cyan] working with tools…\n")
                        _tm = TeamManager(
                            llm_client=llm,
                            memory=memory,
                            skill_manager=skill_manager,
                            root_dir=config.ROOT_DIR,
                            parent_registry=registry,
                        )
                        _run = await _tm.run_single(task_text, role_id)
                        result = _run.results.get(role_id, "No output.")
                        console.rule(f"{role.emoji} [bold #38bdf8]{role.name}[/bold #38bdf8]", style="#334155")
                        console.print(Markdown(result))
                        console.print()
                        continue

                    if sub_t == "run":
                        rest = team_args[1:]
                        preset = "dev"
                        mode_override = None   # None = auto-detect
                        custom_roles = []
                        task_parts = []
                        use_web = True
                        i = 0
                        while i < len(rest):
                            tok = rest[i].lower()
                            if tok == "--preset" and i + 1 < len(rest):
                                preset = rest[i + 1].lower()
                                i += 2
                            elif tok == "--parallel":
                                mode_override = "parallel"
                                i += 1
                            elif tok in ("--pipeline", "--sequential"):
                                mode_override = "sequential"
                                i += 1
                            elif tok == "--roles" and i + 1 < len(rest):
                                custom_roles = [r.strip() for r in rest[i + 1].split(",") if r.strip()]
                                i += 2
                            elif tok == "--no-web":
                                use_web = False
                                i += 1
                            else:
                                task_parts.append(rest[i])
                                i += 1
                        task_text = " ".join(task_parts).strip()
                        if not task_text:
                            console.print("  [yellow]Provide a task. Example: /team run build a login API[/yellow]\n")
                            continue
                        if custom_roles:
                            invalid = [r for r in custom_roles if r not in BUILTIN_ROLES_BY_ID]
                            if invalid:
                                console.print(f"  [red]Unknown roles: {', '.join(invalid)}[/red]\n")
                                continue
                            roles_to_run = custom_roles
                        else:
                            roles_to_run = PRESET_TEAMS.get(preset)
                            if not roles_to_run:
                                console.print(f"  [red]Unknown preset `{preset}`. Available: {', '.join(PRESET_TEAMS)}[/red]\n")
                                continue

                        mode = mode_override or auto_mode(preset, custom_roles)
                        await run_team_with_ui(
                            task=task_text,
                            roles=roles_to_run,
                            mode=mode,
                            llm_client=llm,
                            preset=preset,
                            memory=memory,
                            skill_manager=skill_manager,
                            root_dir=config.ROOT_DIR,
                            parent_registry=registry,
                            use_dashboard_state=use_web,
                        )
                        continue

                    # Unknown subcommand — show help
                    console.print(Markdown(TEAM_HELP))
                    continue
                elif cmd in ("/gateway", "/gateways", "/bot"):
                    parts = text.strip().split()
                    sub = parts[1].lower() if len(parts) > 1 else "status"
                    target = parts[2].lower() if len(parts) > 2 else "all"
                    if sub == "setup":
                        await interactive_gateway_setup(session, env_path)
                    elif sub == "start":
                        console.print(f"\n  [dim cyan]⠋ Starting messaging gateway ({target})...[/dim cyan]")
                        res = await gateway_manager.start_gateway(target)
                        render_gateway_card(gateway_manager.get_statuses())
                        if not any(v in ("started", "already_running") for v in res.values()):
                            console.print("  [yellow]Tip: Run [bold #00ffd7]/gateway setup[/bold #00ffd7] to configure your bot token first.[/yellow]\n")
                    elif sub == "stop":
                        await gateway_manager.stop_gateway(target)
                        console.print(f"\n  [bold #22c55e]✔ Stopped gateway ({target}).[/bold #22c55e]\n")
                    else:
                        render_gateway_card(gateway_manager.get_statuses())
                    continue
                elif cmd in ("/security", "/safe", "/guard"):
                    render_security_card()
                    continue
                elif cmd in ("/computer", "/gui", "/screen"):
                    parts = text.strip().split()
                    subaction = parts[1].lower() if len(parts) > 1 else "status"
                    if subaction in ("screenshot", "shot"):
                        comp_tool = tools.get("computer")
                        if comp_tool:
                            console.print("\n  [dim cyan]⠋ Capturing desktop screenshot...[/dim cyan]")
                            res = await comp_tool.execute(action="screenshot")
                            console.print(f"  [bold #00ffd7]📸 Computer Screen:[/bold #00ffd7] {res}\n")
                        else:
                            console.print("\n  [red]Computer tool is not available in registry.[/red]\n")
                    else:
                        render_computer_card()
                    continue
                elif cmd in ("/skills", "/skill"):
                    render_skills_table(skill_manager.load_all_skills())
                    continue
                elif cmd in ("/memory", "/mem"):
                    render_memories_table(memory.get_all_memories(limit=25))
                    continue
                elif cmd in ("/cron", "/tasks"):
                    parts = text.strip().split()
                    sub = parts[1].lower() if len(parts) > 1 else ""
                    if sub == "run" and len(parts) > 2 and parts[2].isdigit():
                        tid = int(parts[2])
                        console.print(f"\n  [dim cyan]⠋ Executing cron task #{tid} now...[/dim cyan]")
                        res = await cron_scheduler.run_task_now(tid, _cron_executor, on_complete=_cron_notify)
                        if res is None:
                            console.print(f"  [red]Cron task #{tid} not found.[/red]\n")
                        else:
                            console.print(f"  [bold #22c55e]✔ Cron #{tid} complete:[/bold #22c55e]\n{res[:600]}\n")
                    elif sub == "pause" and len(parts) > 2 and parts[2].isdigit():
                        ok = cron_scheduler.pause_task(int(parts[2]))
                        console.print(f"\n  {'[yellow]⏸ Paused[/yellow]' if ok else '[red]Not found[/red]'} task #{parts[2]}\n")
                    elif sub == "resume" and len(parts) > 2 and parts[2].isdigit():
                        ok = cron_scheduler.resume_task(int(parts[2]))
                        console.print(f"\n  {'[green]▶ Resumed[/green]' if ok else '[red]Not found[/red]'} task #{parts[2]}\n")
                    elif sub == "cancel" and len(parts) > 2 and parts[2].isdigit():
                        ok = cron_scheduler.cancel_task(int(parts[2]))
                        console.print(f"\n  {'[dim]✖ Cancelled[/dim]' if ok else '[red]Not found[/red]'} task #{parts[2]}\n")
                    else:
                        render_cron_table(cron_scheduler.list_tasks())
                    continue
                elif cmd in ("/update", "/upgrade"):
                    parts = text.strip().split()
                    if len(parts) > 1 and parts[1].lower() in ("check", "status"):
                        console.print("\n  [dim cyan]⠋ Checking GitHub for updates...[/dim cyan]")
                        up_info = await check_for_update(force=True)
                        render_update_card(up_info)
                    else:
                        await perform_update(console)
                    continue
                elif cmd in ("/setup", "/onboarding"):
                    await interactive_onboarding_setup(session, llm, agent, env_path)
                    ui_controller.update_model(llm.model)
                    ui_controller.update_mode(agent.mode)
                    continue
                elif cmd in ("/sandbox",):
                    parts = text.strip().split()
                    sub = parts[1].lower() if len(parts) > 1 else "status"
                    if sub in ("local", "docker", "ssh"):
                        config.EXEC_BACKEND = sub
                        os.environ["NEXUS_EXEC_BACKEND"] = sub
                        ProviderManager.update_env_file({"NEXUS_EXEC_BACKEND": sub}, env_path)
                        console.print(f"\n  [bold #22c55e]✔ Execution sandbox backend set to:[/bold #22c55e] [bold #00ffd7]{sub}[/bold #00ffd7]\n")
                    else:
                        console.print(f"\n  [bold #00ffd7]🛡 Terminal Execution Sandbox[/bold #00ffd7]")
                        console.print(f"    Backend:      [bold #22c55e]{config.EXEC_BACKEND}[/bold #22c55e]")
                        console.print(f"    Docker Image: [white]{config.DOCKER_IMAGE}[/white]")
                        console.print(f"    SSH Host:     [white]{config.SSH_HOST or '(not set)'}[/white]")
                        console.print("    [dim]Usage: /sandbox [local|docker|ssh][/dim]\n")
                    continue
                elif cmd in ("/mascot",):
                    from .ui.mascot import (
                        build_piko_renderable,
                        detect_graphics_protocol,
                        encode_iterm2_image,
                        encode_kitty_image,
                        encode_sixel_image,
                        render_mascot_png_bytes,
                    )
                    parts = text.strip().split()
                    sub = parts[1].lower() if len(parts) > 1 else ""
                    if sub in ("auto", "pixel", "kitty", "iterm2", "sixel"):
                        os.environ["NEXUS_MASCOT_MODE"] = sub
                        console.print(f"\n  [bold #22c55e]✔ Mascot renderer mode:[/bold #22c55e] [bold #00ffd7]{sub}[/bold #00ffd7] (active: {detect_graphics_protocol(sub)})\n")
                    else:
                        proto = detect_graphics_protocol()
                        console.print(f"\n  [bold #00ffd7]◈ Piko Pixel Mascot Preview[/bold #00ffd7] [dim](mode: {proto})[/dim]\n")
                        if proto in ("kitty", "iterm2", "sixel") and sub == "native":
                            png = render_mascot_png_bytes(0, 0.0, "think", scale=5)
                            seq = encode_kitty_image(png) if proto == "kitty" else (encode_iterm2_image(png) if proto == "iterm2" else encode_sixel_image(0, 0.0, "think", scale=3))
                            sys.stdout.write("  " + seq + "\n")
                            sys.stdout.flush()
                        else:
                            console.print(build_piko_renderable(0, 1.2, "Thinking & coordinating...", llm.model, getattr(console, "width", 100) or 100, agent.mode))
                            console.print()
                            console.print(build_piko_renderable(4, 3.5, "Executing write_file...", llm.model, getattr(console, "width", 100) or 100, agent.mode))
                            console.print("  [dim]Tip: /mascot [auto|pixel|kitty|iterm2|sixel] · /mascot native[/dim]\n")
                    continue
                elif cmd in ("/clear", "/cls"):
                    os.system("cls" if os.name == "nt" else "clear")
                    active_provider = ProviderManager.detect_active_provider(config.API_BASE)
                    up_info = None
                    try:
                        up_info = await check_for_update(force=False)
                    except Exception:
                        pass
                    render_banner(
                        model_name=llm.model,
                        session_id=agent.session_id,
                        skills_count=len(skills),
                        tools_count=len(tools),
                        provider_name=active_provider.name,
                        animate=True,
                        update_info=up_info,
                        mode_id=agent.mode,
                    )
                    continue
                elif cmd.startswith("/new"):
                    new_id = os.urandom(4).hex()
                    custom_title = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
                    current_session[0] = new_id
                    agent.session_id = new_id
                    if custom_title:
                        memory.create_session(new_id, title=custom_title)
                    else:
                        memory.create_session(new_id, title=f"Session {new_id}")
                    console.print("\n  [dim cyan]⠋ Initializing clean context session...[/dim cyan]")
                    await asyncio.sleep(0.2)
                    title_note = f" '{custom_title}'" if custom_title else " (auto-named on first prompt)"
                    console.print(f"  [bold #22c55e]✨ Fresh session activated:[/bold #22c55e] [bold #00ffd7]{new_id}[/bold #00ffd7] [dim]{title_note}[/dim]\n")
                    continue
                else:
                    console.print(f"  [red]Unknown command:[/red] {text}. Type [bold #00ffd7]/[/bold #00ffd7] for command palette.\n")
                    continue

            # Check if API key is configured
            if not config.API_KEY or config.API_KEY == "your_api_key_here":
                active_prov = ProviderManager.detect_active_provider(config.API_BASE)
                if not active_prov.is_local:
                    console.print(
                        f"\n  [bold yellow]Notice:[/bold yellow] No API Key set for [bold]{active_prov.name}[/bold].\n"
                        "  Type [bold #00ffd7]/provider[/bold #00ffd7] to connect your API key, or edit [bold].env[/bold].\n"
                    )

            # Smooth ReAct execution with live streaming & Ctrl+C / Esc interrupt
            await _run_interruptible_agent(agent, text, ui_controller, console)

        except (KeyboardInterrupt, EOFError):
            ui_controller.stop_status()
            await cron_scheduler.stop_runner()
            await gateway_manager.stop_gateway("all")
            await mcp_manager.stop_all()
            console.print("\n  [yellow]Session interrupted. Goodbye![/yellow]\n")
            break
        except Exception as e:
            ui_controller.stop_status()
            console.print(f"\n  [bold red]Error:[/bold red] {str(e)}\n")

async def _watch_interrupt_keys(target_task: asyncio.Task, stop_evt: asyncio.Event):
    """Watch for standalone Esc / Ctrl+C keypresses while agent is running (Windows console)."""
    if sys.platform != "win32":
        return
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return
        import msvcrt
    except Exception:
        return

    while not stop_evt.is_set() and not target_task.done():
        try:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch == b"\x03":
                    if not target_task.done():
                        target_task.cancel()
                    return
                if ch == b"\x1b":
                    await asyncio.sleep(0.015)
                    if msvcrt.kbhit():
                        # Escape sequence (e.g. arrow key), drain trailing bytes
                        while msvcrt.kbhit():
                            msvcrt.getch()
                    else:
                        if not target_task.done():
                            target_task.cancel()
                        return
        except Exception:
            return
        await asyncio.sleep(0.06)


async def _run_interruptible_agent(agent: NexusAgent, text: str, ui_controller: AgentUIController, console_out):
    """Run agent.run(text) with Ctrl+C and Esc interruption that stops the AI without exiting CLI."""
    loop = asyncio.get_running_loop()
    agent_task = asyncio.create_task(agent.run(text))
    stop_evt = asyncio.Event()
    key_task = asyncio.create_task(_watch_interrupt_keys(agent_task, stop_evt))

    def _trigger_cancel():
        if not agent_task.done():
            agent_task.cancel()

    used_loop_sig = False
    prev_sigint = None
    try:
        try:
            loop.add_signal_handler(signal.SIGINT, _trigger_cancel)
            used_loop_sig = True
        except (NotImplementedError, RuntimeError):
            prev_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(_trigger_cancel))

        ui_controller.start_thinking()
        try:
            await agent_task
        except asyncio.CancelledError:
            ui_controller.finish_stream()
            console_out.print("\n  [bold #f59e0b]⚡ Interrupted by user — AI stopped.[/bold #f59e0b] [dim](Session preserved)[/dim]\n")
        finally:
            ui_controller.finish_stream()
    finally:
        stop_evt.set()
        if not key_task.done():
            key_task.cancel()
            try:
                await key_task
            except (asyncio.CancelledError, Exception):
                pass
        if used_loop_sig:
            try:
                loop.remove_signal_handler(signal.SIGINT)
            except Exception:
                pass
        elif prev_sigint is not None:
            try:
                signal.signal(signal.SIGINT, prev_sigint)
            except Exception:
                pass


def _install_win_proactor_pipe_fix() -> None:
    """Suppress benign CPython Windows ProactorEventLoop closed-pipe __del__ ValueError at interpreter shutdown."""
    if sys.platform != "win32":
        return
    try:
        from asyncio import proactor_events
        orig_del = getattr(proactor_events._ProactorBasePipeTransport, "__del__", None)
        if orig_del and not getattr(orig_del, "_nexus_safe", False):
            def _safe_del(self, _orig=orig_del):
                try:
                    _orig(self)
                except (ValueError, RuntimeError):
                    pass
            _safe_del._nexus_safe = True
            proactor_events._ProactorBasePipeTransport.__del__ = _safe_del
    except Exception:
        pass


def main():
    _install_win_proactor_pipe_fix()
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

