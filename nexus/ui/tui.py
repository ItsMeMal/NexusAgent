import os
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.text import Text
from rich.markdown import Markdown
from typing import Dict, Any, Optional

console = Console()

RAW_LOGO = [
    "███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗",
    "████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝",
    "██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗",
    "██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║",
    "██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║",
    "╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝"
]

GRADIENT_COLORS = ["#00ffd7", "#00d7af", "#38bdf8", "#60a5fa", "#818cf8", "#a78bfa"]

def render_banner(
    model_name: str,
    session_id: str,
    skills_count: int,
    tools_count: int,
    provider_name: str = "OpenRouter",
    animate: bool = True,
    update_info: Optional[Dict[str, Any]] = None,
    **kwargs
):
    """Render a cyberpunk welcome banner with interactive laser shimmer and bootloader."""
    # 1. Cyberpunk laser shimmer wave across ASCII logo
    if animate:
        width = len(RAW_LOGO[0])
        with Live(console=console, refresh_per_second=30, transient=True) as live:
            for wave in range(-6, width + 10, 2):
                t = Text()
                for row in RAW_LOGO:
                    for col_idx, char in enumerate(row):
                        dist = abs(col_idx - wave)
                        if dist <= 2:
                            t.append(char, style="bold #ffffff")
                        elif dist <= 5:
                            t.append(char, style="bold #00ffd7")
                        elif dist <= 9:
                            t.append(char, style="bold #38bdf8")
                        else:
                            t.append(char, style="bold #4f46e5")
                    t.append("\n")
                live.update(t)
                time.sleep(0.016)

    # 2. Print final persistent glowing logo
    console.print()
    for idx, line in enumerate(RAW_LOGO):
        console.print(line, style=f"bold {GRADIENT_COLORS[idx]}")

    # 3. Animated diagnostic bootloader checklist
    if animate:
        steps = [
            ("SQLite Memory Engine (FTS5)", "Persistent cross-session memory online"),
            ("Dynamic Skills Engine", f"{skills_count} learned procedure(s) ready"),
            ("Multi-Agent Orchestrator", f"{tools_count} autonomous tools online · subagents ready"),
            ("Router Gateway", f"Connected: {provider_name}"),
        ]
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        with Live(console=console, refresh_per_second=24, transient=True) as live:
            for i, (name, detail) in enumerate(steps):
                for frame in range(3):
                    spin = spinners[frame % len(spinners)]
                    txt = Text()
                    txt.append("\n  [◈] Initializing Nexus Autonomous Core...\n\n", style="bold #38bdf8")
                    for done_i in range(i):
                        txt.append(f"    ✔ {steps[done_i][0]:<30} ", style="bold #22c55e")
                        txt.append(f"[dim]· {steps[done_i][1]}[/dim]\n")
                    txt.append(f"    {spin} {name:<30} ", style="bold #00ffd7")
                    txt.append("[dim yellow]initializing...[/dim yellow]\n")
                    live.update(txt)
                    time.sleep(0.03)

        for name, detail in steps:
            console.print(f"    [bold #22c55e]✔[/bold #22c55e] [white]{name:<30}[/white] [dim]· {detail}[/dim]")

    # 4. Status card & command hints
    console.print()
    console.print(f"  [bold #00ffd7]◈[/bold #00ffd7] [bold #38bdf8]Nexus Agent Orchestrator[/bold #38bdf8] [dim]· Autonomous Multi-Agent Engine[/dim]")
    console.print(f"  [dim]Router:[/dim] [bold #f59e0b]{provider_name}[/bold #f59e0b]  [dim]·[/dim]  [dim]Model:[/dim] [bold #22c55e]{model_name}[/bold #22c55e]  [dim]·[/dim]  [dim]Session:[/dim] [bold #38bdf8]{session_id}[/bold #38bdf8]")
    console.print(f"  [dim]Directory:[/dim] [dim white]{os.getcwd()}[/dim white]  [dim]·[/dim]  [dim]{tools_count} tools online · {skills_count} skills · SQLite+FTS5[/dim]")
    console.print("  [dim]─────────────────────────────────────────────────────────────────────────────[/dim]")
    console.print("  [dim]Type [bold #00ffd7]/[/bold #00ffd7] for command palette · [bold #00ffd7]/models[/bold #00ffd7] to switch model · [bold #00ffd7]/provider[/bold #00ffd7] to connect router · [dim red]exit[/dim red] to quit[/dim]\n")

    if update_info and update_info.get("update_available"):
        render_update_alert(update_info)

