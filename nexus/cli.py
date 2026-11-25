import sys
import os
import asyncio
import argparse
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from .config import config
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
from .core import LLMClient, NexusAgent
from .ui import (
    render_banner,
    render_memories_table,
    render_skills_table,
    render_cron_table,
    render_tools_table,
    render_status_card,
    render_config_table,
    render_sessions_table,
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
    interactive_resume_session,
    interactive_gateway_setup,
    interactive_mcp_add,
    console
)

pt_style = Style.from_dict({
    'box-top': '#475569',
    'app-name': '#38bdf8 bold',
    'dim': '#64748b',
    'model-badge': '#22c55e bold',
    'box-bottom': '#00ffd7 bold',
    'completion-menu.completion': 'bg:#1e1e2e #cdd6f4',
    'completion-menu.completion.current': 'bg:#00d7af #11111b bold',
    'completion-menu.meta.completion': 'bg:#181825 #94a3b8',
    'completion-menu.meta.completion.current': 'bg:#00d7af #11111b',
})

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
    parser.add_argument("-s", "--session", type=str, help="Session ID to resume or use", default=None)
    parser.add_argument("-g", "--gateway", nargs="?", const="all", default=None, help="Run messaging gateway daemon (all|telegram|discord|whatsapp)")
    parser.add_argument("subcommand", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # Support `nexus gateway [all|telegram|discord|whatsapp]` positional syntax
    gateway_target = args.gateway
    if not gateway_target and args.subcommand and args.subcommand[0].lower() == "gateway":
        gateway_target = args.subcommand[1].lower() if len(args.subcommand) > 1 else "all"

    # Active configuration .env path (workspace override or global ~/.nexus/.env)
    env_path = config.ENV_PATH

    # Initialize subsystems
    memory = SQLiteMemory(config.MEMORY_DB_PATH)
    skill_manager = SkillManager(config.SKILLS_DIR)
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

    # Dedicated UI controller for collision-free live streaming & spinners
    ui_controller = AgentUIController(model_name=llm.model, console_instance=console)

    # Subagent orchestrator manager
    subagent_manager = SubagentManager(
        llm=llm,
        memory=memory,
        skill_manager=skill_manager,
        root_dir=config.ROOT_DIR,
        on_subagent_event=ui_controller.on_subagent_event
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
        llm_client=llm
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
        on_thought=ui_controller.on_thought,
        on_token=ui_controller.on_token,
        on_tool_call=ui_controller.on_tool_call,
        on_tool_result=ui_controller.on_tool_result
    )

    # Headless Messaging Gateway Daemon Mode (`nexus --gateway` / `nexus gateway`)
    if gateway_target:
        console.print(f"\n  [bold #00ffd7]🌐 Starting Nexus Gateway Daemon[/bold #00ffd7] [dim](target: {gateway_target})[/dim]")
        started = await gateway_manager.start_gateway(gateway_target)
        render_gateway_card(gateway_manager.get_statuses())
        if not any(v in ("started", "already_running") for v in started.values()):
            console.print("  [bold yellow]⚠ No configured gateways found for target.[/bold yellow] Run `nexus` and type `/gateway setup` first.\n")
            return
        console.print("  [bold #22c55e]✔ Gateway daemon active.[/bold #22c55e] [dim]Listening for Telegram/Discord/WhatsApp messages (Ctrl+C to stop)...[/dim]\n")
        try:
            while True:
                await asyncio.sleep(1.0)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("\n  [dim cyan]⠋ Shutting down messaging gateways...[/dim cyan]")
            await gateway_manager.stop_gateway("all")
            await mcp_manager.stop_all()
            console.print("  [bold #00ffd7]✔ Gateways offline.[/bold #00ffd7]\n")
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
        update_info=update_info
    )

    # Optional auto-start gateways if configured in .env
    if os.getenv("GATEWAY_AUTO_START", "false").lower() in ("true", "1", "yes"):
        try:
            await gateway_manager.start_gateway("all")
        except Exception:
            pass

    completer = NexusCommandCompleter()
    session = PromptSession(
        history=InMemoryHistory(),
        completer=completer,
        complete_while_typing=True
    )

    while True:
        try:
            session.is_password = False
            model_short = llm.model.split("/")[-1] if "/" in llm.model else llm.model
            prompt_fragments = [
                ('class:box-top', '╭─ '),
                ('class:app-name', 'nexus '),
                ('class:dim', '· '),
                ('class:model-badge', f'[{model_short}]'),
                ('class:box-bottom', '\n╰─❯ '),
            ]

            user_input = await session.prompt_async(prompt_fragments, style=pt_style, is_password=False)
            text = user_input.strip()
            if not text:
                continue

            if text.lower() in ("exit", "quit", "q"):
                await gateway_manager.stop_gateway("all")
                await mcp_manager.stop_all()
                console.print("\n  [dim cyan]⠋ Preserving orchestrator session & persistent memory (FTS5)...[/dim cyan]")
                await asyncio.sleep(0.25)
                console.print("  [bold #00ffd7]✔ Session preserved.[/bold #00ffd7] [dim]Nexus Orchestrator offline. Goodbye![/dim]\n")
                break

            # Handle slash commands & command palette
            if text == "/" or text.lower() in ("/help", "/?", "/commands", "/command"):
                render_command_palette()
                continue

            if text.startswith("/"):
                cmd = text.lower().split()[0]
                if cmd in ("/models", "/model"):
                    await interactive_select_model(session, llm, env_path)
                    ui_controller.update_model(llm.model)
                    continue
                elif cmd in ("/provider", "/providers", "/connect"):
                    await interactive_select_provider(session, llm, env_path)
                    ui_controller.update_model(llm.model)
                    continue
                elif cmd in ("/tools", "/tool"):
                    render_tools_table(tools)
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
                        cron_count=len(cron_tasks)
                    )
                    continue
                elif cmd in ("/config", "/env", "/settings"):
                    cfg_dict = {
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
                        console.print(f"\n  [bold #22c55e]✔ Resumed session:[/bold #22c55e] [bold #00ffd7]{target_id}[/bold #00ffd7] [dim]({len(history)} messages loaded)[/dim]\n")
                    else:
                        await interactive_resume_session(memory, current_session, agent)
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
                        update_info=up_info
                    )
                    continue
                elif cmd.startswith("/new"):
                    new_id = os.urandom(4).hex()
                    current_session[0] = new_id
                    agent.session_id = new_id
                    console.print("\n  [dim cyan]⠋ Initializing clean context session...[/dim cyan]")
                    await asyncio.sleep(0.2)
                    console.print(f"  [bold #22c55e]✨ Fresh session activated:[/bold #22c55e] [bold #00ffd7]{new_id}[/bold #00ffd7] [dim](memory isolated)[/dim]\n")
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

            # Smooth ReAct execution with live streaming and zero collision
            ui_controller.start_thinking()
            try:
                await agent.run(text)
            finally:
                ui_controller.finish_stream()

        except (KeyboardInterrupt, EOFError):
            ui_controller.stop_status()
            await gateway_manager.stop_gateway("all")
            await mcp_manager.stop_all()
            console.print("\n  [yellow]Session interrupted. Goodbye![/yellow]\n")
            break
        except Exception as e:
            ui_controller.stop_status()
            console.print(f"\n  [bold red]Error:[/bold red] {str(e)}\n")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

