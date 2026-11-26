import os
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from ..providers.manager import ProviderManager, ProviderProfile, ModelInfo, PROVIDERS
from ..config import config

console = Console()

SLASH_COMMANDS = [
    ("/models", "Select or search AI models (interactive arrow-key menu)", "Models"),
    ("/model", "Alias for /models", "Models"),
    ("/provider", "Select or switch router / provider (interactive arrow-key menu)", "Provider"),
    ("/connect", "Alias for /provider", "Provider"),
    ("/tools", "Inspect all active autonomous tools and their capabilities", "Tools"),
    ("/status", "Display agent system diagnostics and active telemetry", "Status"),
    ("/mcp", "Manage MCP servers — status, /mcp add, /mcp reload, /mcp remove <name>", "Tools"),
    ("/plugins", "View loaded modular plugins from plugins/ directory", "Plugins"),
    ("/github", "GitHub App — repos, PRs, issues, diff, comment, review (/github help)", "GitHub"),
    ("/team", "AI-Team — spawn & manage a team of specialized AI sub-agents (/team help)", "Team"),
    ("/gateway", "Configure or run Telegram, Discord & WhatsApp gateways (/gateway setup|start|stop)", "Gateway"),
    ("/bot", "Alias for /gateway", "Gateway"),
    ("/security", "View security guardrails, command sandbox & safety policy", "Security"),
    ("/computer", "Inspect GUI automation status or capture screenshot (/computer screenshot)", "Computer"),
    ("/update", "Check for updates and upgrade Nexus Agent engine from GitHub", "System"),
    ("/upgrade", "Alias for /update", "System"),
    ("/skills", "View loaded dynamic skills & learned procedures", "Skills"),
    ("/memory", "Inspect persistent facts stored in SQLite FTS5", "Memory"),
    ("/cron", "View scheduled background jobs and automations", "Background"),
    ("/sessions", "List past conversation sessions stored in SQLite", "Session"),
    ("/resume", "Browse and resume past conversation session (interactive arrow-key menu)", "Session"),
    ("/config", "View active runtime settings and configuration", "Utility"),
    ("/new", "Start a new clean session context", "Session"),
    ("/clear", "Clear terminal screen and show banner", "Utility"),
    ("/help", "Display command palette", "Utility"),
    ("exit", "Exit Nexus Agent CLI", "Utility"),
    ("quit", "Exit Nexus Agent CLI", "Utility"),
]

