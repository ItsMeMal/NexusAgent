import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from nexus.config import config
from nexus.memory import SQLiteMemory
from nexus.skills import SkillManager
from nexus.cron import CronScheduler
from nexus.orchestrator import SubagentManager
from nexus.tools import create_default_registry
from nexus.core import LLMClient, NexusAgent

async def run_tests():
    print("1. Testing SQLiteMemory & FTS5...")
    test_db = Path("test_verify.db")
    memory = SQLiteMemory(test_db)
    memory.store_memory("project_type", "Full Nexus Autonomous Orchestrator", category="metadata")
    results = memory.recall_memories("Orchestrator")
    assert len(results) > 0, "Memory recall failed"
    print("   [OK] Stored and recalled memory:", results[0]["content"])

    print("2. Testing SkillManager...")
    skill_mgr = SkillManager(config.SKILLS_DIR)
    skills = skill_mgr.load_all_skills()
    assert len(skills) > 0, "Skills failed to load"
    print(f"   [OK] Loaded {len(skills)} skill(s)")

    print("3. Testing CronScheduler...")
    cron = CronScheduler(test_db)
    tid = cron.add_task("daily_sync", "daily", "Sync git commits")
    tasks = cron.list_tasks()
    assert len(tasks) > 0, "Cron task not added"
    print(f"   [OK] Cron scheduled task #{tid} created")

    print("4. Testing ToolRegistry & Toolsets...")
    llm = LLMClient(api_key="mock", api_base="https://mock.api", model="mock-model")
    subagent_mgr = SubagentManager(llm=llm, memory=memory, skill_manager=skill_mgr, root_dir=config.ROOT_DIR)
    registry = create_default_registry(
        root_dir=config.ROOT_DIR,
        memory=memory,
        skill_manager=skill_mgr,
        cron_scheduler=cron,
        subagent_manager=subagent_mgr,
        session_id_getter=lambda: "test-sess",
        llm_client=llm
    )
    tools = registry.get_all()
    tool_names = [t.name for t in tools]
    print(f"   [OK] Registered {len(tools)} tools: {tool_names}")
    assert "delegate_task" in tool_names, "delegate_task tool missing"
    assert "web_search" in tool_names, "web_search tool missing"
    assert "web_extract" in tool_names, "web_extract tool missing"
    assert "schedule_task" in tool_names, "schedule_task tool missing"
    assert "search_files" in tool_names, "search_files tool missing"
    assert "view_image" in tool_names, "view_image tool missing"
    assert "computer" in tool_names, "computer tool missing"

    # Test Computer Use tool execution
    comp_tool = registry.get("computer")
    comp_res = await comp_tool.execute(action="cursor_position")
    print(f"   [OK] Computer tool telemetry: {comp_res}")

    print("5. Testing Subagent Scoped Registry Creation...")
    scoped = subagent_mgr.build_scoped_registry(["filesystem", "web"])
    scoped_names = [t.name for t in scoped.get_all()]
    print(f"   [OK] Scoped subagent tools: {scoped_names}")
    assert "read_file" in scoped_names
    assert "delegate_task" not in scoped_names  # Subagents don't get recursive subagents by default

    print("6. Testing System Prompt with SOUL Orchestrator...")
    agent = NexusAgent(llm_client=llm, memory=memory, skill_manager=skill_mgr, registry=registry)
    prompt = agent.build_system_prompt()
    assert "Orchestrator" in prompt
    print("   [OK] Orchestrator System prompt assembled successfully.")

    # Cleanup
    import gc
    gc.collect()
    try:
        test_db.unlink(missing_ok=True)
    except Exception:
        pass
    print("\nALL ORCHESTRATOR TESTS PASSED! 🚀")

if __name__ == "__main__":
    asyncio.run(run_tests())
