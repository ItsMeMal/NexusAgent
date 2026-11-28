import os
import re
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.text import Text
from rich.table import Table
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from typing import Dict, Any, Optional

console = Console()

LOGO_GLYPHS = {
    "N": (
        "███╗   ██╗",
        "████╗  ██║",
        "██╔██╗ ██║",
        "██║╚██╗██║",
        "██║ ╚████║",
        "╚═╝  ╚═══╝",
    ),
    "O": (
        " ██████╗",
        "██╔═══██╗",
        "██║   ██║",
        "██║   ██║",
        "╚██████╔╝",
        " ╚═════╝",
    ),
    "L": (
        "██╗",
        "██║",
        "██║",
        "██║",
        "███████╗",
        "╚══════╝",
    ),
    "T": (
        "████████╗",
        "╚══██╔══╝",
        "   ██║",
        "   ██║",
        "   ██║",
        "   ╚═╝",
    ),
    "H": (
        "██╗  ██╗",
        "██║  ██║",
        "███████║",
        "██╔══██║",
        "██║  ██║",
        "╚═╝  ╚═╝",
    ),
    "I": (
        "╔══════╗",
        "   ║║   ",
        "   ║║   ",
        "   ║║   ",
        "   ║║   ",
        "╚══════╝",
    ),
    "R": (
        "██████╗",
        "██╔══██╗",
        "██████╔╝",
        "██╔══██╗",
        "██║  ██║",
        "╚═╝  ╚═╝",
    ),
    "A": (
        " █████╗",
        "██╔══██╗",
        "███████║",
        "██╔══██║",
        "██║  ██║",
        "╚═╝  ╚═╝",
    ),
}


def _compose_logo(word: str, gap: int = 1) -> list[str]:
    """Compose a wordmark using the original outlined block/ANSI glyph style."""
    if not word or any(letter not in LOGO_GLYPHS for letter in word):
        raise ValueError("Logo word contains an unsupported character.")

    glyphs = [LOGO_GLYPHS[letter] for letter in word]
    row_count = len(glyphs[0])
    if any(len(glyph) != row_count for glyph in glyphs):
        raise ValueError("Logo glyphs must have the same number of rows.")

    widths = [max(len(row) for row in glyph) for glyph in glyphs]
    return [
        (" " * gap).join(
            glyph[row_index].ljust(width)
            for glyph, width in zip(glyphs, widths)
        )
        for row_index in range(row_count)
    ]


RAW_LOGO = _compose_logo("NOLTHIRA")

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
        width = max(len(line) for line in RAW_LOGO)
        target_sweep_frames = 30
        wave_step = max(2, round((width + 16) / target_sweep_frames))
        with Live(console=console, refresh_per_second=30, transient=True) as live:
            for wave in range(-6, width + 10, wave_step):
                t = Text()
                for row in RAW_LOGO:
                    for col_idx, char in enumerate(row.ljust(width)):
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
        row_color = GRADIENT_COLORS[min(idx, len(GRADIENT_COLORS) - 1)]
        console.print(line, style=f"bold {row_color}")

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
                    txt.append("\n  [◈] Initializing Nolthira Autonomous Core...\n\n", style="bold #38bdf8")
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
    console.print(f"  [bold #00ffd7]◈[/bold #00ffd7] [bold #38bdf8]Nolthira Agent Orchestrator[/bold #38bdf8] [dim]·[/dim] [bold {mode_spec.color}]{mode_spec.icon} {mode_spec.label}[/bold {mode_spec.color}] [dim]· Autonomous Multi-Agent Engine[/dim]")
    console.print(f"  [dim]Router:[/dim] [bold #f59e0b]{provider_name}[/bold #f59e0b]  [dim]·[/dim]  [dim]Model:[/dim] [bold #22c55e]{model_name}[/bold #22c55e]  [dim]·[/dim]  [dim]Session:[/dim] [bold #38bdf8]{session_id}[/bold #38bdf8]")
    console.print(f"  [dim]Directory:[/dim] [dim white]{os.getcwd()}[/dim white]  [dim]·[/dim]  [dim]{tools_count} tools online · {skills_count} skills · SQLite+FTS5[/dim]")
    console.print("  [dim]─────────────────────────────────────────────────────────────────────────────[/dim]")
    console.print("  [dim]Type [bold #00ffd7]/[/bold #00ffd7] commands · [bold #00ffd7]Shift+Tab[/bold #00ffd7] or [bold #00ffd7]/mode[/bold #00ffd7] switch mode · [bold #00ffd7]/models[/bold #00ffd7] model · [bold #00ffd7]/provider[/bold #00ffd7] router · [dim red]exit[/dim red] quit[/dim]\n")

    if update_info and update_info.get("update_available"):
        render_update_alert(update_info)
    elif update_info and update_info.get("check_error"):
        console.print(
            f"  [dim yellow]Update check unavailable: {update_info['check_error']}[/dim yellow]"
        )


