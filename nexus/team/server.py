"""
nexus/team/server.py
Always-on Nolthira AI Team Dashboard Server (FastAPI + WebSocket).

Runs in background when Nolthira CLI starts (http://127.0.0.1:7891 by default).
Streams real-time AI-Team execution (TeamBoard, Roster, Tool Calls, Mailbox,
Files Touched) and lets users launch new missions, steer follow-ups, inspect
created workspace files, or stop an active run directly from the browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from ..config import config
from ..security import SecurityGuard
from .agent import BUILTIN_ROLES, BUILTIN_ROLES_BY_ID, LEAD_ROLE
from .board import TeamBoard
from .manager import PRESET_TEAMS, TeamManager, TeamRun, auto_mode

logger = logging.getLogger(__name__)

DEFAULT_PORT = int(os.getenv("NEXUS_DASHBOARD_PORT", "7891"))


class DashboardState:
    def __init__(self) -> None:
        self.connections: Set[WebSocket] = set()
        self.current_board: Optional[TeamBoard] = None
        self.history: List[Dict[str, Any]] = []  # serialized board snapshots (last 20)
        self.llm_client = None
        self.memory = None
        self.skill_manager = None
        self.root_dir: Path = config.ROOT_DIR
        self.parent_registry = None
        self.port: int = DEFAULT_PORT
        self._run_lock = asyncio.Lock()
        self._active_task: Optional[asyncio.Task] = None

    def configure(
        self,
        llm_client,
        memory=None,
        skill_manager=None,
        root_dir: Optional[Path] = None,
        parent_registry=None,
    ) -> None:
        self.llm_client = llm_client
        if memory is not None:
            self.memory = memory
        if skill_manager is not None:
            self.skill_manager = skill_manager
        if root_dir is not None:
            self.root_dir = root_dir
        if parent_registry is not None:
            self.parent_registry = parent_registry

    async def broadcast(self, msg: Dict[str, Any]) -> None:
        dead: Set[WebSocket] = set()
        payload = json.dumps(msg, default=str)
        for ws in list(self.connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self.connections -= dead

    def _archive_board(self, board: TeamBoard) -> None:
        snap = board.to_dict()
        self.history = [h for h in self.history if h.get("id") != snap["id"]]
        self.history.insert(0, snap)
        if len(self.history) > 20:
            self.history = self.history[:20]

    def is_running(self) -> bool:
        return bool(self._active_task and not self._active_task.done())

    async def stop_active_run(self) -> bool:
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
            try:
                await self._active_task
            except (asyncio.CancelledError, Exception):
                pass
            return True
        return False

    async def run_team(
        self,
        task: str,
        preset: str = "dev",
        roles: Optional[List[str]] = None,
        mode_override: Optional[str] = None,
        extra_subscriber: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        board_ready_cb: Optional[Callable[[TeamBoard], Any]] = None,
    ) -> Optional[TeamRun]:
        async with self._run_lock:
            if not self.llm_client:
                await self.broadcast({"type": "error", "msg": "LLM client not connected."})
                return None

            selected_roles = list(roles) if roles else list(PRESET_TEAMS.get(preset, PRESET_TEAMS["dev"]))
            mode = mode_override or auto_mode(preset, selected_roles if roles else [])
            if mode == "pipeline":
                mode = "sequential"

            mgr = TeamManager(
                llm_client=self.llm_client,
                memory=self.memory,
                skill_manager=self.skill_manager,
                root_dir=self.root_dir,
                parent_registry=self.parent_registry,
            )

            board = mgr._build_board(
                goal=task,
                preset=preset,
                mode=mode,
                roles=selected_roles,
                include_lead=(mode == "team"),
            )
            self.current_board = board

            async def _ws_forward(ev_type: str, payload: Dict[str, Any]):
                await self.broadcast({"type": ev_type, **payload})

            board.subscribe(_ws_forward)
            if extra_subscriber:
                board.subscribe(extra_subscriber)

            if board_ready_cb:
                try:
                    res = board_ready_cb(board)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

            await self.broadcast({"type": "run_start", "run": board.to_dict()})

            coro = mgr.run_team(
                task=task,
                roles=selected_roles,
                preset=preset,
                mode=mode,
                board=board,
            )
            self._active_task = asyncio.create_task(coro)
            try:
                run = await self._active_task
                self._archive_board(board)
                await self.broadcast({"type": "history_update", "history": self.history})
                return run
            except asyncio.CancelledError:
                self._archive_board(board)
                await self.broadcast({"type": "history_update", "history": self.history})
                raise
            finally:
                self._active_task = None

    async def run_followup(self, prompt: str) -> Optional[TeamRun]:
        async with self._run_lock:
            if not self.llm_client or not self.current_board:
                await self.broadcast({"type": "error", "msg": "No active team session for follow-up."})
                return None

            board = self.current_board
            mgr = TeamManager(
                llm_client=self.llm_client,
                memory=self.memory,
                skill_manager=self.skill_manager,
                root_dir=self.root_dir,
                parent_registry=self.parent_registry,
            )
            self._active_task = asyncio.create_task(mgr.handle_followup(board, prompt))
            try:
                run = await self._active_task
                self._archive_board(board)
                await self.broadcast({"type": "history_update", "history": self.history})
                return run
            except asyncio.CancelledError:
                self._archive_board(board)
                await self.broadcast({"type": "history_update", "history": self.history})
                raise
            finally:
                self._active_task = None


state = DashboardState()
app = FastAPI(title="Nolthira AI Team Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/", response_class=HTMLResponse)
async def index():
    from .dashboard_html import DASHBOARD_HTML
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/api/state")
async def api_state():
    return JSONResponse({
        "connected": state.llm_client is not None,
        "running": state.is_running(),
        "workspace_dir": str(state.root_dir),
        "model": getattr(state.llm_client, "model", "") if state.llm_client else "",
        "current_run": state.current_board.to_dict() if state.current_board else None,
        "history": state.history,
    })


@app.get("/api/file")
async def api_read_file(path: str = Query(..., description="Relative workspace file path")):
    root = state.root_dir.resolve()
    target = (root / path).resolve()
    if not SecurityGuard.is_path_safe(target, root) or not str(target).startswith(str(root)):
        raise HTTPException(status_code=403, detail="Access denied outside workspace")
    if SecurityGuard.is_secret_path(target):
        raise HTTPException(status_code=403, detail="Secret/credential files cannot be previewed")
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > 100_000
        return JSONResponse({
            "path": path,
            "content": content[:100_000],
            "truncated": truncated,
            "size": len(content),
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    state.connections.add(ws)
    await ws.send_text(json.dumps({
        "type": "init",
        "current_run": state.current_board.to_dict() if state.current_board else None,
        "history": state.history,
        "roles": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "toolsets": r.toolsets,
            }
            for r in BUILTIN_ROLES
        ],
        "lead": {
            "id": LEAD_ROLE.id,
            "name": LEAD_ROLE.name,
            "description": LEAD_ROLE.description,
        },
        "presets": dict(PRESET_TEAMS),
        "workspace_dir": str(state.root_dir),
        "model": getattr(state.llm_client, "model", "") if state.llm_client else "",
        "connected": state.llm_client is not None,
        "running": state.is_running(),
    }, default=str))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = msg.get("type")
            if mtype == "run":
                if state.is_running():
                    await ws.send_text(json.dumps({"type": "error", "msg": "A team mission is already running. Stop it first or wait for completion."}))
                    continue
                task = (msg.get("task") or "").strip()
                preset = (msg.get("preset") or "dev").strip().lower()
                roles = msg.get("roles") or []
                mode = msg.get("mode") or None
                if task:
                    asyncio.create_task(state.run_team(task=task, preset=preset, roles=roles, mode_override=mode))
            elif mtype == "followup":
                if state.is_running():
                    await ws.send_text(json.dumps({"type": "error", "msg": "Wait for the active wave to finish or stop it before sending a follow-up."}))
                    continue
                prompt = (msg.get("prompt") or "").strip()
                if prompt:
                    asyncio.create_task(state.run_followup(prompt))
            elif mtype == "stop":
                stopped = await state.stop_active_run()
                await ws.send_text(json.dumps({"type": "status_notice", "msg": "Team mission stopped." if stopped else "No active mission."}))
            elif mtype == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        state.connections.discard(ws)


# ─────────────────────────────────────────────────────────────────────────────
# Server lifecycle
# ─────────────────────────────────────────────────────────────────────────────

_server_task: Optional[asyncio.Task] = None
_server_instance: Optional[uvicorn.Server] = None


def _pick_available_port(preferred: int) -> int:
    for p in range(preferred, preferred + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return preferred


async def start_dashboard_server(
    llm_client,
    port: int = DEFAULT_PORT,
    memory=None,
    skill_manager=None,
    root_dir: Optional[Path] = None,
    parent_registry=None,
) -> int:
    """Start the always-on dashboard server in the background and return its port."""
    global _server_task, _server_instance
    state.configure(
        llm_client=llm_client,
        memory=memory,
        skill_manager=skill_manager,
        root_dir=root_dir,
        parent_registry=parent_registry,
    )
    if _server_task and not _server_task.done():
        return state.port

    chosen_port = _pick_available_port(port)
    state.port = chosen_port
    uv_cfg = uvicorn.Config(app, host="127.0.0.1", port=chosen_port, log_level="error", access_log=False)
    _server_instance = uvicorn.Server(uv_cfg)
    _server_task = asyncio.create_task(_server_instance.serve())
    logger.info("Nolthira AI Team Dashboard started at http://127.0.0.1:%d", chosen_port)
    return chosen_port


async def stop_dashboard_server() -> None:
    global _server_task, _server_instance
    await state.stop_active_run()
    if _server_instance is not None:
        _server_instance.should_exit = True
    if _server_task and not _server_task.done():
        try:
            await asyncio.wait_for(_server_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            if not _server_task.done():
                _server_task.cancel()
                try:
                    await _server_task
                except (asyncio.CancelledError, Exception):
                    pass
