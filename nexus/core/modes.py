from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass(frozen=True)
class AgentMode:
    """Behavioral operating mode for Nolthira Agent."""
    id: str
    label: str
    icon: str              # Crisp monospace-safe glyph (no wide emoji)
    color: str             # Hex accent color for UI badges
    short_desc: str        # Shown in bottom toolbar & /mode picker
    max_steps_floor: int = 0
    max_steps_cap: Optional[int] = None
    max_temperature: Optional[float] = None
    blocked_tools: Set[str] = field(default_factory=set)
    system_directive: str = ""


MUTATING_TOOLS: Set[str] = {
    "write_file",
    "append_file",
    "patch_file",
    "run_command",
    "computer",
    "schedule_task",
    "cancel_scheduled_task",
    "create_skill",
}

AGENT_MODES: Dict[str, AgentMode] = {
    "auto": AgentMode(
        id="auto",
        label="AUTO",
        icon="◈",
        color="#00ffd7",
        short_desc="Autonomous execution across all tools, skills & subagents",
        system_directive=(
            "## Operating Mode: AUTO (Autonomous)\n"
            "- Decide cleanly between direct response vs. tool execution based on user intent.\n"
            "- Use skills, filesystem, shell, web, memory, and subagents autonomously without asking redundant permissions."
        ),
    ),
    "plan": AgentMode(
        id="plan",
        label="PLAN",
        icon="◇",
        color="#a78bfa",
        short_desc="Read-only research & architecture blueprint (no file edits or shell)",
        max_steps_cap=16,
        blocked_tools=set(MUTATING_TOOLS),
        system_directive=(
            "## Operating Mode: PLAN (Read-Only Architect)\n"
            "- You are strictly in **PLAN / READ-ONLY** mode. Mutating files or running shell commands is disabled.\n"
            "- Inspect relevant skills (`read_skill`), files (`read_file`, `list_dir`, `search_files`), and web docs.\n"
            "- Output a structured, actionable architecture & step-by-step implementation blueprint (files, interfaces, edge cases, verification steps) ready to execute once the user switches back to `auto` or `code`."
        ),
    ),
    "code": AgentMode(
        id="code",
        label="CODE",
        icon="⌘",
        color="#38bdf8",
        short_desc="Deep engineering craft with read-before-edit & mandatory verification",
        max_steps_floor=32,
        max_temperature=0.25,
        system_directive=(
            "## Operating Mode: CODE (Deep Engineering)\n"
            "- Read existing files and applicable coding/UI skills (`read_skill`) BEFORE making changes.\n"
            "- Write clean, modular, well-structured production code (`write_file` / `patch_file`).\n"
            "- Always verify changes by running tests, linters, or build commands via `run_command` before reporting completion."
        ),
    ),
    "ask": AgentMode(
        id="ask",
        label="ASK",
        icon="◎",
        color="#22c55e",
        short_desc="Fast conversational Q&A & read-only lookup (no workspace changes)",
        max_steps_cap=8,
        blocked_tools=set(MUTATING_TOOLS) | {"delegate_task"},
        system_directive=(
            "## Operating Mode: ASK (Fast Q&A & Lookup)\n"
            "- Focus on concise, direct answers, explanations, and quick read-only inspection (`read_file`, `web_search`, `recall_memory`).\n"
            "- Do NOT modify workspace files or run shell commands."
        ),
    ),
    "turbo": AgentMode(
        id="turbo",
        label="TURBO",
        icon="▲",
        color="#f59e0b",
        short_desc="High-budget deep autonomy with parallel subagent fan-out",
        max_steps_floor=40,
        system_directive=(
            "## Operating Mode: TURBO (Deep Multi-Agent Autonomy)\n"
            "- Maximize thoroughness and parallelism. For multi-part tasks, split independent work across subagents via `delegate_task`.\n"
            "- Follow relevant skills, implement end-to-end, verify via tests/commands, and fix any issues automatically before finishing."
        ),
    ),
}

MODE_ORDER: List[str] = ["auto", "plan", "code", "ask", "turbo"]


def get_mode(mode_id: Optional[str]) -> AgentMode:
    """Return a valid AgentMode definition, falling back to 'auto'."""
    key = (mode_id or "auto").strip().lower()
    return AGENT_MODES.get(key, AGENT_MODES["auto"])


def cycle_mode(current_id: Optional[str]) -> AgentMode:
    """Cycle cleanly to the next mode in MODE_ORDER."""
    cur = get_mode(current_id).id
    idx = MODE_ORDER.index(cur)
    next_id = MODE_ORDER[(idx + 1) % len(MODE_ORDER)]
    return AGENT_MODES[next_id]
