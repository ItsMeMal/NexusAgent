"""nexus/team/dashboard_html.py — Full dashboard HTML (separated for maintainability)."""

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexus AI-Team</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg:       #080c14;
  --bg2:      #0d1424;
  --bg3:      #111c2e;
  --border:   #1a2740;
  --border2:  #243654;
  --cyan:     #00ffd7;
  --blue:     #38bdf8;
  --purple:   #a78bfa;
  --green:    #22c55e;
  --red:      #f87171;
  --yellow:   #fbbf24;
  --text:     #e2e8f0;
  --muted:    #64748b;
  --muted2:   #94a3b8;
  --mono:     'JetBrains Mono', monospace;
  --sans:     'Inter', system-ui, sans-serif;
  --radius:   10px;
  --radius-lg:16px;
  --shadow:   0 4px 24px rgba(0,0,0,.5);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.5}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}

/* ── Layout ─────────────────────────────────────────────── */
.app{display:grid;grid-template-columns:260px 1fr;grid-template-rows:52px 1fr;height:100vh;overflow:hidden}

/* ── Topbar ─────────────────────────────────────────────── */
.topbar{grid-column:1/-1;display:flex;align-items:center;gap:12px;padding:0 20px;border-bottom:1px solid var(--border);background:var(--bg2)}
.logo{font-size:15px;font-weight:700;color:var(--cyan);letter-spacing:-.3px;display:flex;align-items:center;gap:7px}
.logo-dot{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan);animation:pulse-dot 2s infinite}
@keyframes pulse-dot{0%,100%{opacity:1;box-shadow:0 0 8px var(--cyan)}50%{opacity:.5;box-shadow:0 0 3px var(--cyan)}}
.topbar-mid{flex:1;display:flex;align-items:center;justify-content:center;gap:8px}
.conn-badge{display:flex;align-items:center;gap:5px;font-size:11px;font-weight:500;padding:3px 10px;border-radius:999px;border:1px solid;transition:.3s}
.conn-badge.online{color:var(--green);border-color:color-mix(in srgb,var(--green) 40%,transparent);background:color-mix(in srgb,var(--green) 8%,transparent)}
.conn-badge.offline{color:var(--muted);border-color:var(--border);background:var(--bg3)}
.conn-dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.topbar-right{display:flex;align-items:center;gap:8px}
.btn-open{font-size:11px;font-weight:600;color:var(--muted2);padding:4px 10px;border:1px solid var(--border);border-radius:6px;cursor:pointer;background:transparent;transition:.2s}
.btn-open:hover{color:var(--cyan);border-color:var(--cyan)}

/* ── Sidebar ─────────────────────────────────────────────── */
.sidebar{background:var(--bg2);border-right:1px solid var(--border);overflow-y:auto;display:flex;flex-direction:column}
.sidebar-section{padding:16px 14px 8px}
.sidebar-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:8px}

/* Prompt form */
.prompt-wrap{padding:14px}
.prompt-textarea{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:var(--sans);font-size:13px;padding:10px 12px;resize:none;min-height:80px;line-height:1.5;outline:none;transition:border-color .2s}
.prompt-textarea:focus{border-color:var(--cyan)}
.prompt-textarea::placeholder{color:var(--muted)}
.prompt-row{display:flex;gap:7px;margin-top:8px;align-items:center}

/* Preset selector */
.preset-select{flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:12px;font-family:var(--sans);padding:6px 10px;outline:none;cursor:pointer}
.preset-select:focus{border-color:var(--blue)}

