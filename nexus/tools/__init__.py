from pathlib import Path
from typing import Optional, Callable, Any
from .base import Tool, ToolRegistry
from .filesystem import get_filesystem_tools
from .terminal import get_terminal_tools
from .memory_tools import get_memory_tools
from .skill_tools import get_skill_tools
from .web import get_web_tools
from .browser import get_browser_tools
from .cron_tools import get_cron_tools
from .delegate import get_orchestration_tools
from .vision import get_vision_tools
from .media import get_media_tools
from .computer import get_computer_tools
from .project import get_project_tools
from .checkpoint_tools import get_checkpoint_tools
from ..memory import SQLiteMemory
from ..skills import SkillManager
from ..cron import CronScheduler


def _register_group(registry: ToolRegistry, toolset: str, tools) -> None:
    for tool in tools:
        registry.register(tool, toolset=toolset)


def create_default_registry(
    root_dir: Path,
    memory: SQLiteMemory,
    skill_manager: SkillManager,
    cron_scheduler: Optional[CronScheduler] = None,
    subagent_manager: Optional[Any] = None,
    session_id_getter: Optional[Callable[[], str]] = None,
    llm_client: Optional[Any] = None,
    toolset_manager: Optional[Any] = None,
    profile: Optional[str] = None,
) -> ToolRegistry:
    """Build every available tool once, then enforce the selected named profile."""
    registry = ToolRegistry()

    # Toolsets are explicit categories rather than an unclassified global tool list.
    _register_group(registry, "filesystem", get_filesystem_tools(root_dir))
    _register_group(registry, "terminal", get_terminal_tools(root_dir))
    _register_group(registry, "memory", get_memory_tools(memory))
    _register_group(registry, "skills", get_skill_tools(skill_manager))
    _register_group(registry, "web", get_web_tools())
    _register_group(registry, "browser", get_browser_tools(root_dir))

    if cron_scheduler:
        _register_group(registry, "cron", get_cron_tools(cron_scheduler))

    if subagent_manager and session_id_getter:
        _register_group(
            registry,
            "orchestration",
            get_orchestration_tools(subagent_manager, session_id_getter),
        )

    if llm_client:
        _register_group(registry, "vision", get_vision_tools(llm_client, root_dir))

    _register_group(
        registry,
        "media",
        get_media_tools(
            root_dir=root_dir,
            api_key=getattr(llm_client, "api_key", "") if llm_client else "",
            api_base=getattr(llm_client, "api_base", "") if llm_client else "",
        ),
    )
    _register_group(registry, "project", get_project_tools(root_dir))
    _register_group(registry, "checkpoints", get_checkpoint_tools(root_dir))
    _register_group(registry, "computer", get_computer_tools(llm_client))

    if toolset_manager:
        toolset_manager.apply(registry, profile=profile)

    return registry


__all__ = ["Tool", "ToolRegistry", "create_default_registry"]