def render_tool_call(tool_name: str, arguments: Dict[str, Any]):
    """Compact, high-signal single-line tool call indicator."""
    arg_parts = []
    for k, v in arguments.items():
        val_str = str(v)
        if len(val_str) > 45:
            val_str = val_str[:42] + "..."
        arg_parts.append(f"{k}={repr(val_str)}")
    args_summary = ", ".join(arg_parts) if arg_parts else ""

    console.print(f"  [bold #f59e0b]⚙ {tool_name}[/bold #f59e0b] [dim]({args_summary})[/dim]")

def render_tool_result(tool_name: str, result: str, elapsed: float = 0.0):
    """Compact, high-signal tool result indicator with execution time."""
    lines = result.strip().splitlines()
    first_line = lines[0] if lines else "Done"
    if len(first_line) > 80:
        first_line = first_line[:77] + "..."
    
    total_lines = len(lines)
    suffix_parts = []
    if elapsed > 0:
        suffix_parts.append(f"{elapsed:.2f}s")
    if total_lines > 1:
        suffix_parts.append(f"{total_lines} lines")
    
    suffix = f" [dim]({' · '.join(suffix_parts)})[/dim]" if suffix_parts else ""
    console.print(f"  [bold #22c55e]✔ {tool_name}:[/bold #22c55e] [white]{first_line}[/white]{suffix}")

def render_subagent_event(event_type: str, message: str):
    """Clean indented indicator for subagent activity."""
    icons = {
        "start": "🤖",
        "thought": "💭",
        "tool_call": "⚙",
        "tool_result": "✔",
        "finish": "✨",
        "error": "❌"
    }
    icon = icons.get(event_type, "🤖")
    console.print(f"    [dim magenta]{icon} Subagent [{event_type}]:[/dim magenta] [white]{message[:95]}[/white]")

def render_memories_table(memories: list):
    console.print("\n  [bold #a78bfa]🧠 Persistent Memories[/bold #a78bfa] [dim](SQLite FTS5)[/dim]\n")
    if not memories:
        console.print("  [dim]Memory is currently empty.[/dim]\n")
        return
    for m in memories:
        cat = m.get("category", "general")
        key = m.get("key", "")
        content = m.get("content", "")
        updated = str(m.get("updated_at", ""))
        console.print(f"  [bold #f59e0b]#{key}[/bold #f59e0b] [dim #38bdf8][{cat}][/dim #38bdf8] [dim]· {updated}[/dim]")
        console.print(f"    [white]{content}[/white]\n")

def render_skills_table(skills: list):
    console.print("\n  [bold #00ffd7]⚡ Installed Skills[/bold #00ffd7] [dim](.skills/)[/dim]\n")
    if not skills:
        console.print("  [dim]No skills installed yet.[/dim]\n")
        return
    for s in skills:
        console.print(f"  [bold #22c55e]● {s.name}[/bold #22c55e] [dim]({s.file_path.name})[/dim]")
        console.print(f"    [white]{s.description}[/white]\n")

def render_cron_table(tasks: list):
    console.print("\n  [bold #38bdf8]⏰ Scheduled Automations[/bold #38bdf8] [dim](Background Cron)[/dim]\n")
    if not tasks:
        console.print("  [dim]No automations currently scheduled.[/dim]\n")
        return
    for t in tasks:
        tid = t.get("id", "")
        name = t.get("name", "")
        sched = t.get("schedule", "")
        instr = t.get("instruction", "")
        status = t.get("status", "active")
        status_color = "#22c55e" if status == "active" else "dim"
        console.print(f"  [bold white]#{tid} {name}[/bold white] [{status_color}][{status.upper()}][/{status_color}] [yellow]({sched})[/yellow]")
        console.print(f"    [dim]Task:[/dim] [white]{instr}[/white]\n")