/* Run button */
.btn-run{padding:7px 14px;border-radius:7px;background:var(--cyan);color:#050a12;font-weight:700;font-size:12px;border:none;cursor:pointer;white-space:nowrap;transition:.15s;font-family:var(--sans)}
.btn-run:hover{filter:brightness(1.1)}
.btn-run:active{transform:scale(.97)}
.btn-run:disabled{opacity:.4;cursor:not-allowed}

/* Mode toggle */
.mode-row{display:flex;gap:5px;margin-top:6px}
.mode-pill{flex:1;text-align:center;padding:5px;border-radius:6px;border:1px solid var(--border);font-size:10px;font-weight:600;cursor:pointer;color:var(--muted);transition:.15s;user-select:none}
.mode-pill.active-seq{color:var(--blue);border-color:var(--blue);background:color-mix(in srgb,var(--blue) 10%,transparent)}
.mode-pill.active-par{color:var(--purple);border-color:var(--purple);background:color-mix(in srgb,var(--purple) 10%,transparent)}
.mode-pill:not(.active-seq):not(.active-par):hover{color:var(--muted2);border-color:var(--border2)}

/* Role pills */
.roles-wrap{padding:0 14px 10px;display:flex;flex-wrap:wrap;gap:5px}
.role-pill{font-size:10px;padding:3px 8px;border-radius:5px;border:1px solid var(--border);color:var(--muted2);cursor:pointer;transition:.15s;user-select:none}
.role-pill:hover{border-color:var(--border2);color:var(--text)}
.role-pill.selected{border-color:var(--cyan);color:var(--cyan);background:color-mix(in srgb,var(--cyan) 8%,transparent)}

/* History list */
.history-item{padding:9px 14px;cursor:pointer;border-left:2px solid transparent;transition:.15s}
.history-item:hover{background:var(--bg3);border-left-color:var(--border2)}
.history-item.active{background:var(--bg3);border-left-color:var(--cyan)}
.history-task{font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.history-meta{font-size:10px;color:var(--muted);margin-top:2px;display:flex;gap:6px}
.hist-preset{color:var(--blue)}
.hist-time{color:var(--muted)}

/* ── Main ────────────────────────────────────────────────── */
.main{overflow-y:auto;display:flex;flex-direction:column;gap:0}

/* Empty state */
.empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--muted);padding:40px}
.empty-icon{font-size:40px;opacity:.4}
.empty-title{font-size:15px;font-weight:600;color:var(--muted2)}
.empty-sub{font-size:12px;text-align:center;max-width:260px;line-height:1.6}

/* Run view */
.run-header{padding:20px 24px 16px;border-bottom:1px solid var(--border);background:var(--bg2);position:sticky;top:0;z-index:10}
.run-title{font-size:13px;font-weight:600;color:var(--muted2);margin-bottom:4px;display:flex;align-items:center;gap:8px}
.run-task{font-size:16px;font-weight:700;color:var(--text);letter-spacing:-.2px}
.run-meta{margin-top:8px;display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted)}
.meta-badge{padding:2px 8px;border-radius:5px;border:1px solid;font-weight:600}
.meta-badge.seq{color:var(--blue);border-color:color-mix(in srgb,var(--blue) 40%,transparent);background:color-mix(in srgb,var(--blue) 8%,transparent)}
.meta-badge.par{color:var(--purple);border-color:color-mix(in srgb,var(--purple) 40%,transparent);background:color-mix(in srgb,var(--purple) 8%,transparent)}
.run-elapsed{font-variant-numeric:tabular-nums;color:var(--muted2)}

/* Agent grid */
.agents-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;padding:20px 24px}

.agent-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-lg);padding:16px;display:flex;flex-direction:column;gap:10px;transition:border-color .3s,box-shadow .3s}
.agent-card.waiting{opacity:.55}
.agent-card.running{border-color:var(--blue);box-shadow:0 0 0 1px color-mix(in srgb,var(--blue) 25%,transparent),0 4px 20px color-mix(in srgb,var(--blue) 10%,transparent);animation:glow-blue 2.5s ease-in-out infinite}
.agent-card.done{border-color:color-mix(in srgb,var(--green) 40%,transparent)}
.agent-card.error{border-color:color-mix(in srgb,var(--red) 40%,transparent)}
@keyframes glow-blue{0%,100%{box-shadow:0 0 0 1px color-mix(in srgb,var(--blue) 25%,transparent),0 4px 20px color-mix(in srgb,var(--blue) 10%,transparent)}50%{box-shadow:0 0 0 2px color-mix(in srgb,var(--blue) 40%,transparent),0 8px 32px color-mix(in srgb,var(--blue) 20%,transparent)}}

