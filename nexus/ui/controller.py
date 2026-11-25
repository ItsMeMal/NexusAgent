import sys
import time
import asyncio
from typing import Dict, Any, Optional
from rich.console import Console
from rich.markdown import Markdown

from .tui import (
    render_tool_call,
    render_tool_result,
    render_subagent_event,
    console
)

class AgentUIController:
    """Coordinates live output, animated status spinners with live timers, and streaming tokens without stdout collisions."""

    def __init__(self, model_name: str, console_instance: Optional[Console] = None):
        self.console = console_instance or console
        self.model_name = model_name
        self.status = None
        self.stream_started = False
        self.header_printed = False
        self.has_content = False
        self._thinking_active = False
        self._timer_task: Optional[asyncio.Task] = None
        self._start_time = 0.0
        self._current_message = "Thinking & coordinating..."

    def update_model(self, new_model_name: str):
        self.model_name = new_model_name

    def start_thinking(self, message: str = "Thinking & coordinating..."):
        """Start an animated spinner with a live ticking elapsed timer."""
        self.stop_status()
        self._thinking_active = True
        self._start_time = time.perf_counter()
        self._current_message = message

        self.status = self.console.status(
            f"[bold #00ffd7]⠋[/bold #00ffd7] [bold #38bdf8]Nexus Thinking[/bold #38bdf8] [dim]· {message} (0.0s · Ctrl+C/Esc to stop)[/dim]",
            spinner="dots"
        )
        self.status.start()

        try:
            loop = asyncio.get_running_loop()
            self._timer_task = loop.create_task(self._thinking_ticker())
        except RuntimeError:
            pass

    async def _thinking_ticker(self):
        """Background coroutine that smoothly pulses the spinner and updates elapsed seconds."""
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        while self._thinking_active and self.status:
            elapsed = time.perf_counter() - self._start_time
            spin = spinners[idx % len(spinners)]
            try:
                self.status.update(
                    f"[bold #00ffd7]{spin}[/bold #00ffd7] [bold #38bdf8]Nexus Thinking[/bold #38bdf8] [dim]· {self._current_message} ({elapsed:.1f}s · Ctrl+C/Esc to stop)[/dim]"
                )
            except Exception:
                break
            idx += 1
            await asyncio.sleep(0.08)

    def stop_status(self):
        """Immediately terminate background ticker and spinner so stdout is completely free."""
        self._thinking_active = False
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

        if self.status:
            try:
                self.status.stop()
            except Exception:
                pass
            self.status = None

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
            if not self.header_printed:
                model_short = self.model_name.split("/")[-1] if "/" in self.model_name else self.model_name
                self.console.print(f"\n[bold #00ffd7]◈ Nexus[/bold #00ffd7] [dim]({model_short})[/dim]")
                self.header_printed = True

        # 3. Stream token directly to stdout with immediate flush
        sys.stdout.write(token)
        sys.stdout.flush()

    def on_thought(self, thought: str):
        """Fallback for non-streaming LLM responses."""
        if not thought or not thought.strip():
            return
        self.stop_status()
        if not self.header_printed:
            model_short = self.model_name.split("/")[-1] if "/" in self.model_name else self.model_name
            self.console.print(f"\n[bold #00ffd7]◈ Nexus[/bold #00ffd7] [dim]({model_short})[/dim]")
            self.header_printed = True
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
