# nexus/team/__init__.py
"""AI-Team — spawn and orchestrate a team of specialized AI sub-agents."""

from .manager import TeamManager, PRESET_TEAMS
from .agent import TeamAgent, AgentRole
from .commands import handle_team_command, HELP_TEXT
from .server import start_dashboard_server, stop_dashboard_server

# Alias used by cli.py import
PRESET_TEAMS_REF = PRESET_TEAMS

__all__ = [
    "TeamManager", "TeamAgent", "AgentRole",
    "handle_team_command", "HELP_TEXT",
    "PRESET_TEAMS", "PRESET_TEAMS_REF",
    "start_dashboard_server", "stop_dashboard_server",
]