def build_nolthira_mascot_renderable(
    frame_idx: int,
    elapsed: float,
    message: str = "Thinking & coordinating...",
    model_name: str = "",
    width: int = 100,
    mode_id: str = "auto",
):
    """Render Piko True-Color Pixel Sprite + live telemetry widget for Rich Live."""
    from .mascot import build_piko_renderable
    return build_piko_renderable(
        frame_idx=frame_idx,
        elapsed=elapsed,
        message=message,
        model_name=model_name,
        width=width,
        mode_id=mode_id,
    )

_ACTIVITY_SECRET_LITERAL_RE = re.compile(
    r"""(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|private[_-]?key|database_url|connection_string|authorization)\b\s*[:=]\s*)(["'])(.*?)(\2)""",
    re.MULTILINE,
)
_ACTIVITY_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_ACTIVITY_TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})\b")


def _redact_activity_text(value: Any) -> str:
    """Redact common credential literals before showing tool payloads or output."""
    text = str(value or "")
    text = _ACTIVITY_SECRET_LITERAL_RE.sub(r"\1[REDACTED]", text)
    text = _ACTIVITY_BEARER_RE.sub("Bearer [REDACTED]", text)
    return _ACTIVITY_TOKEN_RE.sub("[REDACTED]", text)


def _render_activity_source(title: str, path: str, source: str, border_style: str = "cyan") -> None:
    """Render complete source text with syntax highlighting and line numbers."""
    safe_source = _redact_activity_text(source)
    if not safe_source:
        return
    try:
        lexer = Syntax.guess_lexer(path or "text")
        body = Syntax(
            safe_source,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=False,
            indent_guides=True,
        )
    except Exception:
        body = Text(safe_source, no_wrap=False)
    line_count = safe_source.count("\n") + (0 if safe_source.endswith("\n") else 1)
    console.print(
        Panel(
            body,
            title=f"[bold]{title}[/bold]",
            subtitle=f"{line_count} line(s) · full payload",
            border_style=border_style,
            expand=True,
        )
    )


def render_tool_call(tool_name: str, arguments: Dict[str, Any]):
    """Show complete coding payloads while keeping ordinary tool calls compact."""
    args = arguments if isinstance(arguments, dict) else {}
    normalized = str(tool_name or "").strip().lower()

    # Large source fields are rendered in dedicated syntax-highlighted panels,
    # never hidden inside a truncated one-line argument summary.
    hidden_fields = {"content", "target", "replacement", "command", "updates"}
    arg_parts = []
    for key, value in args.items():
        if key in hidden_fields:
            continue
        shown = "[REDACTED]" if re.search(
            r"(?i)(api[_-]?key|token|secret|password|authorization)", str(key)
        ) else _redact_activity_text(value)
        if isinstance(shown, (dict, list)):
            shown = "[structured value]"
        shown_text = str(shown)
        if len(shown_text) > 100:
            shown_text = shown_text[:97] + "..."
        arg_parts.append(f"{key}={shown_text!r}")

    if normalized == "update_env" and "updates" in args:
        arg_parts.append("updates='<values hidden>'")

    args_summary = ", ".join(arg_parts) if arg_parts else ""
    console.print(
        f"  [bold #f59e0b]⚙ {tool_name}[/bold #f59e0b] [dim]({args_summary})[/dim]"
    )

    if normalized in {"write_file", "append_file"}:
        path = str(args.get("path") or "<unknown path>")
        source = str(args.get("content") or "")
        title = "WRITE" if normalized == "write_file" else "APPEND"
        _render_activity_source(f"{title} · {path}", path, source, "green" if normalized == "write_file" else "cyan")
    elif normalized == "patch_file":
        path = str(args.get("path") or "<unknown path>")
        _render_activity_source(f"PATCH BEFORE · {path}", path, str(args.get("target") or ""), "red")
        _render_activity_source(f"PATCH AFTER · {path}", path, str(args.get("replacement") or ""), "green")
    elif normalized in {"run_command", "shell", "bash", "cmd", "terminal"}:
        command = _redact_activity_text(args.get("command") or "")
        if command:
            console.print(
                Panel(
                    Text(command, no_wrap=False, overflow="fold"),
                    title="[bold]COMMAND[/bold]",
                    border_style="yellow",
                    expand=True,
                )
            )


