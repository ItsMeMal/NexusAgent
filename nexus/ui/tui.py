import os
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.text import Text
from rich.table import Table
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
    mode_id: str = "auto",
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
    from ..core.modes import get_mode
    mode_spec = get_mode(mode_id)
    console.print()
    console.print(f"  [bold #00ffd7]◈[/bold #00ffd7] [bold #38bdf8]Nexus Agent Orchestrator[/bold #38bdf8] [dim]·[/dim] [bold {mode_spec.color}]{mode_spec.icon} {mode_spec.label}[/bold {mode_spec.color}] [dim]· Autonomous Multi-Agent Engine[/dim]")
    console.print(f"  [dim]Router:[/dim] [bold #f59e0b]{provider_name}[/bold #f59e0b]  [dim]·[/dim]  [dim]Model:[/dim] [bold #22c55e]{model_name}[/bold #22c55e]  [dim]·[/dim]  [dim]Session:[/dim] [bold #38bdf8]{session_id}[/bold #38bdf8]")
    console.print(f"  [dim]Directory:[/dim] [dim white]{os.getcwd()}[/dim white]  [dim]·[/dim]  [dim]{tools_count} tools online · {skills_count} skills · SQLite+FTS5[/dim]")
    console.print("  [dim]─────────────────────────────────────────────────────────────────────────────[/dim]")
    console.print("  [dim]Type [bold #00ffd7]/[/bold #00ffd7] commands · [bold #00ffd7]Shift+Tab[/bold #00ffd7] or [bold #00ffd7]/mode[/bold #00ffd7] switch mode · [bold #00ffd7]/models[/bold #00ffd7] model · [bold #00ffd7]/provider[/bold #00ffd7] router · [dim red]exit[/dim red] quit[/dim]\n")

    if update_info and update_info.get("update_available"):
        render_update_alert(update_info)


_PRISM_THINK_PALETTE = [
    "#00ffd7", "#22d3ee", "#38bdf8", "#818cf8", "#a78bfa", "#e879f9", "#f472b6", "#fb7185",
    "#f472b6", "#e879f9", "#a78bfa", "#818cf8", "#38bdf8", "#22d3ee",
]
_PRISM_TOOL_PALETTE = [
    "#fbbf24", "#f59e0b", "#fb7185", "#f472b6", "#c084fc", "#38bdf8", "#00ffd7", "#22c55e",
    "#00ffd7", "#38bdf8", "#c084fc", "#f472b6", "#fb7185", "#f59e0b",
]
_SPARK_COLORS = ["#fbbf24", "#f472b6", "#00ffd7", "#a78bfa", "#38bdf8", "#fb7185"]

# Piko-Core: squishy, bouncing, multi-color chibi cyber-mochi mascot (every row strictly 19 cells)
_PIKO_THINK_FRAMES = [
    # (row0_aura, l_pad, dome_dashes, paw_l, inner_face_parts, paw_r, bot_mid, r_pad)
    # inner_face_parts: (l_cheek, eye_l, mouth, eye_r, r_cheek)
    ("     ·  ✦  ✧ ·     ", 4, 9, "╭┤", (" ", "◉", "  ◡  ", "◉", " "), "├╮", "───◈───", 4),
    ("    ✧  ·   ✦  ·    ", 4, 9, "╭┤", (" ", "◉", "  ◡  ", "◉", " "), "├╮", "──◈─◈──", 4),
    ("      ✦  ∘  ✧      ", 5, 9, "╭┤", (" ", "◉", " ◡ ", "◉", "  *"), "├╮", "──◈──◈─", 3),  # sway right
    ("                   ", 3, 11, "╭┤", (" ", "•", "   ◡   ", "•", " "), "├╮", "────◈────", 3),  # squish bounce!
    ("    ✦   ·   ✧ ·    ", 4, 9, "╰┤", ("*", "^", "  ◡  ", "^", "*"), "├╯", "──◈─◈──", 4),  # happy blink + blush
    ("      ✧  ∘  ✦      ", 3, 9, "╭┤", ("*  ", "◉", " ◡ ", "◉", " "), "├╮", "─◈──◈──", 5),  # sway left
    ("   ✦   ✧ ◈ ✧   ✦   ", 4, 9, "╰┤", (" ", "✦", "  ▽  ", "✦", " "), "├╯", "──═══──", 4),  # eureka jump!
    ("     ·  ✧  ✦ ·     ", 4, 9, "╭┤", (" ", "◉", "  ω  ", "◉", " "), "├╮", "──═◈═──", 4),
]

