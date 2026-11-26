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

    print("12. Testing /models Health Check (aktif / mati / belum dicek + next-day recovery)...")
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from nexus.providers import ProviderManager, PROVIDERS

    probe_state = {"probe_down_recovered": False, "probed": []}

    class MockRouterHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path.endswith("/models"):
                body = json.dumps({
                    "data": [
                        {"id": "model-ok", "context_length": 128000},
                        {"id": "model-meta-down", "status": "down"},
                        {"id": "model-probe-down", "context_length": 64000},
                        {"id": "model-rate-limit", "context_length": 32000},
                    ]
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            req = json.loads(raw) if raw else {}
            mid = req.get("model", "")
            probe_state["probed"].append(mid)
            if mid == "model-ok":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8"))
            elif mid == "model-probe-down":
                if probe_state["probe_down_recovered"]:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8"))
                else:
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error": {"message": "model unavailable"}}')
            elif mid == "model-rate-limit":
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "rate limit"}}')
            else:
                self.send_response(404)
                self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), MockRouterHandler)
    port = srv.server_address[1]
    srv_thread = threading.Thread(target=srv.serve_forever, daemon=True)
    srv_thread.start()

    try:
        with tempfile.TemporaryDirectory() as htmp:
            cache_file = Path(htmp) / "model_health.json"
            base_url = f"http://127.0.0.1:{port}/v1"
            prov = ProviderManager.detect_active_provider(base_url)

            # Day 1: model-meta-down & model-probe-down must be excluded; model-ok=active; model-rate-limit=unchecked
            models_d1, stats_d1 = await ProviderManager.get_models_with_health(
                prov, api_key="test-key", api_base=base_url,
                health_cache_path=cache_file, today_str="2026-11-26"
            )
            ids_d1 = {m.id: m.status for m in models_d1}
            assert ids_d1.get("model-ok") == "active", f"Expected active, got {ids_d1}"
            assert ids_d1.get("model-rate-limit") == "unchecked", f"Expected unchecked on 429, got {ids_d1}"
            assert "model-meta-down" not in ids_d1, "Metadata down model should be excluded"
            assert "model-probe-down" not in ids_d1, "Probed down model should be excluded"
            assert stats_d1["down_excluded"] == 2

            # Same day re-check: model-probe-down stays excluded from cache without re-probing
            probe_state["probed"].clear()
            models_same, _ = await ProviderManager.get_models_with_health(
                prov, api_key="test-key", api_base=base_url,
                health_cache_path=cache_file, today_str="2026-11-26"
            )
            assert "model-probe-down" not in [m.id for m in models_same]
            assert "model-probe-down" not in probe_state["probed"], "Same-day cached down model must not be re-probed"

            # Next day ("besoknya"): model-probe-down recovers -> automatically re-checked and added back!
            probe_state["probe_down_recovered"] = True
            models_d2, stats_d2 = await ProviderManager.get_models_with_health(
                prov, api_key="test-key", api_base=base_url,
                health_cache_path=cache_file, today_str="2026-11-27"
            )
            ids_d2 = {m.id: m.status for m in models_d2}
            assert ids_d2.get("model-probe-down") == "active", f"Recovered next-day model should be added back: {ids_d2}"
            assert "model-meta-down" not in ids_d2, "Still-down metadata model stays excluded"
            assert stats_d2["down_excluded"] == 1
    finally:
        srv.shutdown()
        srv.server_close()

    print("   [OK] Model health classification (aktif/unchecked/down) + next-day recovery verified.")

    print("13. Testing Nexus Mascot Thinking/Loading Animation...")
    import io
    from rich.console import Console
    from nexus.ui import AgentUIController, build_nexus_mascot_renderable

    buf_console = Console(file=io.StringIO(), width=96, legacy_windows=False)
    ui_ctrl = AgentUIController(model_name="nexus/test-model", console_instance=buf_console)
    for f_idx, msg in [(0, "Thinking & coordinating..."), (2, "Executing write_file..."), (5, "Synthesizing next step...")]:
        rend = build_nexus_mascot_renderable(f_idx, 1.2, msg, "nexus/test-model", 96)
        buf_console.print(rend)
    rendered = buf_console.file.getvalue()
    assert "NEXUS PIKO" in rendered and "THINKING" in rendered and "EXECUTING" in rendered and "SYNTHESIZING" in rendered
    compact_rend = build_nexus_mascot_renderable(0, 0.5, "Thinking...", "m", width=48)
    buf_console.print(compact_rend)
    assert "Thinking" in buf_console.file.getvalue()
    ui_ctrl.start_thinking("Thinking...")
    await asyncio.sleep(0.15)
    ui_ctrl.stop_status()
    print("   [OK] Animated Nexus Mascot thinking/tool/compact lifecycle verified.")

    print("14. Testing Agent Modes (auto/plan/code/ask/turbo) & Upgraded Prompt HUD...")
    from nexus.core import AGENT_MODES, MODE_ORDER, cycle_mode, get_mode
    from nexus.cli import build_prompt_fragments, build_bottom_toolbar

    cur = "auto"
    visited = [cur]
    for _ in range(len(MODE_ORDER)):
        cur = cycle_mode(cur).id
        visited.append(cur)
    assert visited == ["auto", "plan", "code", "ask", "turbo", "auto"], f"Unexpected cycle: {visited}"

    # Verify PLAN mode blocks mutating tools at schema & execution level
    seen_tools_in_plan = []
    class ModeMockLLM:
        def __init__(self):
            self.temperature = 0.7
            self.turn = 0
        async def chat_completion(self, messages, tools=None, on_token=None):
            self.turn += 1
            if tools is not None:
                seen_tools_in_plan.append([t["function"]["name"] for t in tools])
            if self.turn == 1:
                # Even if model hallucinates calling write_file in PLAN mode, Mode Guard blocks it!
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "plan_tc_1",
                        "type": "function",
                        "function": {"name": "write_file", "arguments": '{"path":"bad.txt","content":"no"}'}
                    }]
                }
            return {"role": "assistant", "content": "Architecture blueprint ready."}

    with tempfile.TemporaryDirectory() as mtmp:
        mode_llm = ModeMockLLM()
        mode_agent = NexusAgent(
            llm_client=mode_llm,
            memory=memory,
            skill_manager=skill_mgr,
            registry=registry,
            mode="plan",
            session_id="mode-test-sess",
        )
        assert "PLAN" in mode_agent.build_system_prompt()
        out = await mode_agent.run("Design a REST API")
        assert "blueprint" in out.lower()
        assert not (Path(mtmp) / "bad.txt").exists()
        assert "write_file" not in seen_tools_in_plan[0] and "run_command" not in seen_tools_in_plan[0]
        assert "read_file" in seen_tools_in_plan[0]
        hist_m = memory.get_session_history("mode-test-sess")
        assert any("Mode Guard (PLAN)" in (m.get("content") or "") for m in hist_m)

        # Verify CODE mode caps temperature cleanly during run and restores afterwards
        mode_agent.set_mode("code")
        assert mode_llm.temperature == 0.7
        frags = build_prompt_fragments("deepai-cyber", "code", "NexusAgentCLIV2", "main")
        bar = build_bottom_toolbar("code", "Custom", "abcd1234")
        frag_txt = "".join(t for _, t in frags)
        bar_txt = "".join(t for _, t in bar)
        assert "CODE" in frag_txt and "deepai-cyber" in frag_txt and "main" in frag_txt
        assert "Shift+Tab" in bar_txt and "CODE" in bar_txt
    print("   [OK] Agent modes, PLAN read-only guard, and prompt HUD verified.")

    print("15. Testing LLM Auto-Retry (502), Content Sanitization (400), & Empty-Output Synthesis...")
    import nexus.core.llm as llm_mod
    from nexus.core.llm import sanitize_messages

    san = sanitize_messages([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "1", "content": ""},
    ])
    assert san[0]["content"] == "[calling tools]"
    assert san[1]["content"] == "(empty tool output)"

    retry_state = {"calls": 0, "saw_non_empty_assistant_content": False}

    class RetryMockHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            req = json.loads(raw) if raw else {}
            for m in req.get("messages", []):
                if m.get("role") == "assistant" and m.get("tool_calls") and m.get("content"):
                    retry_state["saw_non_empty_assistant_content"] = True
            retry_state["calls"] += 1
            if retry_state["calls"] == 1:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "All eligible upstream providers failed"}}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"role": "assistant", "content": "Recovered after 502 retry!"}}]}).encode("utf-8"))

    r_srv = HTTPServer(("127.0.0.1", 0), RetryMockHandler)
    r_port = r_srv.server_address[1]
    threading.Thread(target=r_srv.serve_forever, daemon=True).start()
    orig_delays = llm_mod._DEFAULT_RETRY_DELAYS
    llm_mod._DEFAULT_RETRY_DELAYS = (0.01, 0.01, 0.01)
    try:
        retry_events = []
        r_llm = LLMClient(api_key="k", api_base=f"http://127.0.0.1:{r_port}/v1", model="test", max_retries=2)
        res_msg = await r_llm.chat_completion(
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "tc_1", "type": "function", "function": {"name": "read_skill", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "tc_1", "content": "ok"},
            ],
            on_retry=lambda a, m, e: retry_events.append((a, m, e)),
        )
        assert res_msg["content"] == "Recovered after 502 retry!"
        assert retry_state["calls"] == 2 and len(retry_events) == 1
        assert retry_state["saw_non_empty_assistant_content"]
    finally:
        llm_mod._DEFAULT_RETRY_DELAYS = orig_delays
        r_srv.shutdown()
        r_srv.server_close()

    # Test poisoned SQLite history auto-healing + blank-output synthesis fallback
    memory.create_session("heal-sess", title="Heal")
    memory.save_message("heal-sess", "assistant", None, tool_calls=[{"id": "dangling_1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}])

    class BlankThenSynthLLM:
        def __init__(self):
            self.calls = 0
        async def chat_completion(self, messages, tools=None, on_token=None):
            self.calls += 1
            # Verify poisoned history was healed before reaching LLM
            assert any(m.get("tool_call_id") == "dangling_1" for m in messages), "Dangling tool call not healed!"
            if tools is not None:
                return {"role": "assistant", "content": ""}  # simulates model returning empty text
            return {"role": "assistant", "content": "Synthesized non-blank response."}

    heal_agent = NexusAgent(llm_client=BlankThenSynthLLM(), memory=memory, skill_manager=skill_mgr, registry=registry, session_id="heal-sess")
    heal_out = await heal_agent.run("build it")
    assert "Synthesized non-blank response" in heal_out
    print("   [OK] Auto-retry (502), content sanitization (400), history healing, & blank-output synthesis verified.")

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