.card-emoji{font-size:24px;line-height:1}
.card-name{font-size:13px;font-weight:600;color:var(--text)}
.card-status{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:500}
.card-status.waiting{color:var(--muted)}
.card-status.running{color:var(--blue)}
.card-status.done{color:var(--green)}
.card-status.error{color:var(--red)}
.status-dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex-shrink:0}
.spinner{width:10px;height:10px;border:2px solid color-mix(in srgb,var(--blue) 25%,transparent);border-top-color:var(--blue);border-radius:50%;animation:spin .65s linear infinite;flex-shrink:0}
@keyframes spin{to{transform:rotate(360deg)}}
.card-elapsed{font-size:10px;color:var(--muted);font-variant-numeric:tabular-nums;margin-top:auto}

/* Output sections */
.outputs{padding:0 24px 24px;display:flex;flex-direction:column;gap:16px}
.out-block{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-lg);overflow:hidden;animation:fadeUp .35s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.out-head{padding:12px 16px;background:var(--bg3);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
.out-emoji{font-size:15px}
.out-name{font-size:13px;font-weight:600;color:var(--blue)}
.out-elapsed{margin-left:auto;font-size:10px;color:var(--green);background:color-mix(in srgb,var(--green) 10%,transparent);border:1px solid color-mix(in srgb,var(--green) 25%,transparent);padding:2px 8px;border-radius:999px}
.out-body{padding:16px;font-size:12.5px;line-height:1.75;color:var(--muted2);white-space:pre-wrap;word-break:break-word;max-height:480px;overflow-y:auto;font-family:var(--sans)}
.out-body code{background:var(--bg3);color:var(--blue);padding:1px 5px;border-radius:4px;font-family:var(--mono);font-size:11.5px}
pre.out-body{font-family:var(--mono);font-size:12px;color:#a3c8f5}

/* Done banner */
.done-banner{margin:0 24px 24px;padding:14px 20px;background:color-mix(in srgb,var(--green) 8%,transparent);border:1px solid color-mix(in srgb,var(--green) 25%,transparent);border-radius:var(--radius);text-align:center;color:var(--green);font-weight:600;font-size:13px;animation:fadeUp .4s ease}
</style>
</head>
<body>
<div class="app">

  <!-- ── Topbar ── -->
  <header class="topbar">
    <div class="logo">
      <div class="logo-dot"></div>
      Nexus AI-Team
    </div>
    <div class="topbar-mid">
      <div class="conn-badge offline" id="conn-badge">
        <div class="conn-dot"></div>
        <span id="conn-text">Waiting for CLI…</span>
      </div>
    </div>
    <div class="topbar-right">
      <button class="btn-open" onclick="window.open(location.href,'_blank')">Open in new tab ↗</button>
    </div>
  </header>

  <!-- ── Sidebar ── -->
  <aside class="sidebar">

    <!-- Prompt input -->
    <div class="prompt-wrap">
      <div class="sidebar-label">New Task</div>
      <textarea class="prompt-textarea" id="prompt-input" placeholder="Describe what you want the team to build…" rows="4"></textarea>

      <!-- Preset -->
      <div class="prompt-row">
        <select class="preset-select" id="preset-sel">
          <option value="dev">dev (planner→coder→reviewer→tester)</option>
          <option value="fulldev">fulldev (+writer+devops)</option>
          <option value="audit">audit (security+reviewer)</option>
          <option value="docs">docs (writer)</option>
          <option value="analysis">analysis (analyst)</option>
          <option value="review">review (reviewer+security)</option>
          <option value="custom">custom roles ↓</option>
        </select>
        <button class="btn-run" id="run-btn" onclick="submitRun()" disabled>▶ Run</button>
      </div>

      <!-- Mode toggle -->
      <div class="mode-row">
        <div class="mode-pill active-seq" id="mode-auto" onclick="setMode('auto')">Auto</div>
        <div class="mode-pill" id="mode-seq" onclick="setMode('pipeline')">→ Sequential</div>
        <div class="mode-pill" id="mode-par" onclick="setMode('parallel')">⚡ Parallel</div>
      </div>
    </div>

    <!-- Custom roles -->
    <div id="custom-roles-wrap" style="display:none">
      <div class="sidebar-section">
        <div class="sidebar-label">Custom Roles</div>
      </div>
      <div class="roles-wrap" id="roles-wrap"></div>
    </div>

    <!-- History -->
    <div class="sidebar-section" style="margin-top:4px">
      <div class="sidebar-label">History</div>
    </div>
    <div id="history-list"></div>

  </aside>

  <!-- ── Main ── -->
  <main class="main" id="main">
    <div class="empty" id="empty-state">
      <div class="empty-icon">👥</div>
      <div class="empty-title">AI-Team Dashboard</div>
      <div class="empty-sub">Type a task in the sidebar and hit Run.<br>Or use <code style="background:var(--bg3);padding:1px 5px;border-radius:4px">/team run</code> from the CLI.</div>
    </div>
  </main>

</div>

<script>
// ─────────────── State ───────────────
let ws = null;
let currentMode = 'auto';
let selectedRoles = [];
let currentRunId = null;
let renderedOutputs = new Set();
let startTs = null;
let timerInterval = null;

const ROLES_META = {};  // populated from server

// ─────────────── WebSocket ───────────────
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {
    setConn(true);
    setInterval(() => { try { ws.send(JSON.stringify({type:'ping'})); } catch(_){} }, 20000);
  };

  ws.onclose = () => {
    setConn(false);
    setTimeout(connect, 3000);
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'init') handleInit(msg);
    else if (msg.type === 'run_start') handleRunStart(msg.run);
    else if (msg.type === 'agent_update') handleAgentUpdate(msg);
    else if (msg.type === 'run_done') handleRunDone(msg.run);
    else if (msg.type === 'error') showError(msg.msg);
  };
}