class NexusCommandCompleter(Completer):
    """Real-time autocompletion menu when typing slash commands."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if text.startswith("/"):
            for cmd, desc, category in SLASH_COMMANDS:
                if cmd.startswith(text):
                    yield Completion(
                        text=cmd,
                        start_position=-len(text),
                        display=f"{cmd:<12}",
                        display_meta=f"[{category}] {desc}"
                    )
        elif text == "":
            for cmd, desc, category in SLASH_COMMANDS:
                if cmd.startswith("/"):
                    yield Completion(
                        text=cmd,
                        start_position=0,
                        display=f"{cmd:<12}",
                        display_meta=f"[{category}] {desc}"
                    )

def render_command_palette():
    """Render a clean, unboxed command palette grouped by domain."""
    categories = {
        "🤖 Models & Routing": [c for c in SLASH_COMMANDS if c[2] in ("Models", "Provider")],
        "🌐 Messaging Gateways": [c for c in SLASH_COMMANDS if c[2] == "Gateway"],
        "🐙 GitHub App": [c for c in SLASH_COMMANDS if c[2] == "GitHub"],
        "👥 AI-Team": [c for c in SLASH_COMMANDS if c[2] == "Team"],
        "🛠 Tools & Extensibility": [c for c in SLASH_COMMANDS if c[2] in ("Tools", "Status", "Plugins")],
        "🧠 Memory & Skills": [c for c in SLASH_COMMANDS if c[2] in ("Skills", "Memory")],
        "⏰ Automations & Session": [c for c in SLASH_COMMANDS if c[2] in ("Background", "Session")],
        "🛡 Security & Settings": [c for c in SLASH_COMMANDS if c[2] in ("Security", "Utility") and not c[0].startswith("q")]
    }

    console.print()
    console.print("  [bold #00ffd7]⚡ Nexus Command Palette[/bold #00ffd7]\n")

    for cat_title, items in categories.items():
        console.print(f"  [dim #94a3b8]{cat_title}[/dim #94a3b8]")
        for cmd, desc, _ in items:
            console.print(f"    [bold #38bdf8]{cmd:<14}[/bold #38bdf8] [dim]→[/dim]  [white]{desc}[/white]")
        console.print()

    console.print("  [dim]Tip: Type [bold #00ffd7]/[/bold #00ffd7] in prompt to see live autocomplete suggestions.[/dim]\n")

async def _run_arrow_key_provider_picker(providers: List[ProviderProfile], active_id: str) -> Optional[ProviderProfile]:
    """Interactive arrow-key selector for Providers/Routers."""
    selected_idx = [0]
    result = [None]

    # Pre-select active provider
    for i, p in enumerate(providers):
        if p.id == active_id:
            selected_idx[0] = i
            break

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        selected_idx[0] = (selected_idx[0] - 1) % len(providers)
        event.app.invalidate()

    @kb.add("down")
    def _(event):
        selected_idx[0] = (selected_idx[0] + 1) % len(providers)
        event.app.invalidate()

    @kb.add("enter")
    def _(event):
        if 0 <= selected_idx[0] < len(providers):
            result[0] = providers[selected_idx[0]]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event):
        result[0] = None
        event.app.exit()

    def get_header():
        return [
            ("class:title", "Select default inference router:"),
            ("class:dim", "\n\n")
        ]

    def get_content():
        lines = [
            ("class:colhead", f"   {'Provider':<32} {'Default Endpoint':<42} Status\n"),
            ("class:dim", f"   {'─'*32} {'─'*42} {'─'*14}\n")
        ]

        total = len(providers)
        max_rows = 12
        cur = selected_idx[0]
        start_idx = max(0, min(cur - max_rows // 2, total - max_rows))
        end_idx = min(total, start_idx + max_rows)

        for i in range(start_idx, end_idx):
            p = providers[i]
            is_active = (p.id == active_id)
            is_sel = (i == cur)

            if is_sel:
                prefix = " ❯ "
                line_style = "class:cursor"
            elif is_active:
                prefix = "   "
                line_style = "class:active"
            else:
                prefix = "   "
                line_style = ""

            status_str = "● ACTIVE" if is_active else ""
            endpoint_str = p.default_base if p.default_base else "(Custom URL)"
            row_str = f"{prefix}{p.name:<30} {endpoint_str:<42} {status_str}\n"
            lines.append((line_style, row_str))

        hint = f"   [Showing {start_idx+1}-{end_idx} of {total} • ↑/↓ navigate • Enter choose • Esc cancel]\n"
        lines.append(("class:dim", f"\n{hint}"))
        return lines

    layout = Layout(HSplit([
        Window(FormattedTextControl(get_header), height=2),
        Window(FormattedTextControl(get_content), height=16),
    ]))

    style = Style.from_dict({
        "title": "bold #38bdf8",
        "cursor": "bold #11111b bg:#00ffd7",
        "active": "bold #22c55e",
        "colhead": "bold #94a3b8",
        "dim": "#64748b",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False, erase_when_done=True)
    await app.run_async()
    return result[0]

async def interactive_select_provider(session: PromptSession, current_llm, env_path: Path):
    """Full-featured interactive provider switcher with arrow-key navigation."""
    active_profile = ProviderManager.detect_active_provider(config.API_BASE)
    providers = ProviderManager.list_providers()

    try:
        selected = await _run_arrow_key_provider_picker(providers, active_profile.id)
    except Exception:
        selected = None

    if not selected:
        console.print("  [dim]Provider selection cancelled.[/dim]\n")
        return

    # Base URL configuration
    target_base = selected.default_base
    if selected.id == "custom":
        custom_base = (await session.prompt_async(f"\n  Enter Custom Base URL [{config.API_BASE}] ❯ ", is_password=False)).strip()
        if custom_base:
            target_base = custom_base

    # API Key configuration
    target_key = config.API_KEY
    if not selected.is_local:
        existing_masked = f"{target_key[:6]}...{target_key[-4:]}" if len(target_key) > 10 else (target_key or "None")
        console.print(f"  [dim]Current API Key for {selected.name}: {existing_masked}[/dim]")
        try:
            new_key = (await session.prompt_async("  Enter API Key (press Enter to keep existing) ❯ ", is_password=True)).strip()
        finally:
            session.is_password = False
        if new_key:
            target_key = new_key
    else:
        target_key = "ollama"

    # Save to config and .env
    config.API_BASE = target_base
    config.API_KEY = target_key
    current_llm.api_base = target_base.rstrip("/")
    current_llm.api_key = target_key
    os.environ["OPENAI_API_BASE"] = target_base
    os.environ["OPENAI_API_KEY"] = target_key

    updates = {
        "OPENAI_API_BASE": target_base,
        "OPENAI_API_KEY": target_key
    }
    ProviderManager.update_env_file(updates, env_path)

    console.print(f"\n  [dim cyan]⠋ Handshaking with {selected.name}...[/dim cyan]")
    await asyncio.sleep(0.2)
    console.print(f"  [bold #22c55e]✔ Connected to {selected.name}![/bold #22c55e] [dim]({target_base})[/dim]\n")

    # Prompt to pick a model now
    prompt_model = (await session.prompt_async(f"  Browse & select a model for {selected.name} now? [Y/n] ❯ ", is_password=False)).strip().lower()
    if prompt_model in ("", "y", "yes"):
        await interactive_select_model(session, current_llm, env_path, provider_override=selected)

async def _run_arrow_key_model_picker(
    models: List[ModelInfo],
    active_model: str,
    provider_name: str,
    health_stats: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Interactive unboxed arrow-key selector with real-time fuzzy filter and model health status."""
    filter_text = [""]
    selected_idx = [0]
    result = [None]
    total_models = len(models)
    stats = health_stats or {}
    down_excluded = int(stats.get("down_excluded", 0))

    # Pre-select current active model
    for i, m in enumerate(models):
        if m.id.lower() == (active_model or "").lower():
            selected_idx[0] = i
            break

    def get_filtered() -> List[ModelInfo]:
        q = filter_text[0].lower().strip()
        if not q:
            return models
        return [m for m in models if q in m.id.lower() or q in m.tag.lower() or q in m.status.lower()]

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        filtered = get_filtered()
        if filtered:
            selected_idx[0] = (selected_idx[0] - 1) % len(filtered)
            event.app.invalidate()

    @kb.add("down")
    def _(event):
        filtered = get_filtered()
        if filtered:
            selected_idx[0] = (selected_idx[0] + 1) % len(filtered)
            event.app.invalidate()

    @kb.add("enter")
    def _(event):
        filtered = get_filtered()
        if filtered and 0 <= selected_idx[0] < len(filtered):
            result[0] = filtered[selected_idx[0]].id
        event.app.exit()

    @kb.add("c-r")
    def _(event):
        result[0] = "__REFRESH__"
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event):
        result[0] = None
        event.app.exit()

    @kb.add("backspace")
    def _(event):
        if filter_text[0]:
            filter_text[0] = filter_text[0][:-1]
            selected_idx[0] = 0
            event.app.invalidate()

    @kb.add("<any>")
    def _(event):
        for ch in event.data:
            if ch.isprintable():
                filter_text[0] += ch
                selected_idx[0] = 0
                event.app.invalidate()

    def get_header():
        q = filter_text[0]
        filter_display = q if q else "<type to search...>"
        filter_style = "class:filter-active" if q else "class:dim"
        active_cnt = sum(1 for m in models if m.status == "active")
        unchecked_cnt = sum(1 for m in models if m.status != "active")
        down_note = f" · {down_excluded} down skipped" if down_excluded > 0 else ""
        return [
            ("class:title", f"Select model for [{provider_name}]:"),
            ("class:dim", f"  ("),
            ("class:status-ok", f"{active_cnt} aktif"),
            ("class:dim", f" · "),
            ("class:status-unk", f"{unchecked_cnt} belum dicek"),
            ("class:status-down", down_note),
            ("class:dim", f" · Filter: "),
            (filter_style, filter_display),
            ("class:dim", f" · {total_models} models)\n\n")
        ]

    def get_content():
        filtered = get_filtered()
        if not filtered:
            return [("class:dim", f"\n   No models match '{filter_text[0]}'. Press Backspace to clear filter.\n")]

        lines = [
            ("class:colhead", f"   {'Model Identifier':<40} {'Tag':<15} {'Ctx':<7} Status\n"),
            ("class:dim", f"   {'─'*40} {'─'*15} {'─'*7} {'─'*26}\n")
        ]

        total = len(filtered)
        max_rows = 12
        cur = selected_idx[0]
        start_idx = max(0, min(cur - max_rows // 2, total - max_rows))
        end_idx = min(total, start_idx + max_rows)

        for i in range(start_idx, end_idx):
            m = filtered[i]
            is_active = (m.id.lower() == active_model.lower())
            is_sel = (i == cur)

            if is_sel:
                prefix = " ❯ "
                line_style = "class:cursor"
            elif is_active:
                prefix = "   "
                line_style = "class:active"
            else:
                prefix = "   "
                line_style = ""

            if m.status == "active":
                health_label = "● Aktif"
            else:
                health_label = "○ Belum dicek"
            status_str = f"{health_label} ← in use" if is_active else health_label
            tag_str = f"[{m.tag}]"
            row_str = f"{prefix}{m.id:<40} {tag_str:<15} {m.context:<7} {status_str}\n"
            lines.append((line_style, row_str))

        hint_base = "↑/↓ move • type to filter • Ctrl+R re-check • Enter select • Esc cancel"
        if total > max_rows:
            hint = f"   [Showing {start_idx + 1}-{end_idx} of {total} • {hint_base}]"
        else:
            hint = f"   [{hint_base}]"
        lines.append(("class:dim", f"\n{hint}\n"))

        return lines

    layout = Layout(HSplit([
        Window(FormattedTextControl(get_header), height=2),
        Window(FormattedTextControl(get_content), height=16),
    ]))

    style = Style.from_dict({
        "title": "bold #38bdf8",
        "provider": "bold #f59e0b",
        "filter-active": "bold #00ffd7",
        "status-ok": "bold #22c55e",
        "status-unk": "#eab308",
        "status-down": "#ef4444",
        "cursor": "bold #11111b bg:#00ffd7",
        "active": "bold #22c55e",
        "colhead": "bold #94a3b8",
        "dim": "#64748b",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False, erase_when_done=True)
    await app.run_async()
    return result[0]

async def interactive_select_model(
    session: PromptSession,
    current_llm,
    env_path: Path,
    provider_override: Optional[ProviderProfile] = None,
    force_check: bool = False,
):
    """Interactive model selector with live health check (aktif / belum dicek / down excluded)."""
    provider = provider_override or ProviderManager.detect_active_provider(config.API_BASE)

    # Check if provider is connected and authenticated before listing models
    is_connected = True
    if not provider.is_local:
        if not config.API_KEY or config.API_KEY == "your_api_key_here":
            is_connected = False

    if not is_connected:
        console.print(f"\n  [bold yellow]⚠ Provider Not Connected:[/bold yellow] [bold #f59e0b]{provider.name}[/bold #f59e0b]")
        console.print(f"  [dim]Active Endpoint:[/dim] [white]{config.API_BASE}[/white]")
        console.print("  [dim]No API key is configured for this router/provider yet.[/dim]")
        console.print("  [dim]Please connect and authenticate your provider before browsing models.[/dim]\n")

        prompt_connect = (await session.prompt_async(f"  Connect to {provider.name} now? [Y/n] ❯ ", is_password=False)).strip().lower()
        if prompt_connect in ("", "y", "yes"):
            await interactive_select_provider(session, current_llm, env_path)
            provider = ProviderManager.detect_active_provider(config.API_BASE)
            if not provider.is_local and (not config.API_KEY or config.API_KEY == "your_api_key_here"):
                return
        else:
            console.print("  [dim]Model selection aborted. Use /provider to connect when ready.[/dim]\n")
            return

    console.print(f"\n  [bold #00ffd7]◈ Active Provider:[/bold #00ffd7] [bold #f59e0b]{provider.name}[/bold #f59e0b] [dim]({config.API_BASE})[/dim]")

    force = force_check
    while True:
        status_msg = (
            f"[bold cyan]  Re-checking model health from {provider.name}...[/bold cyan]"
            if force else
            f"[bold cyan]  Fetching & checking live model health from {provider.name}...[/bold cyan]"
        )
        with console.status(status_msg):
            models, health_stats = await ProviderManager.get_models_with_health(
                provider,
                api_key=config.API_KEY,
                api_base=config.API_BASE,
                check_health=True,
                force_refresh=force,
            )

        down_cnt = int(health_stats.get("down_excluded", 0))
        if down_cnt > 0:
            down_preview = ", ".join(health_stats.get("down_models", [])[:4])
            more = f" (+{down_cnt - 4} more)" if down_cnt > 4 else ""
            console.print(
                f"  [dim red]✖ Excluded {down_cnt} down/mati model(s):[/dim red] [dim]{down_preview}{more} (auto re-check tomorrow)[/dim]"
            )

        if not models:
            console.print("  [bold red]✖ No active models available today from this provider (all returned down).[/bold red]")
            console.print("  [dim]Run `/models check` to force re-check or check again tomorrow.[/dim]\n")
            return

        active_model = config.MODEL
        try:
            selected_model_id = await _run_arrow_key_model_picker(models, active_model, provider.name, health_stats)
        except Exception:
            selected_model_id = None

        if selected_model_id == "__REFRESH__":
            force = True
            continue
        break

    if not selected_model_id:
        console.print("  [dim]Kept current active model.[/dim]\n")
        return

    # Update runtime config & LLM
    config.MODEL = selected_model_id
    current_llm.model = selected_model_id
    os.environ["NEXUS_MODEL"] = selected_model_id

    # Persist to .env
    ProviderManager.update_env_file({"NEXUS_MODEL": selected_model_id}, env_path)

    console.print(f"\n  [dim cyan]⠋ Activating model '{selected_model_id}' on {provider.name}...[/dim cyan]")
    await asyncio.sleep(0.2)
    console.print(f"  [bold #22c55e]✔ Model switched to:[/bold #22c55e] [bold #00ffd7]{selected_model_id}[/bold #00ffd7] [dim](Router: {provider.name} · saved to .env)[/dim]\n")

async def _run_arrow_key_session_picker(sessions: List[Dict[str, Any]], active_id: str) -> Optional[str]:
    """Interactive arrow-key selector for past sessions."""
    selected_idx = [0]
    result = [None]
    total = len(sessions)

    for i, s in enumerate(sessions):
        if s.get("id") == active_id:
            selected_idx[0] = i
            break

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        if total:
            selected_idx[0] = (selected_idx[0] - 1) % total
            event.app.invalidate()

    @kb.add("down")
    def _(event):
        if total:
            selected_idx[0] = (selected_idx[0] + 1) % total
            event.app.invalidate()

    @kb.add("enter")
    def _(event):
        if total and 0 <= selected_idx[0] < total:
            result[0] = sessions[selected_idx[0]].get("id")
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event):
        result[0] = None
        event.app.exit()

    def get_header():
        return [
            ("class:title", "Select conversation session to resume:"),
            ("class:dim", f"  ({total} sessions in SQLite)\n\n")
        ]

    def get_content():
        if not sessions:
            return [("class:dim", "   No past sessions found.\n")]

        lines = [
            ("class:colhead", f"   {'Session ID':<22} {'Messages':<12} Updated\n"),
            ("class:dim", f"   {'─'*22} {'─'*12} {'─'*28}\n")
        ]

        max_rows = 12
        cur = selected_idx[0]
        start_idx = max(0, min(cur - max_rows // 2, total - max_rows))
        end_idx = min(total, start_idx + max_rows)

        for i in range(start_idx, end_idx):
            s = sessions[i]
            sid = s.get("id", "")
            msgs = s.get("message_count", 0)
            updated = str(s.get("updated_at", ""))[:19]
            is_active = (sid == active_id)
            is_sel = (i == cur)

            if is_sel:
                prefix = " ❯ "
                line_style = "class:cursor"
            elif is_active:
                prefix = "   "
                line_style = "class:active"
            else:
                prefix = "   "
                line_style = ""

            status_str = "● ACTIVE" if is_active else ""
            msg_str = f"{msgs} msgs"
            row_str = f"{prefix}{sid:<20} {msg_str:<12} {updated:<20} {status_str}\n"
            lines.append((line_style, row_str))

        hint = f"   [Showing {start_idx+1}-{end_idx} of {total} • ↑/↓ navigate • Enter resume • Esc cancel]\n"
        lines.append(("class:dim", f"\n{hint}"))
        return lines

    layout = Layout(HSplit([
        Window(FormattedTextControl(get_header), height=2),
        Window(FormattedTextControl(get_content), height=16),
    ]))

    style = Style.from_dict({
        "title": "bold #38bdf8",
        "cursor": "bold #11111b bg:#00ffd7",
        "active": "bold #22c55e",
        "colhead": "bold #94a3b8",
        "dim": "#64748b",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False, erase_when_done=True)
    await app.run_async()
    return result[0]

async def interactive_resume_session(memory, current_session: list, agent) -> Optional[str]:
    """Interactive session resumer."""
    sessions = memory.list_sessions(limit=30)
    if not sessions:
        console.print("  [dim]No previous sessions found to resume.[/dim]\n")
        return None

    try:
        chosen_id = await _run_arrow_key_session_picker(sessions, current_session[0])
    except Exception:
        chosen_id = None

    if not chosen_id:
        console.print("  [dim]Kept current session.[/dim]\n")
        return None

    current_session[0] = chosen_id
    agent.session_id = chosen_id
    history = memory.get_session_history(chosen_id)

    console.print(f"\n  [dim cyan]⠋ Loading conversation context from SQLite...[/dim cyan]")
    await asyncio.sleep(0.2)
    console.print(f"  [bold #22c55e]✔ Resumed session:[/bold #22c55e] [bold #00ffd7]{chosen_id}[/bold #00ffd7] [dim]({len(history)} messages loaded)[/dim]\n")
    return chosen_id


async def _run_arrow_key_gateway_picker() -> Optional[str]:
    """Interactive arrow-key selector for messaging gateway platform."""
    platforms = [
        ("telegram", "Telegram Bot", "BotFather token · Long-polling · Typing indicator"),
        ("discord", "Discord Bot", "Gateway v10 WebSocket · DMs, @mentions & channels"),
        ("whatsapp", "WhatsApp Bridge", "Meta Cloud API or Baileys/Evolution webhook"),
    ]
    selected_idx = [0]
    result = [None]
    total = len(platforms)

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        selected_idx[0] = (selected_idx[0] - 1) % total
        event.app.invalidate()

    @kb.add("down")
    def _(event):
        selected_idx[0] = (selected_idx[0] + 1) % total
        event.app.invalidate()

    @kb.add("enter")
    def _(event):
        result[0] = platforms[selected_idx[0]][0]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event):
        result[0] = None
        event.app.exit()

    def get_header():
        return [
            ("class:title", "Select Messaging Gateway to Configure:"),
            ("class:dim", "  (Hermes-Style Unified Bridge)\n\n"),
        ]

    def get_content():
        lines = [
            ("class:colhead", f"   {'Gateway':<18} {'Description'}\n"),
            ("class:dim", f"   {'─'*18} {'─'*56}\n"),
        ]
        for i, (pid, pname, pdesc) in enumerate(platforms):
            if i == selected_idx[0]:
                prefix = " ❯ "
                line_style = "class:cursor"
            else:
                prefix = "   "
                line_style = ""
            lines.append((line_style, f"{prefix}{pname:<16} {pdesc}\n"))

        lines.append(("class:dim", "\n   [↑/↓ move • Enter configure • Esc cancel]\n"))
        return lines

    layout = Layout(HSplit([
        Window(FormattedTextControl(get_header), height=2),
        Window(FormattedTextControl(get_content), height=8),
    ]))

    style = Style.from_dict({
        "title": "bold #38bdf8",
        "cursor": "bold #11111b bg:#00ffd7",
        "colhead": "bold #94a3b8",
        "dim": "#64748b",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False, erase_when_done=True)
    await app.run_async()
    return result[0]


async def interactive_gateway_setup(session: PromptSession, env_path: Path) -> Optional[str]:
    """Interactive setup wizard for Telegram, Discord, and WhatsApp gateways."""
    try:
        choice = await _run_arrow_key_gateway_picker()
    except Exception:
        choice = None

    if not choice:
        console.print("  [dim]Gateway setup cancelled.[/dim]\n")
        return None

    updates: Dict[str, str] = {}

    if choice == "telegram":
        console.print("\n  [bold #00ffd7]✈️ Telegram Bot Gateway Setup[/bold #00ffd7]")
        console.print("  [dim]Get a bot token from @BotFather on Telegram (/newbot).[/dim]")
        try:
            token = (await session.prompt_async("  TELEGRAM_BOT_TOKEN (Enter to keep existing) ❯ ", is_password=True)).strip()
        finally:
            session.is_password = False
        if token:
            updates["TELEGRAM_BOT_TOKEN"] = token

        cur_allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")
        allowed = (await session.prompt_async(f"  TELEGRAM_ALLOWED_USERS (comma IDs/@usernames) [{cur_allowed or 'empty=deny unknown'}] ❯ ", is_password=False)).strip()
        if allowed:
            updates["TELEGRAM_ALLOWED_USERS"] = allowed

    elif choice == "discord":
        console.print("\n  [bold #00ffd7]🎮 Discord Bot Gateway Setup[/bold #00ffd7]")
        console.print("  [dim]Create a bot in Discord Developer Portal -> Bot -> Token.[/dim]")
        try:
            token = (await session.prompt_async("  DISCORD_BOT_TOKEN (Enter to keep existing) ❯ ", is_password=True)).strip()
        finally:
            session.is_password = False
        if token:
            updates["DISCORD_BOT_TOKEN"] = token

        cur_users = os.getenv("DISCORD_ALLOWED_USERS", "")
        allowed_u = (await session.prompt_async(f"  DISCORD_ALLOWED_USERS (comma IDs/usernames) [{cur_users or 'empty=deny unknown'}] ❯ ", is_password=False)).strip()
        if allowed_u:
            updates["DISCORD_ALLOWED_USERS"] = allowed_u

        cur_ch = os.getenv("DISCORD_ALLOWED_CHANNELS", "")
        allowed_c = (await session.prompt_async(f"  DISCORD_ALLOWED_CHANNELS (optional channel IDs) [{cur_ch}] ❯ ", is_password=False)).strip()
        if allowed_c:
            updates["DISCORD_ALLOWED_CHANNELS"] = allowed_c

    elif choice == "whatsapp":
        console.print("\n  [bold #00ffd7]💬 WhatsApp Gateway Setup[/bold #00ffd7]")
        console.print("  [dim]Supports Meta Cloud API OR a local Baileys/Evolution QR bridge.[/dim]")
        mode = (await session.prompt_async("  Mode: [1] Local Bridge (Baileys/Evolution) or [2] Meta Cloud API [1/2] ❯ ", is_password=False)).strip()
        updates["WHATSAPP_ENABLED"] = "true"

        if mode == "2":
            try:
                wa_tok = (await session.prompt_async("  WHATSAPP_API_TOKEN (Enter to keep existing) ❯ ", is_password=True)).strip()
            finally:
                session.is_password = False
            if wa_tok:
                updates["WHATSAPP_API_TOKEN"] = wa_tok
            pid = (await session.prompt_async(f"  WHATSAPP_PHONE_NUMBER_ID [{os.getenv('WHATSAPP_PHONE_NUMBER_ID', '')}] ❯ ", is_password=False)).strip()
            if pid:
                updates["WHATSAPP_PHONE_NUMBER_ID"] = pid
            vtok = (await session.prompt_async(f"  WHATSAPP_VERIFY_TOKEN [{os.getenv('WHATSAPP_VERIFY_TOKEN', 'nexus_verify_token')}] ❯ ", is_password=False)).strip()
            if vtok:
                updates["WHATSAPP_VERIFY_TOKEN"] = vtok
        else:
            cur_br = os.getenv("WHATSAPP_BRIDGE_URL", "http://localhost:3000/send")
            burl = (await session.prompt_async(f"  WHATSAPP_BRIDGE_URL [{cur_br}] ❯ ", is_password=False)).strip()
            updates["WHATSAPP_BRIDGE_URL"] = burl or cur_br
            try:
                btok = (await session.prompt_async("  WHATSAPP_BRIDGE_TOKEN (optional, Enter to skip) ❯ ", is_password=True)).strip()
            finally:
                session.is_password = False
            if btok:
                updates["WHATSAPP_BRIDGE_TOKEN"] = btok

        cur_port = os.getenv("WHATSAPP_PORT", "8090")
        wport = (await session.prompt_async(f"  Webhook Listen Port [{cur_port}] ❯ ", is_password=False)).strip()
        if wport:
            updates["WHATSAPP_PORT"] = wport

        cur_nums = os.getenv("WHATSAPP_ALLOWED_NUMBERS", "")
        wnums = (await session.prompt_async(f"  WHATSAPP_ALLOWED_NUMBERS (e.g. 62812xxx) [{cur_nums or 'empty=deny unknown'}] ❯ ", is_password=False)).strip()
        if wnums:
            updates["WHATSAPP_ALLOWED_NUMBERS"] = wnums

    # Ask about allow-all policy if no allow-list was provided
    allow_all_ans = (await session.prompt_async("  Allow ALL users (skip allow-list)? [y/N] ❯ ", is_password=False)).strip().lower()
    if allow_all_ans in ("y", "yes"):
        updates["GATEWAY_ALLOW_ALL_USERS"] = "true"
    elif allow_all_ans in ("n", "no"):
        updates["GATEWAY_ALLOW_ALL_USERS"] = "false"

    if updates:
        for k, v in updates.items():
            os.environ[k] = v
        ProviderManager.update_env_file(updates, env_path)
        console.print(f"\n  [bold #22c55e]✔ Saved {choice.capitalize()} gateway config to .env![/bold #22c55e]")
        console.print(f"  [dim]Run [bold #00ffd7]/gateway start {choice}[/bold #00ffd7] to start listening now, or [bold #00ffd7]nexus --gateway[/bold #00ffd7] in daemon mode.[/dim]\n")
    else:
        console.print("\n  [dim]No changes made.[/dim]\n")

    return choice


async def _run_arrow_key_mcp_picker() -> Optional[str]:
    """Arrow-key selector for popular MCP server presets & custom stdio/remote transports."""
    presets = [
        ("github-remote", "GitHub (Remote HTTP)", "Official Copilot MCP URL + Bearer PAT (no Node/Docker needed)"),
        ("github-local", "GitHub (Local npx)", "npx @modelcontextprotocol/server-github + GitHub PAT"),
        ("filesystem", "Filesystem (npx)", "Read/write/search files in an allowed local directory"),
        ("playwright", "Playwright (npx)", "Browser automation & DOM inspection via Playwright MCP"),
        ("context7", "Context7 Docs (npx)", "Up-to-date library/framework docs lookup"),
        ("fetch", "Web Fetch (uvx)", "Fetch & convert web pages to Markdown via mcp-server-fetch"),
        ("custom-remote", "Custom Remote (HTTP/SSE)", "Connect any remote MCP URL (Streamable HTTP or SSE)"),
        ("custom-stdio", "Custom Local (stdio)", "Configure any local command + args + env vars"),
    ]
    selected_idx = [0]
    result = [None]
    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        if selected_idx[0] > 0:
            selected_idx[0] -= 1

    @kb.add("down")
    def _(event):
        if selected_idx[0] < len(presets) - 1:
            selected_idx[0] += 1

    @kb.add("enter")
    def _(event):
        result[0] = presets[selected_idx[0]][0]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event):
        result[0] = None
        event.app.exit()

    def get_header():
        return [
            ("class:title", "Add Model Context Protocol (MCP) Server:"),
            ("class:dim", "  (Stdio + Remote HTTP/SSE)\n\n"),
        ]

    def get_content():
        lines = [
            ("class:colhead", f"   {'Preset / Transport':<24} {'Description'}\n"),
            ("class:dim", f"   {'─'*24} {'─'*58}\n"),
        ]
        for i, (pid, pname, pdesc) in enumerate(presets):
            if i == selected_idx[0]:
                prefix = " ❯ "
                line_style = "class:cursor"
            else:
                prefix = "   "
                line_style = ""
            lines.append((line_style, f"{prefix}{pname:<22} {pdesc}\n"))

        lines.append(("class:dim", "\n   [↑/↓ move • Enter select • Esc cancel]\n"))
        return lines

    layout = Layout(HSplit([
        Window(FormattedTextControl(get_header), height=2),
        Window(FormattedTextControl(get_content), height=13),
    ]))

    style = Style.from_dict({
        "title": "bold #38bdf8",
        "cursor": "bold #11111b bg:#00ffd7",
        "colhead": "bold #94a3b8",
        "dim": "#64748b",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False, erase_when_done=True)
    await app.run_async()
    return result[0]


async def interactive_mcp_add(session: PromptSession, mcp_manager, registry) -> bool:
    """Interactive wizard to add a stdio or remote HTTP/SSE MCP server and connect immediately."""
    import shlex
    from ..mcp import MCPServerConfig

    try:
        choice = await _run_arrow_key_mcp_picker()
    except Exception:
        choice = None

    if not choice:
        console.print("  [dim]MCP setup cancelled.[/dim]\n")
        return False

    cfg: Optional[MCPServerConfig] = None

    if choice == "github-remote":
        console.print("\n  [bold #00ffd7]🐙 GitHub Remote MCP Setup[/bold #00ffd7]")
        console.print("  [dim]Endpoint: https://api.githubcopilot.com/mcp/[/dim]")
        name = (await session.prompt_async("  Server name [github] ❯ ", is_password=False)).strip() or "github"
        url = (await session.prompt_async("  MCP URL [https://api.githubcopilot.com/mcp/] ❯ ", is_password=False)).strip() or "https://api.githubcopilot.com/mcp/"
        try:
            pat = (await session.prompt_async("  GitHub PAT Token (ghp_.../github_pat_..., optional if public) ❯ ", is_password=True)).strip()
        finally:
            session.is_password = False
        headers = {"Authorization": f"Bearer {pat}"} if pat else {}
        cfg = MCPServerConfig(name=name, url=url, headers=headers, transport="http")

    elif choice == "github-local":
        console.print("\n  [bold #00ffd7]🐙 GitHub Local MCP (npx) Setup[/bold #00ffd7]")
        name = (await session.prompt_async("  Server name [github] ❯ ", is_password=False)).strip() or "github"
        try:
            pat = (await session.prompt_async("  GITHUB_PERSONAL_ACCESS_TOKEN ❯ ", is_password=True)).strip()
        finally:
            session.is_password = False
        env = {"GITHUB_PERSONAL_ACCESS_TOKEN": pat} if pat else {}
        cfg = MCPServerConfig(
            name=name,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env=env,
            transport="stdio",
        )

    elif choice == "filesystem":
        console.print("\n  [bold #00ffd7]📁 Filesystem MCP Setup[/bold #00ffd7]")
        name = (await session.prompt_async("  Server name [filesystem] ❯ ", is_password=False)).strip() or "filesystem"
        default_dir = str(config.WORKSPACE_DIR)
        root_dir = (await session.prompt_async(f"  Allowed directory [{default_dir}] ❯ ", is_password=False)).strip() or default_dir
        cfg = MCPServerConfig(
            name=name,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", root_dir],
            transport="stdio",
        )

    elif choice == "playwright":
        console.print("\n  [bold #00ffd7]🎭 Playwright Browser MCP Setup[/bold #00ffd7]")
        name = (await session.prompt_async("  Server name [playwright] ❯ ", is_password=False)).strip() or "playwright"
        cfg = MCPServerConfig(
            name=name,
            command="npx",
            args=["-y", "@playwright/mcp@latest"],
            transport="stdio",
        )

    elif choice == "context7":
        console.print("\n  [bold #00ffd7]📚 Context7 Docs MCP Setup[/bold #00ffd7]")
        name = (await session.prompt_async("  Server name [context7] ❯ ", is_password=False)).strip() or "context7"
        cfg = MCPServerConfig(
            name=name,
            command="npx",
            args=["-y", "@upstash/context7-mcp"],
            transport="stdio",
        )

    elif choice == "fetch":
        console.print("\n  [bold #00ffd7]🌐 Web Fetch MCP Setup[/bold #00ffd7]")
        name = (await session.prompt_async("  Server name [fetch] ❯ ", is_password=False)).strip() or "fetch"
        cfg = MCPServerConfig(
            name=name,
            command="uvx",
            args=["mcp-server-fetch"],
            transport="stdio",
        )

    elif choice == "custom-remote":
        console.print("\n  [bold #00ffd7]🌐 Custom Remote MCP (Streamable HTTP / SSE)[/bold #00ffd7]")
        name = (await session.prompt_async("  Server name (e.g. linear, cloudflare) ❯ ", is_password=False)).strip()
        if not name:
            console.print("  [red]Server name is required.[/red]\n")
            return False
        url = (await session.prompt_async("  Server URL (https://...) ❯ ", is_password=False)).strip()
        if not url:
            console.print("  [red]URL is required.[/red]\n")
            return False
        tmode = (await session.prompt_async("  Transport [1=Streamable HTTP (auto SSE fallback), 2=SSE] [1] ❯ ", is_password=False)).strip()
        transport = "sse" if tmode == "2" else "http"
        try:
            auth = (await session.prompt_async("  Bearer Token / Authorization value (Enter to skip) ❯ ", is_password=True)).strip()
        finally:
            session.is_password = False
        headers = {}
        if auth:
            headers["Authorization"] = auth if auth.lower().startswith(("bearer ", "token ", "basic ")) else f"Bearer {auth}"
        cfg = MCPServerConfig(name=name, url=url, headers=headers, transport=transport)

    elif choice == "custom-stdio":
        console.print("\n  [bold #00ffd7]⚙️ Custom Stdio MCP Setup[/bold #00ffd7]")
        name = (await session.prompt_async("  Server name (e.g. postgres, sqlite) ❯ ", is_password=False)).strip()
        if not name:
            console.print("  [red]Server name is required.[/red]\n")
            return False
        command = (await session.prompt_async("  Command (e.g. npx, uvx, python, docker) ❯ ", is_password=False)).strip()
        if not command:
            console.print("  [red]Command is required.[/red]\n")
            return False
        raw_args = (await session.prompt_async("  Args (space-separated, Enter if none) ❯ ", is_password=False)).strip()
        try:
            args = shlex.split(raw_args) if raw_args else []
        except ValueError:
            args = raw_args.split() if raw_args else []
        raw_env = (await session.prompt_async("  Env vars KEY=VAL,KEY2=VAL2 (Enter to skip) ❯ ", is_password=False)).strip()
        env: Dict[str, str] = {}
        if raw_env:
            for pair in raw_env.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    if k.strip():
                        env[k.strip()] = v.strip()
        cfg = MCPServerConfig(name=name, command=command, args=args, env=env, transport="stdio")

    if not cfg:
        return False

    scope_ans = (await session.prompt_async("  Save to [1] Global (~/.nexus/mcp.json) or [2] Workspace (.mcp.json) [1] ❯ ", is_password=False)).strip()
    scope = "workspace" if scope_ans == "2" else "global"

    saved_path = mcp_manager.add_server_to_config(cfg, scope=scope)
    console.print(f"\n  [bold #22c55e]✔ Saved '{cfg.name}' to[/bold #22c55e] [dim]{saved_path}[/dim]")
    console.print(f"  [dim cyan]⠋ Connecting to MCP server '{cfg.name}'...[/dim cyan]")

    started = await mcp_manager.reload(registry)
    loaded_tools = started.get(cfg.name)
    if loaded_tools is not None:
        preview = ", ".join(loaded_tools[:8]) + (f" (+{len(loaded_tools)-8} more)" if len(loaded_tools) > 8 else "")
        console.print(f"  [bold #22c55e]✔ Connected '{cfg.name}' ({len(loaded_tools)} tools):[/bold #22c55e] [cyan]{preview or 'none'}[/cyan]\n")
    else:
        err = mcp_manager._errors.get(cfg.name, "Unknown error")
        console.print(f"  [bold yellow]⚠ Saved to config, but connection failed:[/bold yellow] [red]{err}[/red]\n")

    return True


