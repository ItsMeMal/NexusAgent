"""
nexus/team/dashboard.py
AI-Team Web Dashboard — FastAPI + WebSocket real-time UI.

Flow:
  1. /team run starts a local FastAPI server on port 7891
  2. Browser auto-opens to http://localhost:7891
  3. Each agent status update is broadcast via WebSocket to the page
  4. The page shows live agent cards: waiting → spinning → done with output
  5. Server shuts down automatically when the team run finishes
"""

from __future__ import annotations

import asyncio
import json
import time
import webbrowser
import logging
from pathlib import Path
from typing import List, Set, Dict, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .agent import BUILTIN_ROLES_BY_ID, AgentRole
from .manager import TeamManager, auto_mode, PRESET_TEAMS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# WebSocket connection manager
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        msg = json.dumps(data)
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()
_app_state: Dict = {
    "task": "",
    "mode": "",
    "roles": [],
    "agents": {},   # role_id → {name, emoji, state, elapsed, output}
    "done": False,
    "total_elapsed": 0.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(DASHBOARD_HTML)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Send current state immediately on connect
    await ws.send_text(json.dumps({"type": "state", "data": _app_state}))
    try:
        while True:
            await ws.receive_text()   # keep alive (ping)
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ─────────────────────────────────────────────────────────────────────────────
# Team runner with dashboard broadcast
# ─────────────────────────────────────────────────────────────────────────────

async def run_team_with_dashboard(
    task: str,
    roles: List[str],
    mode: str,
    llm_client,
    port: int = 7891,
):
    """Start dashboard server, open browser, run team, broadcast updates."""

    # Init state
    _app_state["task"] = task
    _app_state["mode"] = mode
    _app_state["roles"] = roles
    _app_state["done"] = False
    _app_state["total_elapsed"] = 0.0
    _app_state["agents"] = {}

    for role_id in roles:
        role = BUILTIN_ROLES_BY_ID.get(role_id)
        _app_state["agents"][role_id] = {
            "name": role.name if role else role_id,
            "emoji": role.emoji if role else "🤖",
            "state": "waiting",
            "elapsed": 0,
            "output": "",
        }

    async def broadcast_state():
        await manager.broadcast({"type": "state", "data": _app_state})

    start_total = time.monotonic()

    async def on_agent_start(role_id: str):
        _app_state["agents"][role_id]["state"] = "running"
        _app_state["agents"][role_id]["started_at"] = time.monotonic()
        await broadcast_state()

    async def on_progress(role_id: str, result: str):
        agent = _app_state["agents"].get(role_id, {})
        started = agent.get("started_at", start_total)
        agent["state"] = "done"
        agent["elapsed"] = round(time.monotonic() - started, 1)
        agent["output"] = result
        _app_state["total_elapsed"] = round(time.monotonic() - start_total, 1)
        await broadcast_state()

    # Start server
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Give server time to start
    await asyncio.sleep(0.8)
    webbrowser.open(f"http://localhost:{port}")

    # Mark first agent running (pipeline) or all (parallel)
    if mode == "parallel":
        for role_id in roles:
            await on_agent_start(role_id)
    else:
        if roles:
            await on_agent_start(roles[0])

    # Wrap progress to also start next agent in pipeline
    async def pipeline_progress(role_id: str, result: str):
        await on_progress(role_id, result)
        idx = roles.index(role_id) if role_id in roles else -1
        if idx + 1 < len(roles):
            await on_agent_start(roles[idx + 1])

    team = TeamManager(llm_client)

    if mode == "parallel":
        run = await team.run_parallel(task, roles, progress_cb=on_progress)
    else:
        run = await team.run_pipeline(task, roles, progress_cb=pipeline_progress)

    _app_state["done"] = True
    _app_state["total_elapsed"] = round(time.monotonic() - start_total, 1)
    await broadcast_state()

    # Keep server alive 60s so user can read results
    await asyncio.sleep(60)
    server.should_exit = True
    await server_task
    return run


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard HTML (single-file, no CDN deps needed)
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexus AI-Team Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: #0a0e1a;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    min-height: 100vh;
    padding: 24px;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .header h1 {
    font-size: 22px;
    font-weight: 700;
    color: #00ffd7;
    letter-spacing: -0.5px;
  }

  .badge {
    font-size: 11px;
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 999px;
    background: #1e293b;
    color: #94a3b8;
    border: 1px solid #334155;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .badge.sequential { color: #38bdf8; border-color: #38bdf8; }
  .badge.parallel { color: #a78bfa; border-color: #a78bfa; }

  .task-bar {
    background: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 10px 16px;
    margin-bottom: 24px;
    font-size: 13px;
    color: #94a3b8;
  }

  .task-bar span { color: #e2e8f0; }

  .timer {
    margin-left: auto;
    font-size: 13px;
    color: #64748b;
    font-variant-numeric: tabular-nums;
  }

  .top-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }

  /* Agent cards row */
  .agents-row {
    display: flex;
    gap: 12px;
    margin-bottom: 28px;
    flex-wrap: wrap;
  }

  .agent-card {
    flex: 1;
    min-width: 150px;
    background: #111827;
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 16px 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: border-color 0.3s, box-shadow 0.3s;
  }

  .agent-card.running {
    border-color: #0ea5e9;
    box-shadow: 0 0 0 1px #0ea5e920, 0 4px 20px #0ea5e915;
    animation: pulse-border 2s infinite;
  }

  .agent-card.done {
    border-color: #22c55e40;
    box-shadow: 0 0 0 1px #22c55e15;
  }

  .agent-card.error {
    border-color: #ef444450;
  }

  @keyframes pulse-border {
    0%, 100% { box-shadow: 0 0 0 1px #0ea5e920, 0 4px 20px #0ea5e915; }
    50% { box-shadow: 0 0 0 2px #0ea5e935, 0 4px 30px #0ea5e925; }
  }

  .agent-emoji { font-size: 22px; }

  .agent-name {
    font-size: 13px;
    font-weight: 600;
    color: #cbd5e1;
  }

  .agent-status {
    font-size: 11px;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .agent-status.waiting { color: #475569; }
  .agent-status.running { color: #38bdf8; }
  .agent-status.done    { color: #22c55e; }
  .agent-status.error   { color: #f87171; }

  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
  }

  .spinner {
    width: 10px;
    height: 10px;
    border: 2px solid #38bdf820;
    border-top-color: #38bdf8;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .agent-elapsed {
    font-size: 11px;
    color: #475569;
    font-variant-numeric: tabular-nums;
    margin-top: auto;
  }

  /* Output sections */
  .outputs { display: flex; flex-direction: column; gap: 20px; }

  .output-block {
    background: #0d1117;
    border: 1px solid #1e293b;
    border-radius: 12px;
    overflow: hidden;
    animation: fadeIn 0.3s ease;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .output-header {
    background: #111827;
    border-bottom: 1px solid #1e293b;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .output-header .emoji { font-size: 16px; }
  .output-header .name { font-weight: 600; font-size: 13px; color: #38bdf8; }
  .output-header .elapsed-badge {
    margin-left: auto;
    font-size: 11px;
    color: #22c55e;
    background: #22c55e15;
    border: 1px solid #22c55e30;
    padding: 2px 8px;
    border-radius: 999px;
  }

  .output-body {
    padding: 16px;
    font-size: 13px;
    line-height: 1.7;
    color: #cbd5e1;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 500px;
    overflow-y: auto;
  }

  /* Markdown-like styling */
  .output-body code {
    background: #1e293b;
    padding: 1px 5px;
    border-radius: 4px;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    font-size: 12px;
    color: #7dd3fc;
  }

  .done-banner {
    display: none;
    background: linear-gradient(135deg, #064e3b, #065f46);
    border: 1px solid #22c55e40;
    border-radius: 12px;
    padding: 16px 20px;
    margin-top: 20px;
    text-align: center;
    color: #22c55e;
    font-weight: 600;
    font-size: 15px;
    animation: fadeIn 0.5s ease;
  }

  .done-banner.show { display: block; }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
</style>
</head>
<body>

<div class="top-row">
  <div class="header">
    <h1>👥 Nexus AI-Team</h1>
  </div>
  <div class="badge" id="mode-badge">—</div>
  <div class="timer" id="timer">0.0s</div>
</div>

<div class="task-bar">
  📋 Task: <span id="task-text">connecting…</span>
</div>

<div class="agents-row" id="agents-row"></div>
<div class="outputs" id="outputs"></div>
<div class="done-banner" id="done-banner">✅ AI-Team done! All agents completed.</div>

<script>
const ws = new WebSocket(`ws://${location.host}/ws`);
let startTime = null;
let timerInterval = null;
let renderedOutputs = new Set();

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'state') render(msg.data);
};

ws.onopen = () => {
  // Send ping every 20s
  setInterval(() => { try { ws.send('ping'); } catch(_) {} }, 20000);
};

function render(state) {
  if (!startTime) {
    startTime = Date.now() - (state.total_elapsed * 1000);
    if (!timerInterval) {
      timerInterval = setInterval(() => {
        const el = document.getElementById('timer');
        if (el) el.textContent = ((Date.now() - startTime) / 1000).toFixed(1) + 's';
      }, 100);
    }
  }

  // Task & mode
  document.getElementById('task-text').textContent = state.task || '—';
  const badge = document.getElementById('mode-badge');
  if (state.mode === 'pipeline') {
    badge.textContent = '→ sequential';
    badge.className = 'badge sequential';
  } else {
    badge.textContent = '⚡ parallel';
    badge.className = 'badge parallel';
  }

  // Agent cards
  const row = document.getElementById('agents-row');
  row.innerHTML = '';
  for (const roleId of state.roles) {
    const a = state.agents[roleId] || {};
    const card = document.createElement('div');
    card.className = `agent-card ${a.state || 'waiting'}`;
    let statusHtml = '';
    if (a.state === 'waiting') statusHtml = `<div class="agent-status waiting"><div class="dot"></div> waiting</div>`;
    else if (a.state === 'running') statusHtml = `<div class="agent-status running"><div class="spinner"></div> running…</div>`;
    else if (a.state === 'done') statusHtml = `<div class="agent-status done"><div class="dot"></div> done</div>`;
    else statusHtml = `<div class="agent-status error"><div class="dot"></div> error</div>`;
    card.innerHTML = `
      <div class="agent-emoji">${a.emoji || '🤖'}</div>
      <div class="agent-name">${a.name || roleId}</div>
      ${statusHtml}
      <div class="agent-elapsed">${a.elapsed ? a.elapsed + 's' : ''}</div>
    `;
    row.appendChild(card);
  }

  // Output blocks — append new ones as agents complete
  for (const roleId of state.roles) {
    const a = state.agents[roleId] || {};
    if ((a.state === 'done' || a.state === 'error') && a.output && !renderedOutputs.has(roleId)) {
      renderedOutputs.add(roleId);
      const block = document.createElement('div');
      block.className = 'output-block';
      block.id = `out-${roleId}`;
      block.innerHTML = `
        <div class="output-header">
          <span class="emoji">${a.emoji || '🤖'}</span>
          <span class="name">${a.name || roleId}</span>
          <span class="elapsed-badge">✓ ${a.elapsed}s</span>
        </div>
        <div class="output-body">${escapeHtml(a.output)}</div>
      `;
      document.getElementById('outputs').appendChild(block);
      block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  // Done banner
  if (state.done) {
    document.getElementById('done-banner').className = 'done-banner show';
    if (timerInterval) {
      clearInterval(timerInterval);
      document.getElementById('timer').textContent = state.total_elapsed + 's';
    }
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}
</script>
</body>
</html>'''