def render_tools_table(tools: list):
    """Render comprehensive grouped tool directory."""
    groups = {
        "📁 File Operations": ["read_file", "write_file", "patch_file", "list_dir", "search_files"],
        "💻 Shell & Terminal": ["run_command"],
        "👁️ Multimodal Vision": ["view_image"],
        "🧠 Memory & Knowledge": ["store_memory", "recall_memory", "list_all_memories"],
        "⚡ Dynamic Skills": ["list_skills", "read_skill", "create_skill"],
        "🌐 Web & Live Research": ["web_search", "web_extract"],
        "⏰ Background Automations": ["schedule_task", "list_scheduled_tasks", "cancel_scheduled_task"],
        "🤖 Multi-Agent Orchestration": ["delegate_task"]
    }
    tool_map = {t.name: t.description for t in tools}

    console.print(f"\n  [bold #00ffd7]🛠 Autonomous Tool Registry[/bold #00ffd7] [dim]({len(tools)} tools online)[/dim]\n")
    for group_name, tool_names in groups.items():
        console.print(f"  [dim #94a3b8]{group_name}[/dim #94a3b8]")
        for name in tool_names:
            desc = tool_map.get(name, "Autonomous tool capability.")
            short_desc = desc.split(". ")[0].strip()
            if not short_desc.endswith("."):
                short_desc += "."
            console.print(f"    [bold #38bdf8]{name:<24}[/bold #38bdf8] [dim]→[/dim]  [white]{short_desc}[/white]")
        console.print()

def render_status_card(model_name: str, provider_name: str, session_id: str, tools_count: int, skills_count: int, mem_count: int, cron_count: int):
    """Render system diagnostics overview."""
    console.print("\n  [bold #00ffd7]◈ Nexus System Diagnostic Overview[/bold #00ffd7]\n")
    console.print(f"    [dim]Active Model:[/dim]      [bold #22c55e]{model_name}[/bold #22c55e]")
    console.print(f"    [dim]Inference Router:[/dim]  [bold #f59e0b]{provider_name}[/bold #f59e0b]")
    console.print(f"    [dim]Active Session:[/dim]    [bold #38bdf8]{session_id}[/bold #38bdf8]")
    console.print(f"    [dim]Working Directory:[/dim] [white]{os.getcwd()}[/white]")
    console.print(f"    [dim]Memory Engine:[/dim]     [cyan]SQLite + FTS5 Full-Text Search[/cyan] [dim]({mem_count} facts stored)[/dim]")
    console.print(f"    [dim]Learned Skills:[/dim]    [green]{skills_count} loaded from .skills/[/green]")
    console.print(f"    [dim]Tool Engine:[/dim]       [yellow]{tools_count} autonomous tools online[/yellow]")
    console.print(f"    [dim]Automations:[/dim]       [magenta]{cron_count} background tasks scheduled[/magenta]")
    console.print(f"    [dim]Multi-Agent:[/dim]       [bold #00ffd7]Subagent Hierarchy Active (delegate_task ready)[/bold #00ffd7]\n")

def render_config_table(cfg_dict: dict):
    """Render runtime settings and configuration."""
    console.print("\n  [bold #38bdf8]⚙ Active Runtime Configuration[/bold #38bdf8]\n")
    for k, v in cfg_dict.items():
        val_str = str(v)
        if "key" in k.lower() and len(val_str) > 8:
            val_str = val_str[:6] + "..." + val_str[-4:]
        console.print(f"    [bold #94a3b8]{k:<22}[/bold #94a3b8] [dim]│[/dim] [white]{val_str}[/white]")
    console.print()

def render_sessions_table(sessions: list, current_session: str):
    """Render past conversation sessions stored in SQLite."""
    console.print("\n  [bold #a78bfa]📂 Stored Conversation Sessions[/bold #a78bfa] [dim](SQLite)[/dim]\n")
    if not sessions:
        console.print("  [dim]No recorded sessions.[/dim]\n")
        return
    for s in sessions:
        sid = s.get("id", "")
        msgs = s.get("message_count", 0)
        updated = s.get("updated_at", "")
        is_cur = (sid == current_session)
        prefix = " ❯ " if is_cur else "   "
        style_cur = "bold #00ffd7" if is_cur else "bold white"
        tag = " [green][ACTIVE][/green]" if is_cur else ""
        console.print(f"{prefix}[{style_cur}]{sid}[/{style_cur}]{tag} [dim]· {msgs} messages · updated: {updated}[/dim]")
    console.print()