function setConn(online) {
  const badge = document.getElementById('conn-badge');
  const text = document.getElementById('conn-text');
  const btn = document.getElementById('run-btn');
  badge.className = `conn-badge ${online ? 'online' : 'offline'}`;
  text.textContent = online ? 'CLI connected' : 'Waiting for CLI…';
  btn.disabled = !online;
}

// ─────────────── Init ───────────────
function handleInit(msg) {
  // Populate role pills
  const wrap = document.getElementById('roles-wrap');
  wrap.innerHTML = '';
  for (const r of msg.roles) {
    ROLES_META[r.id] = r;
    const pill = document.createElement('div');
    pill.className = 'role-pill';
    pill.dataset.id = r.id;
    pill.title = r.description;
    pill.innerHTML = `${r.emoji} ${r.id}`;
    pill.onclick = () => toggleRole(r.id, pill);
    wrap.appendChild(pill);
  }

  // Restore current run if any
  if (msg.current_run && msg.current_run.task) {
    renderRun(msg.current_run);
  }

  // Render history
  renderHistory(msg.history);

  // Check if connected
  setConn(msg.connected);
}

// ─────────────── Mode & Roles ───────────────
function setMode(m) {
  currentMode = m;
  ['auto','seq','par'].forEach(id => {
    document.getElementById('mode-'+id).className = 'mode-pill';
  });
  if (m === 'auto') document.getElementById('mode-auto').className = 'mode-pill active-seq';
  else if (m === 'pipeline') document.getElementById('mode-seq').className = 'mode-pill active-seq';
  else document.getElementById('mode-par').className = 'mode-pill active-par';
}

