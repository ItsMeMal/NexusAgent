"""
nexus/team/server.py
Always-on Nexus Dashboard Server.

Runs persistently in background when Nexus CLI starts.
Serves the web dashboard at http://localhost:7891 at all times.
Features:
  - Submit tasks from the web UI (prompt input + preset picker)
  - Real-time WebSocket updates for running team
  - Full run history with outputs
  - Nexus agent chat passthrough
"""

from __future__ import annotations

import asyncio
import json
import time
import logging
import uuid
from typing import List, Set, Dict, Optional, Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from .agent import BUILTIN_ROLES_BY_ID, BUILTIN_ROLES
from .manager import TeamManager, auto_mode, PRESET_TEAMS

logger = logging.getLogger(__name__)

DEFAULT_PORT = 7891


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class DashboardState:
    def __init__(self):
        self.connections: Set[WebSocket] = set()
        self.current_run: Dict[str, Any] = {}
        self.history: List[Dict[str, Any]] = []   # last 20 runs
        self.llm_client = None
        self._run_lock = asyncio.Lock()

    def set_llm(self, llm):
        self.llm_client = llm

    async def broadcast(self, msg: dict):
        dead = set()
        payload = json.dumps(msg)
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self.connections -= dead

    async def run_team(self, task: str, preset: str, roles: List[str], mode_override: Optional[str]):
        async with self._run_lock:
            if not self.llm_client:
                await self.broadcast({"type": "error", "msg": "LLM client not connected. Start Nexus CLI first."})
                return

            mode = mode_override or auto_mode(preset, roles if roles else [])
            if not roles:
                roles = PRESET_TEAMS.get(preset, PRESET_TEAMS["dev"])

            run_id = uuid.uuid4().hex[:8]
            start = time.monotonic()

            run = {
                "id": run_id,
                "task": task,
                "preset": preset,
                "mode": mode,
                "roles": roles,
                "agents": {},
                "done": False,
                "total_elapsed": 0.0,
                "started_at": time.strftime("%H:%M:%S"),
            }

            for rid in roles:
                role = BUILTIN_ROLES_BY_ID.get(rid)
                run["agents"][rid] = {
                    "name": role.name if role else rid,
                    "emoji": role.emoji if role else "🤖",
                    "state": "waiting",
                    "elapsed": 0.0,
                    "output": "",
                }

            self.current_run = run
            await self.broadcast({"type": "run_start", "run": run})

            async def mark_running(role_id: str):
                run["agents"][role_id]["state"] = "running"
                run["agents"][role_id]["_started"] = time.monotonic()
                await self.broadcast({"type": "agent_update", "run_id": run_id, "role_id": role_id, "agent": run["agents"][role_id]})

            async def on_progress(role_id: str, result: str):
                agent = run["agents"].get(role_id, {})
                agent["state"] = "done"
                agent["elapsed"] = round(time.monotonic() - agent.get("_started", start), 1)
                agent["output"] = result
                run["total_elapsed"] = round(time.monotonic() - start, 1)
                await self.broadcast({"type": "agent_update", "run_id": run_id, "role_id": role_id, "agent": agent})

            async def pipeline_progress(role_id: str, result: str):
                await on_progress(role_id, result)
                idx = roles.index(role_id) if role_id in roles else -1
                if idx + 1 < len(roles):
                    await mark_running(roles[idx + 1])

            # Mark initial running
            if mode == "parallel":
                for rid in roles:
                    await mark_running(rid)
            elif roles:
                await mark_running(roles[0])

            manager = TeamManager(self.llm_client)
            try:
                if mode == "parallel":
                    result_run = await manager.run_parallel(task, roles, progress_cb=on_progress)
                else:
                    result_run = await manager.run_pipeline(task, roles, progress_cb=pipeline_progress)
            except Exception as exc:
                await self.broadcast({"type": "error", "msg": str(exc)})
                return

            run["done"] = True
            run["total_elapsed"] = round(time.monotonic() - start, 1)
            self.history.insert(0, run)
            if len(self.history) > 20:
                self.history = self.history[:20]
            await self.broadcast({"type": "run_done", "run": run})


state = DashboardState()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/", response_class=HTMLResponse)
async def index():
    from .dashboard_html import DASHBOARD_HTML
    return HTMLResponse(DASHBOARD_HTML)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    state.connections.add(ws)
    # Send initial state
    await ws.send_text(json.dumps({
        "type": "init",
        "current_run": state.current_run,
        "history": state.history,
        "roles": [{"id": r.id, "name": r.name, "emoji": r.emoji, "description": r.description} for r in BUILTIN_ROLES],
        "presets": {k: v for k, v in PRESET_TEAMS.items()},
        "connected": state.llm_client is not None,
    }))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "run":
                task = msg.get("task", "").strip()
                preset = msg.get("preset", "dev")
                roles = msg.get("roles", [])
                mode = msg.get("mode") or None
                if task:
                    asyncio.create_task(state.run_team(task, preset, roles, mode))
            elif msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        state.connections.discard(ws)


# ─────────────────────────────────────────────────────────────────────────────
# Start / stop helpers
# ─────────────────────────────────────────────────────────────────────────────

_server_task: Optional[asyncio.Task] = None


async def start_dashboard_server(llm_client, port: int = DEFAULT_PORT):
    """Start the always-on dashboard server in background."""
    global _server_task
    state.set_llm(llm_client)
    if _server_task and not _server_task.done():
        # Already running — just update llm
        return

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    _server_task = asyncio.create_task(server.serve())
    logger.info("Nexus Dashboard started at http://localhost:%d", port)


async def stop_dashboard_server():
    global _server_task
    if _server_task and not _server_task.done():
        _server_task.cancel()
        try:
            await _server_task
        except asyncio.CancelledError:
            pass


async def notify_run(task: str, roles: List[str], mode: str):
    """Called from CLI /team run to trigger a run via dashboard state."""
    await state.run_team(task, "custom" if roles else "dev", roles, mode)