def render_mcp_table(servers: list):
    """Render configured Model Context Protocol servers."""
    console.print("\n  [bold #38bdf8]🔌 Model Context Protocol (MCP) Servers[/bold #38bdf8]\n")
    if not servers:
        console.print("  [dim]No external MCP servers configured yet.[/dim]")
        console.print("  [dim]Create [.mcp.json] or [mcp_servers.json] in workspace to connect stdio/SSE servers.[/dim]\n")
        return
    for s in servers:
        status_color = "green" if s.active else "dim"
        console.print(f"  [bold #00ffd7]● {s.name}[/bold #00ffd7] [{status_color}][ACTIVE][/{status_color}]")
        console.print(f"    [dim]Command:[/dim] [white]{s.command} {' '.join(s.args)}[/white]\n")

def render_plugins_table(plugins: list):
    """Render modular extension plugins."""
    console.print("\n  [bold #00ffd7]🧩 Installed Extension Plugins[/bold #00ffd7] [dim](plugins/)[/dim]\n")
    if not plugins:
        console.print("  [dim]No custom plugins in plugins/ directory.[/dim]")
        console.print("  [dim]Create a plugin folder with [plugin.json] to load custom tools & agents.[/dim]\n")
        return
    for p in plugins:
        console.print(f"  [bold #22c55e]● {p.name}[/bold #22c55e] [dim]v{p.version} by {p.author}[/dim]")
        console.print(f"    [white]{p.description}[/white]\n")

def render_security_card():
    """Render security policy and guardrail telemetry."""
    auto_approve = False
    try:
        from ..config import config
        auto_approve = bool(config.AUTO_APPROVE)
    except Exception:
        pass

    console.print("\n  [bold #00ffd7]🛡️ Nexus Security & Guardrail Policy[/bold #00ffd7]\n")
    console.print("    [bold #22c55e]✔ Destructive Command Interceptor:[/bold #22c55e] [green]ACTIVE[/green] [dim](Blocks rm -rf /, format, fork bombs, disk wipes)[/dim]")
    console.print("    [bold #22c55e]✔ Path Sandbox Guard:[/bold #22c55e]              [green]ACTIVE[/green] [dim](Blocks OS system files C:\\Windows, /etc, /bin)[/dim]")
    console.print("    [bold #22c55e]✔ Subagent Permission Boundary:[/bold #22c55e]     [green]ACTIVE[/green] [dim](Subagents run in scoped tool registries)[/dim]")
    console.print(f"    [bold #22c55e]✔ Auto-Approve Mode:[/bold #22c55e]                [yellow]{'ENABLED' if auto_approve else 'DISABLED (Safe Mode)'}[/yellow]")
    console.print("    [dim]Tip: Set NEXUS_AUTO_APPROVE=true in .env only if you want fully autonomous unattended execution.[/dim]\n")

def render_computer_card():
    """Render Computer Use GUI automation status and capabilities."""
    console.print("\n  [bold #00ffd7]🖥️ Nexus Computer Use (GUI Automation)[/bold #00ffd7]\n")
    try:
        import pyautogui
        w, h = pyautogui.size()
        x, y = pyautogui.position()
        console.print(f"    [bold #22c55e]✔ Automation Engine:[/bold #22c55e]   [green]ONLINE[/green] [dim](PyAutoGUI v{pyautogui.__version__})[/dim]")
        console.print(f"    [bold #22c55e]✔ Screen Resolution:[/bold #22c55e]   [white]{w}x{h}[/white]")
        console.print(f"    [bold #22c55e]✔ Cursor Position:[/bold #22c55e]     [white]({x}, {y})[/white]")
        console.print("    [bold #22c55e]✔ FailSafe Abort:[/bold #22c55e]      [green]ENABLED[/green] [dim](Move cursor to screen corner to abort)[/dim]")
    except Exception as e:
        console.print(f"    [bold yellow]! Automation Engine:[/bold yellow]   [yellow]HEADLESS / FALLBACK[/yellow] [dim]({e})[/dim]")

    from ..config import config
    console.print(f"    [bold #22c55e]✔ Screenshots Path:[/bold #22c55e]    [cyan]{config.SCREENSHOTS_DIR}[/cyan]")
    console.print("    [dim]Supported Actions: screenshot, mouse_move, left_click, right_click, double_click, drag, type, key, hotkey, scroll, app_launch[/dim]")
    console.print("    [dim]Tip: Ask Nexus e.g. 'Take a screenshot and see what window is open' or 'Click the search bar at [500, 200]'.[/dim]\n")