function toggleRole(id, el) {
  if (selectedRoles.includes(id)) {
    selectedRoles = selectedRoles.filter(r => r !== id);
    el.classList.remove('selected');
  } else {
    selectedRoles.push(id);
    el.classList.add('selected');
  }
}

document.getElementById('preset-sel').addEventListener('change', function() {
  const isCustom = this.value === 'custom';
  document.getElementById('custom-roles-wrap').style.display = isCustom ? 'block' : 'none';
  if (!isCustom) {
    selectedRoles = [];
    document.querySelectorAll('.role-pill').forEach(p => p.classList.remove('selected'));
  }
});

// ─────────────── Submit ───────────────
function submitRun() {
  const task = document.getElementById('prompt-input').value.trim();
  if (!task || !ws) return;
  const preset = document.getElementById('preset-sel').value;
  const roles = preset === 'custom' ? [...selectedRoles] : [];
  const mode = currentMode === 'auto' ? null : currentMode;

  ws.send(JSON.stringify({ type: 'run', task, preset, roles, mode }));
  document.getElementById('prompt-input').value = '';
}

// Enter = submit (Shift+Enter = newline)
document.getElementById('prompt-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitRun(); }
});

// ─────────────── Run rendering ───────────────
function renderRun(run) {
  currentRunId = run.id;
  renderedOutputs = new Set();
  startTs = Date.now() - run.total_elapsed * 1000;

  const main = document.getElementById('main');
  main.innerHTML = `
    <div class="run-header">
      <div class="run-title">
        <span>👥 AI-Team</span>
        <div class="meta-badge ${run.mode === 'pipeline' ? 'seq' : 'par'}" id="run-mode-badge">
          ${run.mode === 'pipeline' ? '→ sequential' : '⚡ parallel'}
        </div>
      </div>
      <div class="run-task" id="run-task">${esc(run.task)}</div>
      <div class="run-meta">
        <span>${run.preset}</span>
        <span>·</span>
        <span class="run-elapsed" id="run-elapsed">${run.total_elapsed}s</span>
      </div>
    </div>
    <div class="agents-grid" id="agents-grid"></div>
    <div class="outputs" id="outputs"></div>
  `;

  // Start timer
  if (timerInterval) clearInterval(timerInterval);
  if (!run.done) {
    timerInterval = setInterval(() => {
      const el = document.getElementById('run-elapsed');
      if (el) el.textContent = ((Date.now() - startTs) / 1000).toFixed(1) + 's';
    }, 100);
  }

  // Render agent cards
  renderAgentCards(run);

  // Render any already-done outputs
  for (const rid of run.roles) {
    const a = run.agents[rid];
    if (a && (a.state === 'done' || a.state === 'error') && a.output) {
      appendOutput(rid, a);
    }
  }

  if (run.done) showDoneBanner(run);
}

function renderAgentCards(run) {
  const grid = document.getElementById('agents-grid');
  if (!grid) return;
  grid.innerHTML = '';
  for (const rid of run.roles) {
    const a = run.agents[rid] || { name: rid, emoji: '🤖', state: 'waiting', elapsed: 0 };
    const card = document.createElement('div');
    card.className = `agent-card ${a.state}`;
    card.id = `card-${rid}`;
    card.innerHTML = agentCardHTML(rid, a);
    grid.appendChild(card);
  }
}

function agentCardHTML(rid, a) {
  let statusHTML = '';
  if (a.state === 'waiting') statusHTML = `<div class="card-status waiting"><div class="status-dot"></div>waiting</div>`;
  else if (a.state === 'running') statusHTML = `<div class="card-status running"><div class="spinner"></div>running…</div>`;
  else if (a.state === 'done') statusHTML = `<div class="card-status done"><div class="status-dot"></div>done</div>`;
  else statusHTML = `<div class="card-status error"><div class="status-dot"></div>error</div>`;
  return `
    <div class="card-emoji">${a.emoji || '🤖'}</div>
    <div class="card-name">${a.name || rid}</div>
    ${statusHTML}
    <div class="card-elapsed">${a.elapsed ? a.elapsed + 's' : ''}</div>
  `;
}

