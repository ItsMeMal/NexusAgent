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
from ..memory import SQLiteMemory
from ..skills import SkillManager
from ..cron import CronScheduler

def create_default_registry(
    root_dir: Path,
    memory: SQLiteMemory,
    skill_manager: SkillManager,
    cron_scheduler: Optional[CronScheduler] = None,
    subagent_manager: Optional[Any] = None,
    session_id_getter: Optional[Callable[[], str]] = None,
    llm_client: Optional[Any] = None
) -> ToolRegistry:
    registry = ToolRegistry()
    
    # 1. Filesystem Tools (read_file, write_file, patch_file, list_dir, search_files)
    for t in get_filesystem_tools(root_dir):
        registry.register(t)
        
    # 2. Terminal Shell Tools
    for t in get_terminal_tools(root_dir):
        registry.register(t)
        
    # 3. Persistent Memory Tools (SQLite + FTS5)
    for t in get_memory_tools(memory):
        registry.register(t)
        
    # 4. Dynamic Skills Tools
    for t in get_skill_tools(skill_manager):
        registry.register(t)

    # 5. Web & Native Browser Automation Tools
    for t in get_web_tools():
        registry.register(t)
    for t in get_browser_tools(root_dir):
        registry.register(t)

    # 6. Cron / Background Scheduling Tools
    if cron_scheduler:
        for t in get_cron_tools(cron_scheduler):
            registry.register(t)

    # 7. Subagent Orchestration (delegate_task)
    if subagent_manager and session_id_getter:
        for t in get_orchestration_tools(subagent_manager, session_id_getter):
            registry.register(t)

    # 8. Multimodal Vision & Media Output Tools (view_image, image_generate, text_to_speech)
    if llm_client:
        for t in get_vision_tools(llm_client, root_dir):
            registry.register(t)
    for t in get_media_tools(
        root_dir=root_dir,
        api_key=getattr(llm_client, "api_key", "") if llm_client else "",
        api_base=getattr(llm_client, "api_base", "") if llm_client else "",
    ):
        registry.register(t)

    # 9. Computer Use Tools (GUI automation: screenshot, mouse, keyboard, hotkey, scroll, app_launch)
    for t in get_computer_tools(llm_client):
        registry.register(t)
        
    return registry

__all__ = ["Tool", "ToolRegistry", "create_default_registry"]
