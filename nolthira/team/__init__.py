# nexus/team/__init__.py
"""AI-Team — Lead-coordinated multi-agent workspace orchestration."""

from .agent import AgentRole, BUILTIN_ROLES, BUILTIN_ROLES_BY_ID, LEAD_ROLE, TeamAgent
from .board import TeamBoard, TeamMessage, TeamTask, TeamToolEvent
from .commands import HELP_TEXT, handle_team_command
from .manager import PRESET_TEAMS, TeamManager, TeamRun, auto_mode
from .server import start_dashboard_server, state as dashboard_state, stop_dashboard_server

PRESET_TEAMS_REF = PRESET_TEAMS

__all__ = [
    "AgentRole",
    "BUILTIN_ROLES",
    "BUILTIN_ROLES_BY_ID",
    "LEAD_ROLE",
    "TeamAgent",
    "TeamBoard",
    "TeamTask",
    "TeamMessage",
    "TeamToolEvent",
    "TeamManager",
    "TeamRun",
    "PRESET_TEAMS",
    "PRESET_TEAMS_REF",
    "auto_mode",
    "handle_team_command",
    "HELP_TEXT",
    "dashboard_state",
    "start_dashboard_server",
    "stop_dashboard_server",
]