function handleRunStart(run) {
  renderRun(run);
  renderHistory([]);  // will get history on done
}

function handleAgentUpdate(msg) {
  const { run_id, role_id, agent } = msg;
  if (run_id !== currentRunId) return;

  // Update card
  const card = document.getElementById(`card-${role_id}`);
  if (card) {
    card.className = `agent-card ${agent.state}`;
    card.innerHTML = agentCardHTML(role_id, agent);
  }

  // Append output block when done
  if ((agent.state === 'done' || agent.state === 'error') && agent.output && !renderedOutputs.has(role_id)) {
    renderedOutputs.add(role_id);
    appendOutput(role_id, agent);
  }
}

function appendOutput(rid, agent) {
  const container = document.getElementById('outputs');
  if (!container) return;
  const block = document.createElement('div');
  block.className = 'out-block';
  block.id = `out-${rid}`;
  block.innerHTML = `
    <div class="out-head">
      <span class="out-emoji">${agent.emoji || '🤖'}</span>
      <span class="out-name">${agent.name || rid}</span>
      <span class="out-elapsed">✓ ${agent.elapsed}s</span>
    </div>
    <div class="out-body">${formatOutput(agent.output)}</div>
  `;
  container.appendChild(block);
  block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function handleRunDone(run) {
  if (timerInterval) clearInterval(timerInterval);
  const el = document.getElementById('run-elapsed');
  if (el) el.textContent = run.total_elapsed + 's';
  showDoneBanner(run);
  renderHistory([run]);
}

function showDoneBanner(run) {
  const existing = document.getElementById('done-banner');
  if (existing) return;
  const outputs = document.getElementById('outputs');
  if (!outputs) return;
  const banner = document.createElement('div');
  banner.className = 'done-banner';
  banner.id = 'done-banner';
  banner.textContent = `✅ All ${run.roles.length} agents done in ${run.total_elapsed}s`;
  outputs.appendChild(banner);
}

// ─────────────── History ───────────────
let historyItems = [];
function renderHistory(newItems) {
  if (newItems.length) {
    for (const r of newItems) {
      historyItems = historyItems.filter(h => h.id !== r.id);
      historyItems.unshift(r);
    }
    historyItems = historyItems.slice(0, 20);
  }
  const list = document.getElementById('history-list');
  list.innerHTML = '';
  for (const run of historyItems) {
    const item = document.createElement('div');
    item.className = `history-item ${run.id === currentRunId ? 'active' : ''}`;
    item.onclick = () => { currentRunId = run.id; renderedOutputs = new Set(); renderRun(run); };
    item.innerHTML = `
      <div class="history-task">${esc(run.task)}</div>
      <div class="history-meta">
        <span class="hist-preset">${run.preset}</span>
        <span>·</span>
        <span class="hist-time">${run.started_at || ''} · ${run.total_elapsed}s</span>
      </div>
    `;
    list.appendChild(item);
  }
}

// ─────────────── Helpers ───────────────
function esc(str) {
  return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function formatOutput(str) {
  // Basic markdown-ish: code blocks, inline code, bold
  return esc(str)
    .replace(/```[\w]*\n?([\s\S]*?)```/g, '<pre class="out-body" style="margin:8px 0;padding:12px;background:var(--bg3);border-radius:7px;border:1px solid var(--border);font-size:12px;overflow-x:auto">$1</pre>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong style="color:var(--text)">$1</strong>')
    .replace(/^(#{1,3})\s(.+)$/gm, (_, h, t) => `<strong style="color:var(--cyan);font-size:${h.length===1?'15':'13'}px;display:block;margin-top:12px">${t}</strong>`);
}

function showError(msg) {
  console.error('Dashboard error:', msg);
}

// ─────────────── Boot ───────────────
connect();
</script>
</body>
</html>'''
