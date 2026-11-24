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
    ("/mcp", "Inspect connected Model Context Protocol (MCP) servers & tools", "Tools"),
    ("/plugins", "View loaded modular plugins from plugins/ directory", "Plugins"),
    ("/security", "View security guardrails, command sandbox & safety policy", "Security"),
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

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False)
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
        custom_base = (await session.prompt_async(f"\n  Enter Custom Base URL [{config.API_BASE}] ❯ ")).strip()
        if custom_base:
            target_base = custom_base

    # API Key configuration
    target_key = config.API_KEY
    if not selected.is_local:
        existing_masked = f"{target_key[:6]}...{target_key[-4:]}" if len(target_key) > 10 else (target_key or "None")
        console.print(f"  [dim]Current API Key for {selected.name}: {existing_masked}[/dim]")
        new_key = (await session.prompt_async("  Enter API Key (press Enter to keep existing) ❯ ", is_password=True)).strip()
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
    prompt_model = (await session.prompt_async(f"  Browse & select a model for {selected.name} now? [Y/n] ❯ ")).strip().lower()
    if prompt_model in ("", "y", "yes"):
        await interactive_select_model(session, current_llm, env_path, provider_override=selected)

async def _run_arrow_key_model_picker(models: List[ModelInfo], active_model: str, provider_name: str) -> Optional[str]:
    """Interactive unboxed arrow-key selector with real-time fuzzy filter."""
    filter_text = [""]
    selected_idx = [0]
    result = [None]
    total_models = len(models)

    def get_filtered() -> List[ModelInfo]:
        q = filter_text[0].lower().strip()
        if not q:
            return models
        return [m for m in models if q in m.id.lower() or q in m.tag.lower()]

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
        return [
            ("class:title", f"Select model for [{provider_name}]:"),
            ("class:dim", f"  (Router: "),
            ("class:provider", f"{provider_name}"),
            ("class:dim", f" · Filter: "),
            (filter_style, filter_display),
            ("class:dim", f" · {total_models} models)\n\n")
        ]

    def get_content():
        filtered = get_filtered()
        if not filtered:
            return [("class:dim", f"\n   No models match '{filter_text[0]}'. Press Backspace to clear filter.\n")]

        lines = [
            ("class:colhead", f"   {'Model Identifier':<42} {'Tag':<16} {'Context':<8} Status\n"),
            ("class:dim", f"   {'─'*42} {'─'*16} {'─'*8} {'─'*22}\n")
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

            status_str = "← currently in use" if is_active else ""
            tag_str = f"[{m.tag}]"
            row_str = f"{prefix}{m.id:<40} {tag_str:<16} {m.context:<8} {status_str}\n"
            lines.append((line_style, row_str))

        if total > max_rows:
            hint = f"   [Showing {start_idx + 1}-{end_idx} of {total} • ↑/↓ move • type to filter • Enter select • Esc cancel]"
        else:
            hint = f"   [↑/↓ move • type to filter • Enter select • Esc cancel]"
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
        "cursor": "bold #11111b bg:#00ffd7",
        "active": "bold #22c55e",
        "colhead": "bold #94a3b8",
        "dim": "#64748b",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False)
    await app.run_async()
    return result[0]

async def interactive_select_model(session: PromptSession, current_llm, env_path: Path, provider_override: Optional[ProviderProfile] = None):
    """Interactive model selector with live catalog and arrow-key selection."""
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

        prompt_connect = (await session.prompt_async(f"  Connect to {provider.name} now? [Y/n] ❯ ")).strip().lower()
        if prompt_connect in ("", "y", "yes"):
            await interactive_select_provider(session, current_llm, env_path)
            provider = ProviderManager.detect_active_provider(config.API_BASE)
            if not provider.is_local and (not config.API_KEY or config.API_KEY == "your_api_key_here"):
                return
        else:
            console.print("  [dim]Model selection aborted. Use /provider to connect when ready.[/dim]\n")
            return

    console.print(f"\n  [bold #00ffd7]◈ Active Provider:[/bold #00ffd7] [bold #f59e0b]{provider.name}[/bold #f59e0b] [dim]({config.API_BASE})[/dim]")
    with console.status(f"[bold cyan]  Fetching live model catalog from {provider.name}...[/bold cyan]"):
        models = await ProviderManager.get_models_for_provider(provider, api_key=config.API_KEY, api_base=config.API_BASE)

    active_model = config.MODEL

    try:
        selected_model_id = await _run_arrow_key_model_picker(models, active_model, provider.name)
    except Exception:
        selected_model_id = None

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

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False)
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