def render_tool_result(tool_name: str, result: str, elapsed: float = 0.0):
    """Show full read/command output; keep small routine results compact."""
    safe_result = _redact_activity_text(result)
    lines = safe_result.strip().splitlines()
    first_line = lines[0] if lines else "Done"

    suffix_parts = []
    if elapsed > 0:
        suffix_parts.append(f"{elapsed:.2f}s")
    if len(lines) > 1:
        suffix_parts.append(f"{len(lines)} lines")
    suffix = f" [dim]({' · '.join(suffix_parts)})[/dim]" if suffix_parts else ""

    console.print(
        f"  [bold #22c55e]✔ {tool_name}:[/bold #22c55e] [white]{first_line[:120]}[/white]{suffix}"
    )

    normalized = str(tool_name or "").strip().lower()
    if normalized in {"read_file", "run_command", "process"} and safe_result.strip():
        console.print(
            Panel(
                Text(safe_result, no_wrap=False, overflow="fold"),
                title=f"[bold]{normalized.upper()} OUTPUT[/bold]",
                border_style="blue",
                expand=True,
            )
        )

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
    import datetime as _dt
    console.print("\n  [bold #38bdf8]⏰ Scheduled Automations[/bold #38bdf8] [dim](Background Cron Runner)[/dim]\n")
    if not tasks:
        console.print("  [dim]No automations currently scheduled.[/dim]\n")
        return
    for t in tasks:
        tid = t.get("id", "")
        name = t.get("name", "")
        sched = t.get("schedule", "")
        instr = t.get("instruction", "")
        status = t.get("status", "active")
        mode = t.get("mode", "agent")
        run_cnt = t.get("run_count", 0) or 0
        nxt = t.get("next_run")
        nxt_str = ""
        if nxt and status == "active":
            try:
                nxt_str = f" · next: {_dt.datetime.fromtimestamp(float(nxt)).strftime('%H:%M:%S')}"
            except Exception:
                pass
        status_color = "#22c55e" if status == "active" else ("#38bdf8" if status == "completed" else "dim")
        console.print(f"  [bold white]#{tid} {name}[/bold white] [{status_color}][{status.upper()}][/{status_color}] [yellow]({sched} · {mode})[/yellow] [dim]runs:{run_cnt}{nxt_str}[/dim]")
        console.print(f"    [dim]Task:[/dim] [white]{instr}[/white]")
        if t.get("last_result"):
            preview = str(t["last_result"]).replace("\n", " ")[:100]
            console.print(f"    [dim]Last:[/dim] [cyan]{preview}[/cyan]")
        console.print()