_PIKO_TOOL_FRAMES = [
    ("    ▲  ✦ ◈ ✦  ▲    ", 4, 9, "╰┤", (" ", "▸", "  ◡  ", "▸", " "), "├╯", "─▓▒◈▒▓─", 4),
    ("                   ", 3, 11, "╭┤", (" ", "◈", "   ▽   ", "◈", " "), "├╮", "─▒▓█◈█▓▒─", 3),  # squish bounce
    ("    ▼  ✧ ◈ ✧  ▼    ", 4, 9, "╰┤", ("*", "▸", "  ω  ", "▸", "*"), "├╯", "─░▒▓▒░─", 4),
    ("      ✦  ◈  ✦      ", 4, 9, "╭┤", (" ", "◈", "  ◡  ", "◈", " "), "├╮", "─▓▒█▒▓─", 4),
]

_MASCOT_SPINNERS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _append_prism_chars(txt: Text, s: str, palette: list, offset: int, bold: bool = True) -> None:
    """Append a string with flowing multi-color gradient across characters."""
    for idx, ch in enumerate(s):
        color = palette[(idx + offset) % len(palette)]
        txt.append(ch, style=f"bold {color}" if bold else color)


def build_nexus_mascot_renderable(
    frame_idx: int,
    elapsed: float,
    message: str = "Thinking & coordinating...",
    model_name: str = "",
    width: int = 100,
    mode_id: str = "auto",
):
    """Build a vibrant multi-color animated Piko-Core Mascot + live telemetry widget for Rich Live."""
    msg_low = (message or "").lower()
    is_tool = msg_low.startswith("executing") or "tool" in msg_low
    is_synth = "synth" in msg_low

    frames = _PIKO_TOOL_FRAMES if is_tool else _PIKO_THINK_FRAMES
    row0, l_pad, dash_cnt, paw_l, face_parts, paw_r, bot_mid, r_pad = frames[frame_idx % len(frames)]
    l_cheek, eye_l, mouth, eye_r, r_cheek = face_parts
    spin = _MASCOT_SPINNERS[frame_idx % len(_MASCOT_SPINNERS)]
    palette = _PRISM_TOOL_PALETTE if is_tool else _PRISM_THINK_PALETTE

    # Compact 1-line multi-color fallback for ultra-narrow terminals
    if width < 64:
        t = Text()
        t.append("  ")
        t.append(paw_l, style="bold #f472b6")
        t.append(eye_l, style="bold #00ffd7")
        t.append(mouth.strip(), style="bold #fbbf24")
        t.append(eye_r, style="bold #00ffd7")
        t.append(paw_r, style="bold #a78bfa")
        t.append(f" {spin} {message[:26]} ", style="bold #38bdf8")
        t.append(f"({elapsed:.1f}s)", style="dim")
        return t

    if is_tool:
        badge_text = " EXECUTING "
        badge_style = "bold #11111b on #f59e0b"
        eye_c = "bold #fef08a"
        mouth_c = "bold #fb7185"
        paw_l_c = "bold #fb923c"
        paw_r_c = "bold #f472b6"
    elif is_synth:
        badge_text = " SYNTHESIZING "
        badge_style = "bold #11111b on #c084fc"
        eye_c = "bold #ffffff"
        mouth_c = "bold #f472b6"
        paw_l_c = "bold #00ffd7"
        paw_r_c = "bold #a78bfa"
    else:
        badge_text = " THINKING "
        badge_style = "bold #11111b on #00ffd7"
        eye_c = "bold #ffffff" if eye_l in ("✦", "^") else "bold #67e8f9"
        mouth_c = "bold #fbbf24" if "▽" in mouth else "bold #f472b6"
        paw_l_c = "bold #f472b6"
        paw_r_c = "bold #38bdf8"

    # Column 1: 4-line fixed 19-char wide Multi-Color Piko-Core Mascot
    mascot = Text()

    # Row 0: twinkling multi-color aura stars
    for i, ch in enumerate(row0):
        if ch == " ":
            mascot.append(" ")
        elif ch == "◈":
            mascot.append(ch, style="bold #00ffd7")
        elif ch in ("✦", "✧", "▲", "▼"):
            mascot.append(ch, style=f"bold {_SPARK_COLORS[(i + frame_idx) % len(_SPARK_COLORS)]}")
        else:
            mascot.append(ch, style=_SPARK_COLORS[(i + frame_idx + 2) % len(_SPARK_COLORS)])
    mascot.append("\n")

    # Row 1: flowing holographic dome
    mascot.append(" " * l_pad)
    _append_prism_chars(mascot, "╭" + ("─" * dash_cnt) + "╮", palette, frame_idx)
    mascot.append(" " * r_pad + "\n")

    # Row 2: pastel paws + glowing eyes + rosy cheeks + cute mouth
    mascot.append(" " * max(0, l_pad - 1))
    mascot.append(paw_l, style=paw_l_c)
    mascot.append(l_cheek, style="bold #fb7185" if "*" in l_cheek else "")
    mascot.append(eye_l, style=eye_c)
    mascot.append(mouth, style=mouth_c)
    mascot.append(eye_r, style=eye_c)
    mascot.append(r_cheek, style="bold #fb7185" if "*" in r_cheek else "")
    mascot.append(paw_r, style=paw_r_c)
    mascot.append(" " * max(0, r_pad - 1) + "\n")

    # Row 3: prism belly + rainbow core + cute feet
    mascot.append(" " * l_pad)
    mascot.append("╰┴", style=f"bold {palette[frame_idx % len(palette)]}")
    _append_prism_chars(mascot, bot_mid, palette, frame_idx + 3)
    mascot.append("┴╯", style=f"bold {palette[(frame_idx + 6) % len(palette)]}")
    mascot.append(" " * r_pad)

    # Column 2: 4-line telemetry + prism wave bar aligned alongside Piko-Core
    model_short = (model_name.split("/")[-1] if "/" in model_name else model_name) or "nexus"
    if len(model_short) > 28:
        model_short = model_short[:25] + "..."

    bar_len = 24
    cycle = bar_len * 2 - 2
    pos = frame_idx % cycle
    if pos >= bar_len:
        pos = cycle - pos

    from ..core.modes import get_mode
    mode_spec = get_mode(mode_id)

    info = Text()
    info.append("◈ NEXUS ", style="bold #00ffd7")
    info.append("PIKO ", style="bold #f472b6")
    info.append(badge_text, style=badge_style)
    info.append(f"  {mode_spec.icon} {mode_spec.label}", style=f"bold {mode_spec.color}")
    info.append(f"  ·  {model_short}\n", style="dim #94a3b8")

    clean_msg = message if len(message) <= 44 else message[:41] + "..."
    info.append(f"{spin} ", style=f"bold {_SPARK_COLORS[frame_idx % len(_SPARK_COLORS)]}")
    info.append(f"{clean_msg}\n", style="bold white")

    info.append("[", style="dim #475569")
    for i in range(bar_len):
        dist = abs(i - pos)
        if dist == 0:
            info.append("✦", style="bold #ffffff")
        elif dist <= 2:
            info.append("━", style=f"bold {palette[(i + frame_idx) % len(palette)]}")
        elif dist <= 5:
            info.append("━", style=palette[(i + frame_idx) % len(palette)])
        else:
            info.append("─", style="#334155")
    info.append("]\n", style="dim #475569")

    info.append(f"◷ {elapsed:4.1f}s", style="bold #38bdf8")
    info.append("  ·  ", style="dim")
    info.append("Esc / Ctrl+C to interrupt", style="dim #94a3b8")

    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_row(mascot, info)
    return grid

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
        "📁 File Operations": ["read_file", "write_file", "append_file", "patch_file", "list_dir", "search_files"],
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