def render_update_alert(update_info: Dict[str, Any]):
    """Render an eye-catching update notification card in the CLI banner."""
    msg = update_info.get("message", "New engine release available")
    rem_sha = update_info.get("remote_sha", "latest")
    console.print(f"  [bold #f59e0b]⚡ UPDATE AVAILABLE:[/bold #f59e0b] [bold white]A newer version of Nexus Agent is available![/bold white]")
    console.print(f"    [dim]Latest commit:[/dim] [bold #00ffd7]{rem_sha}[/bold #00ffd7] [dim]· \"{msg}\"[/dim]")
    console.print(f"    [dim]Type [bold #22c55e]/update[/bold #22c55e] to upgrade engine directly from CLI.[/dim]\n")

def render_update_card(update_info: Optional[Dict[str, Any]]):
    """Render update status information."""
    if update_info and update_info.get("update_available"):
        rem_sha = update_info.get("remote_sha", "latest")
        msg = update_info.get("message", "New release available")
        console.print(f"\n  [bold #f59e0b]⚡ UPDATE AVAILABLE:[/bold #f59e0b] [bold white]A newer version of Nexus Agent is available![/bold white]")
        console.print(f"    [dim]Current local:[/dim] [white]{update_info.get('local_sha', 'unknown')}[/white]")
        console.print(f"    [dim]Latest remote:[/dim] [bold #00ffd7]{rem_sha}[/bold #00ffd7]")
        console.print(f"    [dim]Commit:[/dim]        [dim]\"{msg}\"[/dim]")
        console.print(f"    [dim]Run:[/dim]           [bold #22c55e]/update[/bold #22c55e] to install updates.\n")
    else:
        console.print("\n  [bold #22c55e]✔ Nexus Agent is up to date![/bold #22c55e]")
        console.print("  [dim]You are running the latest version from GitHub main.[/dim]\n")

def render_gateway_card(statuses: list):
    """Render unified messaging gateway status card (Telegram, Discord, WhatsApp)."""
    console.print("\n  [bold #00ffd7]🌐 Nexus Messaging Gateways (Hermes-Style Bridge)[/bold #00ffd7]\n")
    icons = {"telegram": "✈️", "discord": "🎮", "whatsapp": "💬"}
    for st in statuses:
        icon = icons.get(st.platform.lower(), "📡")
        name = st.platform.capitalize()
        if st.running:
            badge = "[bold #22c55e][ONLINE][/bold #22c55e]"
        elif st.configured:
            badge = "[bold #f59e0b][CONFIGURED · IDLE][/bold #f59e0b]"
        else:
            badge = "[dim][NOT CONFIGURED][/dim]"

        id_str = f" [bold #00ffd7]{st.identity}[/bold #00ffd7]" if st.identity else ""
        mode_str = f" [dim]({st.mode})[/dim]" if st.mode else ""
        console.print(f"  {icon} [bold white]{name:<10}[/bold white] {badge}{id_str}{mode_str}")

        sec_policy = "Allow-All (Open)" if st.allow_all else (
            f"Allow-list ({st.allowed_users_count} user/number)" if st.allowed_users_count > 0 else "Locked (0 allowed · add IDs in .env)"
        )
        if st.configured or st.running:
            console.print(f"     [dim]Security:[/dim] [white]{sec_policy}[/white]  [dim]| Handled:[/dim] [cyan]{st.messages_handled}[/cyan]")
        if st.last_error:
            console.print(f"     [bold red]Last Error:[/bold red] [red]{st.last_error}[/red]")

    console.print("\n  [dim]Commands:[/dim]")
    console.print("    [bold #38bdf8]/gateway setup[/bold #38bdf8]          [dim]Interactive setup wizard for Telegram / Discord / WhatsApp[/dim]")
    console.print("    [bold #38bdf8]/gateway start \\[all|name][/bold #38bdf8] [dim]Start configured gateways in background[/dim]")
    console.print("    [bold #38bdf8]/gateway stop \\[all|name][/bold #38bdf8]  [dim]Stop running gateways[/dim]")
    console.print("    [bold #38bdf8]nexus --gateway[/bold #38bdf8]         [dim]Run standalone headless gateway daemon[/dim]\n")