def render_tools_table(tools: list):
    """Render comprehensive grouped tool directory."""
    groups = {
        "📁 File Operations": ["read_file", "write_file", "append_file", "patch_file", "list_dir", "search_files"],
        "💻 Shell & Terminal": ["run_command"],
        "👁️ Multimodal Vision & Media": ["view_image", "image_generate", "text_to_speech"],
        "🧠 Memory & Knowledge": ["store_memory", "recall_memory", "list_all_memories", "session_search"],
        "⚡ Dynamic Skills": ["list_skills", "read_skill", "create_skill"],
        "🌐 Web & Browser Automation": ["web_search", "web_extract", "browser"],
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

def render_token_usage(usage: Dict[str, Any]) -> None:
    """Show provider usage or clearly labeled estimates and known context remaining."""
    if not usage:
        return

    def fmt(value: Any) -> str:
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "—"

    source = str(usage.get("source", "unavailable"))
    label = "API-reported" if source in {"provider", "api_reported"} else ("estimated" if source.startswith("estimated") else "unavailable")
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
    context_window = int(usage.get("context_window", 0) or 0)
    console.print(
        f"  [dim]Tokens · {label}[/dim]  [white]Input {fmt(input_tokens)}[/white]  "
        f"[white]Output {fmt(output_tokens)}[/white]  [bold #00ffd7]Total {fmt(total_tokens)}[/bold #00ffd7]"
    )
    if context_window:
        remaining = max(0, context_window - total_tokens)
        remaining_pct = max(0.0, 100.0 - (total_tokens / context_window * 100.0))
        console.print(
            f"  [dim]Context[/dim] [white]{fmt(total_tokens)} / {fmt(context_window)}[/white] "
            f"[dim]· remaining {fmt(remaining)} ({remaining_pct:.1f}%)[/dim]"
        )
    else:
        console.print("  [dim]Context window unavailable for this model; remaining tokens are not guessed.[/dim]")
    session = usage.get("session")
    if isinstance(session, dict):
        console.print(
            f"  [dim]Session · input {fmt(session.get('input_tokens'))} · output {fmt(session.get('output_tokens'))} · "
            f"total {fmt(session.get('total_tokens'))} · {fmt(session.get('requests'))} request(s)[/dim]"
        )


def render_status_card(model_name: str, provider_name: str, session_id: str, tools_count: int, skills_count: int, mem_count: int, cron_count: int, mode_id: str = "auto"):
    """Render system diagnostics overview."""
    from ..core.modes import get_mode
    mode_spec = get_mode(mode_id)
    console.print("\n  [bold #00ffd7]◈ Nolthira System Diagnostic Overview[/bold #00ffd7]\n")
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
    """Render past conversation sessions stored in SQLite with readable titles."""
    console.print("\n  [bold #a78bfa]📂 Stored Conversation Sessions[/bold #a78bfa] [dim](SQLite)[/dim]\n")
    if not sessions:
        console.print("  [dim]No recorded sessions.[/dim]\n")
        return
    for s in sessions:
        sid = s.get("id", "")
        title = s.get("title") or f"Session {sid}"
        msgs = s.get("message_count", 0)
        updated = str(s.get("updated_at", ""))[:19]
        is_cur = (sid == current_session)
        prefix = " ❯ " if is_cur else "   "
        style_cur = "bold #00ffd7" if is_cur else "bold white"
        tag = " [green][ACTIVE][/green]" if is_cur else ""
        console.print(f"{prefix}[{style_cur}]{title}[/{style_cur}] [dim](#{sid})[/dim]{tag} [dim]· {msgs} msgs · {updated}[/dim]")
    console.print()


def render_resumed_history(history: list, session_id: str, title: str = "", max_turns: int = 12):
    """Render recent conversation turns cleanly when resuming a session so chat context is visible."""
    label = title or f"Session {session_id}"
    console.print(f"\n  [bold #22c55e]✔ Resumed:[/bold #22c55e] [bold #00ffd7]{label}[/bold #00ffd7] [dim](#{session_id} · {len(history)} msgs)[/dim]")
    visible = [
        m for m in history
        if m.get("role") in ("user", "assistant")
    ]
    if not visible:
        console.print("  [dim](No chat messages recorded in this session yet.)[/dim]\n")
        return

    console.print("  [dim]─── Recent Conversation History ─────────────────────────────────────────[/dim]")
    tail = visible[-max_turns:]
    skipped = len(visible) - len(tail)
    if skipped > 0:
        console.print(f"  [dim]... ({skipped} earlier turn(s) omitted; Nolthira still remembers full context)[/dim]\n")
    for m in tail:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        tool_calls = m.get("tool_calls") or []
        if role == "user":
            snippet = content if len(content) <= 280 else content[:277] + "..."
            console.print(f"  [bold #38bdf8]❯ You:[/bold #38bdf8] [white]{snippet}[/white]")
        elif role == "assistant":
            if content == "[calling tools]" or (not content and tool_calls):
                names = ", ".join((tc.get("function") or {}).get("name", "tool") for tc in tool_calls[:4])
                console.print(f"  [dim]  ⚙ Called tools: {names}[/dim]")
            elif content:
                snippet = content if len(content) <= 450 else content[:447] + "..."
                console.print(f"  [bold #00ffd7]◈ Nolthira:[/bold #00ffd7] [dim white]{snippet}[/dim white]\n")
    console.print("  [dim]─────────────────────────────────────────────────────────────────────────[/dim]\n")

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

    console.print("\n  [bold #00ffd7]🛡️ Nolthira Security & Guardrail Policy[/bold #00ffd7]\n")
    console.print("    [bold #22c55e]✔ Destructive Command Interceptor:[/bold #22c55e] [green]ACTIVE[/green] [dim](Blocks rm -rf /, format, fork bombs, disk wipes)[/dim]")
    console.print("    [bold #22c55e]✔ Path Sandbox Guard:[/bold #22c55e]              [green]ACTIVE[/green] [dim](Blocks OS system files C:\\Windows, /etc, /bin)[/dim]")
    console.print("    [bold #22c55e]✔ Subagent Permission Boundary:[/bold #22c55e]     [green]ACTIVE[/green] [dim](Subagents run in scoped tool registries)[/dim]")
    console.print(f"    [bold #22c55e]✔ Auto-Approve Mode:[/bold #22c55e]                [yellow]{'ENABLED' if auto_approve else 'DISABLED (Safe Mode)'}[/yellow]")
    console.print("    [dim]Tip: Only enable unattended execution in workspaces and tasks you trust.[/dim]\n")

def render_computer_card():
    """Render Computer Use GUI automation status and capabilities."""
    console.print("\n  [bold #00ffd7]🖥️ Nolthira Computer Use (GUI Automation)[/bold #00ffd7]\n")
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
    console.print("    [dim]Tip: Ask Nolthira e.g. 'Take a screenshot and see what window is open' or 'Click the search bar at [500, 200]'.[/dim]\n")

def render_update_alert(update_info: Dict[str, Any]):
    """Render an eye-catching update notification card in the CLI banner."""
    msg = update_info.get("message", "New engine release available")
    rem_sha = update_info.get("remote_sha", "latest")
    console.print(f"  [bold #f59e0b]⚡ UPDATE AVAILABLE:[/bold #f59e0b] [bold white]A newer version of Nolthira Agent is available![/bold white]")
    console.print(f"    [dim]Latest commit:[/dim] [bold #00ffd7]{rem_sha}[/bold #00ffd7] [dim]· \"{msg}\"[/dim]")
    console.print(f"    [dim]Type [bold #22c55e]/update[/bold #22c55e] to upgrade engine directly from CLI.[/dim]\n")

def render_update_card(update_info: Optional[Dict[str, Any]]):
    """Render update status information without masking check failures."""
    if update_info and update_info.get("check_error"):
        console.print(
            f"\n  [bold yellow]⚠ Could not check for updates:[/bold yellow] "
            f"{update_info['check_error']}\n"
        )
    elif update_info and update_info.get("update_available"):
        rem_sha = update_info.get("remote_sha", "latest")
        msg = update_info.get("message", "New release available")
        console.print(f"\n  [bold #f59e0b]⚡ UPDATE AVAILABLE:[/bold #f59e0b] [bold white]A newer version of Nolthira Agent is available![/bold white]")
        console.print(f"    [dim]Current local:[/dim] [white]{update_info.get('local_sha', 'unknown')}[/white]")
        console.print(f"    [dim]Latest remote:[/dim] [bold #00ffd7]{rem_sha}[/bold #00ffd7]")
        console.print(f"    [dim]Commit:[/dim]        [dim]\"{msg}\"[/dim]")
        console.print(f"    [dim]Run:[/dim]           [bold #22c55e]/update[/bold #22c55e] to install updates.\n")
    else:
        console.print("\n  [bold #22c55e]✔ Nolthira Agent is up to date![/bold #22c55e]")
        console.print("  [dim]You are running the latest version from GitHub main.[/dim]\n")

def render_gateway_card(statuses: list):
    """Render unified messaging gateway status card (Telegram, Discord, WhatsApp, Slack, Email)."""
    console.print("\n  [bold #00ffd7]🌐 Nolthira Messaging Gateways (Hermes-Style Bridge)[/bold #00ffd7]\n")
    icons = {"telegram": "✈️", "discord": "🎮", "whatsapp": "💬", "slack": "#️⃣", "email": "📧"}
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
    console.print("    [bold #38bdf8]nolthira --gateway[/bold #38bdf8]         [dim]Run standalone headless gateway daemon[/dim]\n")





