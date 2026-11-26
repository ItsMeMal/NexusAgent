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

    print("8. Testing MCP Stdio JSON-RPC Transport...")
    import sys, json, tempfile
    from nexus.mcp import MCPManager
    mock_mcp_script = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line:\n"
        "        continue\n"
        "    msg = json.loads(line)\n"
        "    mid = msg.get('id')\n"
        "    method = msg.get('method')\n"
        "    if method == 'initialize':\n"
        "        resp = {'jsonrpc': '2.0', 'id': mid, 'result': {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}}}\n"
        "    elif method == 'tools/list':\n"
        "        resp = {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': [{'name': 'ping', 'description': 'Echo ping', 'inputSchema': {'type': 'object', 'properties': {'msg': {'type': 'string'}}}}]}}\n"
        "    elif method == 'tools/call':\n"
        "        arg = msg.get('params', {}).get('arguments', {}).get('msg', '')\n"
        "        resp = {'jsonrpc': '2.0', 'id': mid, 'result': {'content': [{'type': 'text', 'text': f'pong:{arg}'}]}}\n"
        "    else:\n"
        "        continue\n"
        "    sys.stdout.write(json.dumps(resp) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        server_py = tmp_path / "mock_mcp.py"
        server_py.write_text(mock_mcp_script, encoding="utf-8")
        mcp_cfg = {
            "mcpServers": {
                "mock": {
                    "command": sys.executable,
                    "args": [str(server_py)]
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(mcp_cfg), encoding="utf-8")
        mcp_mgr = MCPManager(workspace_dir=tmp_path, codebase_dir=tmp_path)
        started = await mcp_mgr.start_all()
        assert "mock" in started and "ping" in started["mock"], f"MCP start failed: {started}, errors={mcp_mgr._errors}"
        mcp_mgr.register_mcp_tools(registry)
        mcp_tool = registry.get("mcp_mock_ping")
        assert mcp_tool is not None, "MCP tool not registered"
        call_res = await mcp_tool.execute(msg="nexus")
        assert call_res == "pong:nexus", f"Unexpected MCP tool output: {call_res}"
        statuses = mcp_mgr.get_status()
        assert statuses and statuses[0]["status"] == "running" and statuses[0]["tools"] == 1
        await mcp_mgr.stop_all()
    print("   [OK] MCP stdio handshake, tools/list, tools/call, and cleanup verified.")

    print("9. Testing Remote HTTP MCP Transport + Config Add/Remove...")
    from nexus.mcp import MCPServerConfig

    async def handle_remote_mcp(reader, writer):
        req_line = await reader.readline()
        headers = {}
        while True:
            hline = await reader.readline()
            if hline in (b"\r\n", b"\n", b""):
                break
            k, _, v = hline.decode().partition(":")
            headers[k.strip().lower()] = v.strip()
        clen = int(headers.get("content-length", "0"))
        body = await reader.readexactly(clen) if clen > 0 else b"{}"
        rpc = json.loads(body.decode("utf-8"))
        method = rpc.get("method")
        mid = rpc.get("id")
        if method == "notifications/initialized":
            resp_bytes = b""
            status = "202 Accepted"
            extra_hdr = ""
        else:
            if method == "initialize":
                res_obj = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}}
                extra_hdr = "Mcp-Session-Id: sess-abc-123\r\n"
            elif method == "tools/list":
                assert headers.get("mcp-session-id") == "sess-abc-123", f"Missing session header: {headers}"
                assert headers.get("authorization") == "Bearer test-pat-xyz", f"Missing auth header: {headers}"
                res_obj = {"jsonrpc": "2.0", "id": mid, "result": {"tools": [{"name": "repo_info", "description": "Remote repo info", "inputSchema": {"type": "object", "properties": {"repo": {"type": "string"}}}}]}}
                extra_hdr = ""
            elif method == "tools/call":
                repo = rpc.get("params", {}).get("arguments", {}).get("repo", "")
                res_obj = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"stars:999:{repo}"}]}}
                extra_hdr = ""
            else:
                res_obj = {"jsonrpc": "2.0", "id": mid, "result": {}}
                extra_hdr = ""
            resp_bytes = json.dumps(res_obj).encode("utf-8")
            status = "200 OK"
        raw_http = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(resp_bytes)}\r\n"
            f"{extra_hdr}"
            f"Connection: close\r\n\r\n"
        ).encode("utf-8") + resp_bytes
        writer.write(raw_http)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle_remote_mcp, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with tempfile.TemporaryDirectory() as tmpdir2:
            tmp_p2 = Path(tmpdir2)
            rmgr = MCPManager(workspace_dir=tmp_p2, codebase_dir=tmp_p2)
            os.environ["NEXUS_TEST_MCP_TOKEN"] = "test-pat-xyz"
            rcfg = MCPServerConfig(
                name="ghremote",
                url=f"http://127.0.0.1:{port}/mcp/",
                headers={"Authorization": "Bearer ${NEXUS_TEST_MCP_TOKEN}"},
                transport="http",
            )
            saved_file = rmgr.add_server_to_config(rcfg, scope="workspace")
            assert saved_file.exists()
            rstarted = await rmgr.start_all()
            assert "ghremote" in rstarted and "repo_info" in rstarted["ghremote"], f"Remote start failed: {rstarted}, errors={rmgr._errors}"
            rmgr.register_mcp_tools(registry)
            rtool = registry.get("mcp_ghremote_repo_info")
            assert rtool is not None
            rout = await rtool.execute(repo="ItsMeMal/NexusAgent")
            assert rout == "stars:999:ItsMeMal/NexusAgent", f"Unexpected remote output: {rout}"
            rstatus = rmgr.get_status()
            assert rstatus[0]["transport"] == "http" and rstatus[0]["status"] == "running"
            removed = await rmgr.remove_server("ghremote", registry)
            assert removed and registry.get("mcp_ghremote_repo_info") is None
            await rmgr.stop_all()
    finally:
        server.close()
        await server.wait_closed()
        os.environ.pop("NEXUS_TEST_MCP_TOKEN", None)
    print("   [OK] Remote HTTP MCP transport, env header expansion, session tracking, and add/remove verified.")

    print("10. Testing Agent & Gateway Interrupt / /stop Cancellation...")
    from nexus.gateways.base import GatewayMessage
    from nexus.tools.base import Tool

    slow_started = asyncio.Event()
    async def slow_handler(**kwargs):
        slow_started.set()
        await asyncio.sleep(10)
        return "finished"

    registry.register(Tool(
        name="slow_mock_tool",
        description="Slow test tool",
        parameters={"type": "object", "properties": {}},
        handler=slow_handler,
    ))

    class SlowMockLLM:
        model = "mock-model"
        async def chat_completion(self, messages, tools=None, on_token=None):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "tc_interrupt_1", "type": "function", "function": {"name": "slow_mock_tool", "arguments": "{}"}}],
            }

    tg_int = gw_mgr.gateways["telegram"]
    tg_int.llm = SlowMockLLM()
    run_coro = asyncio.create_task(tg_int.process_message(GatewayMessage(
        platform="telegram", user_id="6966600514", chat_id="99999", text="run slow tool", username="mallss"
    )))
    await asyncio.wait_for(slow_started.wait(), timeout=3.0)
    stop_reply = await tg_int.process_message(GatewayMessage(
        platform="telegram", user_id="6966600514", chat_id="99999", text="/stop", username="mallss"
    ))
    assert "Interrupted" in stop_reply, f"Expected interrupted reply, got: {stop_reply}"
    run_res = await run_coro
    assert run_res is None, f"Expected None on cancelled task, got: {run_res}"
    hist = memory.get_session_history("telegram_99999")
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "tc_interrupt_1" and "Interrupted" in (m.get("content") or "") for m in hist), f"Dangling tool call not cleaned up: {hist}"
    print("   [OK] Gateway /stop cancellation and dangling tool_call memory cleanup verified.")

    print("11. Testing Real AI-Team Orchestrator (Board + Tools + Dashboard API)...")
    from nexus.team import TeamManager, dashboard_state
    from nexus.team.server import api_state, api_read_file
    from fastapi import HTTPException

    class TeamMockLLM:
        model = "mock-team-model"
        def __init__(self):
            self.step_map = {}

        async def chat_completion(self, messages, tools=None, on_token=None):
            sys_txt = messages[0].get("content", "")
            last_role = messages[-1].get("role")
            if "Team Lead" in sys_txt and "Plan this mission" in messages[1].get("content", ""):
                if last_role == "user":
                    return {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "lead_t1",
                                "type": "function",
                                "function": {
                                    "name": "team_create_task",
                                    "arguments": json.dumps({
                                        "title": "Build hello.txt",
                                        "description": "Write hello.txt with 'hello team'",
                                        "assigned_to": "coder",
                                        "depends_on": []
                                    })
                                }
                            },
                            {
                                "id": "lead_t2",
                                "type": "function",
                                "function": {
                                    "name": "team_create_task",
                                    "arguments": json.dumps({
                                        "title": "Verify hello.txt",
                                        "description": "Read hello.txt and confirm content",
                                        "assigned_to": "reviewer",
                                        "depends_on": ["T1"]
                                    })
                                }
                            },
                        ]
                    }
                return {"role": "assistant", "content": "Board planned cleanly."}

            if "Code Writer" in sys_txt:
                if last_role == "user":
                    return {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "coder_w1",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps({"path": "hello.txt", "content": "hello team"})
                            }
                        }]
                    }
                return {"role": "assistant", "content": "Wrote hello.txt."}

            if "Code Reviewer" in sys_txt:
                if last_role == "user":
                    return {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "rev_r1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": "hello.txt"})
                            }
                        }]
                    }
                return {"role": "assistant", "content": "Verified hello.txt contains 'hello team'."}

            return {"role": "assistant", "content": "Mission complete: hello.txt created and verified."}

    with tempfile.TemporaryDirectory() as team_tmp:
        team_root = Path(team_tmp)
        team_llm = TeamMockLLM()
        dashboard_state.configure(
            llm_client=team_llm,
            memory=memory,
            skill_manager=skill_mgr,
            root_dir=team_root,
            parent_registry=registry,
        )
        team_run = await dashboard_state.run_team(
            task="Create hello.txt and verify it",
            preset="custom",
            roles=["coder", "reviewer"],
            mode_override="team",
        )
        assert team_run is not None and team_run.board is not None
        assert (team_root / "hello.txt").read_text(encoding="utf-8") == "hello team"
        assert len(team_run.board.tasks) == 2
        assert all(t.status == "completed" for t in team_run.board.tasks)
        assert any(f["path"] == "hello.txt" and f["by"] == "coder" for f in team_run.board.files_touched)
        assert len(team_run.board.tool_events) >= 4

        # Check Dashboard REST endpoints & path traversal protection
        st_resp = await api_state()
        assert st_resp.status_code == 200
        f_resp = await api_read_file(path="hello.txt")
        assert json.loads(f_resp.body.decode())["content"] == "hello team"
        blocked = False
        try:
            await api_read_file(path="../secret.txt")
        except HTTPException as he:
            blocked = (he.status_code == 403)
        assert blocked, "Path traversal outside workspace must be blocked"
    print("   [OK] Real AI-Team Lead + Shared Task Board + Real File Tools + Dashboard API verified.")

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
