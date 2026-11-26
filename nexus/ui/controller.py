import sys
import time
import asyncio
from typing import Dict, Any, Optional
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from .tui import (
    build_nexus_mascot_renderable,
    render_tool_call,
    render_tool_result,
    render_subagent_event,
    console
)

class AgentUIController:
    """Coordinates live output, animated Nexus Mascot thinking/loading indicator, and streaming tokens without stdout collisions."""

    def __init__(self, model_name: str, console_instance: Optional[Console] = None, mode_id: str = "auto"):
        self.console = console_instance or console
        self.model_name = model_name
        self.mode_id = mode_id
        self.status = None
        self.live: Optional[Live] = None
        self.stream_started = False
        self.header_printed = False
        self.has_content = False
        self._thinking_active = False
        self._timer_task: Optional[asyncio.Task] = None
        self._start_time = 0.0
        self._current_message = "Thinking & coordinating..."

    def update_model(self, new_model_name: str):
        self.model_name = new_model_name

    def update_mode(self, new_mode_id: str):
        self.mode_id = new_mode_id

    def _render_mascot(self, frame_idx: int, elapsed: float):
        return build_nexus_mascot_renderable(
            frame_idx=frame_idx,
            elapsed=elapsed,
            message=self._current_message,
            model_name=self.model_name,
            width=getattr(self.console, "width", 100) or 100,
            mode_id=self.mode_id,
        )

    def start_thinking(self, message: str = "Thinking & coordinating..."):
        """Start the animated Nexus Mascot with a live ticking elapsed timer."""
        self.stop_status()
        self._thinking_active = True
        self._start_time = time.perf_counter()
        self._current_message = message

        try:
            self.live = Live(
                self._render_mascot(0, 0.0),
                console=self.console,
                refresh_per_second=12,
                transient=True,
            )
            self.live.start()
        except Exception:
            self.live = None

        try:
            loop = asyncio.get_running_loop()
            self._timer_task = loop.create_task(self._thinking_ticker())
        except RuntimeError:
            pass

    async def _thinking_ticker(self):
        """Background coroutine that smoothly animates the Nexus Mascot frames and updates elapsed seconds."""
        idx = 1
        while self._thinking_active and self.live:
            elapsed = time.perf_counter() - self._start_time
            try:
                self.live.update(self._render_mascot(idx, elapsed))
            except Exception:
                break
            idx += 1
            await asyncio.sleep(0.09)

    def stop_status(self):
        """Immediately terminate background ticker and transient mascot live view so stdout is completely free."""
        self._thinking_active = False
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

        if self.live:
            try:
                self.live.stop()
            except Exception:
                pass
            self.live = None

        if self.status:
            try:
                self.status.stop()
            except Exception:
                pass
            self.status = None

    def _print_assistant_header(self):
        if not self.header_printed:
            from ..core.modes import get_mode
            mode_spec = get_mode(self.mode_id)
            model_short = self.model_name.split("/")[-1] if "/" in self.model_name else self.model_name
            self.console.print(
                f"\n[bold #00ffd7]◈ Nexus[/bold #00ffd7] "
                f"[bold {mode_spec.color}]\\[{mode_spec.icon} {mode_spec.label}][/bold {mode_spec.color}] "
                f"[dim]({model_short})[/dim]"
            )
            self.header_printed = True

    def on_token(self, token: str):
        """Called as each streaming token arrives from the LLM."""
        if not self.stream_started:
            if not token.strip():
                return
            # 1. Stop the background spinner & timer immediately before writing to stdout
            self.stop_status()
            self.stream_started = True
            self.has_content = True

            # 2. Print assistant header only once per turn
            self._print_assistant_header()

        # 3. Stream token directly to stdout with immediate flush
        sys.stdout.write(token)
        sys.stdout.flush()

    def on_thought(self, thought: str):
        """Fallback for non-streaming LLM responses."""
        if not thought or not thought.strip():
            return
        self.stop_status()
        self._print_assistant_header()
        self.console.print(Markdown(thought))
        self.console.print()
        self.has_content = True

    def on_tool_call(self, tool_name: str, arguments: Dict[str, Any]):
        """Called when agent initiates a tool execution."""
        self.stop_status()
        if self.stream_started:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.stream_started = False

        render_tool_call(tool_name, arguments)
        self.start_thinking(f"Executing {tool_name}...")

    def on_tool_result(self, tool_name: str, result: str, elapsed: float = 0.0):
        """Called when a tool execution completes."""
        self.stop_status()
        render_tool_result(tool_name, result, elapsed)
        self.start_thinking("Synthesizing next step...")

    def on_subagent_event(self, event_type: str, message: str):
        """Called when a delegated subagent reports progress."""
        self.stop_status()
        render_subagent_event(event_type, message)

    def finish_stream(self):
        """Conclude the turn, stop all spinners, and ensure clean terminal spacing."""
        self.stop_status()
        if self.stream_started:
            sys.stdout.write("\n\n")
            sys.stdout.flush()
            self.stream_started = False
        elif not self.has_content:
            self.console.print()
        self.has_content = False
        self.header_printed = False
