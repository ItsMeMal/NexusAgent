# nexus/team/__init__.py
"""AI-Team — spawn and orchestrate a team of specialized AI sub-agents."""

from .manager import TeamManager
from .agent import TeamAgent, AgentRole
from .commands import handle_team_command, HELP_TEXT

__all__ = ["TeamManager", "TeamAgent", "AgentRole", "handle_team_command", "HELP_TEXT"]
