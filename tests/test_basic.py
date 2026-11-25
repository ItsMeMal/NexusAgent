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

    print("7. Testing Messaging Gateways (Telegram, Discord, WhatsApp) & Plugins...")
    from nexus.plugins import PluginManager
    from nexus.gateways import GatewayManager, GatewayMessage, chunk_text
    from nexus.gateways.discord import _AsyncWebSocket

    pm = PluginManager(workspace_dir=config.WORKSPACE_DIR, codebase_dir=config.CODEBASE_DIR)
    plugin_names = [p.name for p in pm.list_plugins()]
    assert "telegram-gateway" in plugin_names
    assert "discord-gateway" in plugin_names
    assert "whatsapp-gateway" in plugin_names
    print(f"   [OK] Gateway plugins discovered: {plugin_names}")

    gw_mgr = GatewayManager(llm_client=llm, memory=memory, skill_manager=skill_mgr, registry=registry)
    gw_mgr.register_tools(registry)
    assert registry.get("gateway_send") is not None

    # Test allow-list security & WhatsApp webhook extraction
    wa = gw_mgr.gateways["whatsapp"]
    meta_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": [{"wa_id": "6281234567890", "profile": {"name": "Mallss"}}],
                    "messages": [{"id": "wamid.1", "from": "6281234567890", "type": "text", "text": {"body": "/status"}}]
                }
            }]
        }]
    }
    extracted = wa.extract_incoming_messages(meta_payload)
    assert len(extracted) == 1 and extracted[0].user_id == "6281234567890" and extracted[0].text == "/status"
    # Unauthorized by default when allow-list is empty
    denied_reply = await wa.process_message(extracted[0])
    assert "Access Denied" in denied_reply
    # Test chunking and Discord WebSocket frame builder
    chunks = chunk_text("hello\n" * 500, max_length=1000)
    assert len(chunks) > 1 and all(len(c) <= 1000 for c in chunks)
    frame = _AsyncWebSocket.build_frame(b'{"op":1}')
    assert (frame[0] & 0x8F) == 0x81 and (frame[1] & 0x80) == 0x80

    # Test Telegram _handle_update completes & sends reply despite typing_task cancellation
    import os
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TESTTOKEN"
    os.environ["TELEGRAM_ALLOWED_USERS"] = "6966600514"
    tg = gw_mgr.gateways["telegram"]
    sent_payloads = []
    async def mock_send_text(chat_id: str, text: str) -> bool:
        sent_payloads.append((chat_id, text))
        return True
    async def mock_typing(client, chat_id, stop_evt):
        await asyncio.sleep(10)
    tg.send_text = mock_send_text
    tg._send_typing_loop = mock_typing
    await tg._handle_update(None, {
        "update_id": 1,
        "message": {"message_id": 10, "chat": {"id": 6966600514, "type": "private"}, "from": {"id": 6966600514, "username": "mallss"}, "text": "/start"}
    })
    assert len(sent_payloads) == 1 and "Nexus Agent" in sent_payloads[0][1], f"Telegram reply missing: {sent_payloads}"

    print("   [OK] Gateway adapters, allow-list security, WhatsApp parser, Telegram update flow, and WS frame builder verified.")

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