def render_status_card(model_name: str, provider_name: str, session_id: str, tools_count: int, skills_count: int, mem_count: int, cron_count: int, mode_id: str = "auto"):
    """Render system diagnostics overview."""
    from ..core.modes import get_mode
    mode_spec = get_mode(mode_id)
    console.print("\n  [bold #00ffd7]◈ Nexus System Diagnostic Overview[/bold #00ffd7]\n")
    console.print(f"    [dim]Agent Mode:[/dim]        [bold {mode_spec.color}]{mode_spec.icon} {mode_spec.label}[/bold {mode_spec.color}] [dim]({mode_spec.short_desc})[/dim]")
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
    """Render configured & running Model Context Protocol (MCP) servers."""
    console.print("\n  [bold #38bdf8]🔌 Model Context Protocol (MCP) Servers[/bold #38bdf8]\n")
    if not servers:
        console.print("  [dim]No external MCP servers configured yet.[/dim]")
        console.print("  [dim]Run [bold #00ffd7]/mcp add[/bold #00ffd7] for interactive setup (GitHub, Playwright, Remote HTTP/SSE, Custom).[/dim]\n")
        return
    for s in servers:
        if isinstance(s, dict):
            name = s.get("name", "?")
            transport = s.get("transport", "stdio").upper()
            cmd = s.get("command", "")
            status = s.get("status", "configured")
            tool_count = s.get("tools", 0)
            tool_names = s.get("tool_names", [])
            err = s.get("error", "")
            badge_map = {
                "running": f"[green][RUNNING · {transport} · {tool_count} tools][/green]",
                "error": f"[red][ERROR · {transport}][/red]",
                "disabled": f"[dim][DISABLED · {transport}][/dim]",
                "configured": f"[yellow][CONFIGURED · {transport} · {tool_count} tools][/yellow]",
            }
            badge = badge_map.get(status, f"[dim][{status.upper()}][/dim]")
            console.print(f"  [bold #00ffd7]● {name}[/bold #00ffd7] {badge}")
            console.print(f"    [dim]Target:[/dim]  [white]{cmd}[/white]")
            if tool_names:
                preview = ", ".join(tool_names[:8]) + (f" (+{len(tool_names) - 8} more)" if len(tool_names) > 8 else "")
                console.print(f"    [dim]Tools:[/dim]   [cyan]{preview}[/cyan]")
            if err:
                console.print(f"    [dim]Error:[/dim]   [red]{err}[/red]")
            console.print()
        else:
            status_color = "green" if s.active else "dim"
            console.print(f"  [bold #00ffd7]● {s.name}[/bold #00ffd7] [{status_color}][ACTIVE][/{status_color}]")
            console.print(f"    [dim]Command:[/dim] [white]{s.command} {' '.join(s.args)}[/white]\n")
    console.print("  [dim]Commands: [bold #00ffd7]/mcp add[/bold #00ffd7] · [bold #00ffd7]/mcp reload[/bold #00ffd7] · [bold #00ffd7]/mcp remove <name>[/bold #00ffd7][/dim]\n")

def render_plugins_table(plugins: list):
    """Render modular extension plugins."""
    console.print("\n  [bold #00ffd7]🧩 Installed Extension Plugins[/bold #00ffd7] [dim](plugins/)[/dim]\n")
    if not plugins:
        console.print("  [dim]No custom plugins in plugins/ directory.[/dim]")
        console.print("  [dim]Create a plugin folder with [plugin.json] to load custom tools & agents.[/dim]\n")
        return
    for p in plugins:
        extra = f" · [cyan]{p.skills_count} skills[/cyan]" if getattr(p, "skills_count", 0) else ""
        console.print(f"  [bold #22c55e]● {p.name}[/bold #22c55e] [dim]v{p.version} by {p.author}[/dim]{extra}")
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





