"""nolthira/team/dashboard_html.py — Redesigned always-on AI-Team Control Room UI."""

DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nolthira AI Team</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg:        #0a0e16;
  --rail:      #0f1520;
  --surface:   #141c2b;
  --surface-2: #192336;
  --border:    #1f2b42;
  --border-2:  #2c3d5e;
  --accent:    #14f1d9;
  --accent-fg: #051316;
  --info:      #38bdf8;
  --lead:      #a78bfa;
  --success:   #22c55e;
  --warning:   #f59e0b;
  --danger:    #f87171;
  --text:      #e6edf6;
  --text-2:    #94a3b8;
  --text-3:    #64748b;
  --sans:      'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --mono:      'JetBrains Mono', ui-monospace, 'Cascadia Code', Consolas, monospace;
  --r-sm:      6px;
  --r-md:      10px;
  --r-lg:      12px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  height: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  font-size: 13.5px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

::selection { background: color-mix(in srgb, var(--accent) 28%, transparent); color: var(--text); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-2); }

/* ── App Shell ─────────────────────────────────────────── */
.shell {
  display: grid;
  grid-template-columns: 300px 1fr;
  grid-template-rows: 52px 1fr;
  height: 100vh;
  overflow: hidden;
}

/* ── Topbar ────────────────────────────────────────────── */
.topbar {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 18px;
  background: var(--rail);
  border-bottom: 1px solid var(--border);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 14px;
  letter-spacing: -0.02em;
  color: var(--text);
}
.brand-mark {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
}
.top-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chip.mono { font-family: var(--mono); font-size: 11px; }
.chip.online {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 35%, transparent);
  background: color-mix(in srgb, var(--success) 10%, transparent);
}
.chip.offline {
  color: var(--warning);
  border-color: color-mix(in srgb, var(--warning) 35%, transparent);
  background: color-mix(in srgb, var(--warning) 10%, transparent);
}
.dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex-shrink: 0; }
.top-actions { display: flex; align-items: center; gap: 8px; }
.icon-btn, .menu-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--sans);
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease, color 150ms ease;
}
.icon-btn:hover, .menu-toggle:hover {
  background: var(--surface-2);
  border-color: var(--border-2);
  color: var(--text);
}
.menu-toggle { display: none; }

/* ── Sidebar Rail ──────────────────────────────────────── */
.rail {
  background: var(--rail);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  min-height: 0;
}
.rail-block {
  padding: 16px;
  border-bottom: 1px solid var(--border);
}
.rail-heading {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.field-label {
  display: block;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-2);
  margin-bottom: 6px;
}
textarea.composer {
  width: 100%;
  min-height: 92px;
  padding: 10px 12px;
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-family: var(--sans);
  font-size: 13px;
  line-height: 1.5;
  resize: vertical;
  caret-color: var(--accent);
  transition: border-color 150ms ease;
}
textarea.composer::placeholder { color: var(--text-3); }
textarea.composer:focus { outline: none; border-color: var(--accent); }

.controls-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}
select.select {
  width: 100%;
  padding: 7px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-family: var(--sans);
  font-size: 12.5px;
  cursor: pointer;
}
select.select:focus { outline: none; border-color: var(--accent); }

.seg {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  padding: 3px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--bg);
}
.seg-btn {
  padding: 5px 6px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-3);
  font-family: var(--sans);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}
.seg-btn:hover { color: var(--text-2); }
.seg-btn.active {
  background: var(--surface-2);
  color: var(--text);
}

.role-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.role-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 150ms ease, color 150ms ease, background-color 150ms ease;
}
.role-chip:hover { border-color: var(--border-2); color: var(--text); }
.role-chip.selected {
  border-color: var(--accent);
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.btn-row { display: flex; gap: 8px; margin-top: 12px; }
.btn-primary {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: var(--r-sm);
  border: none;
  background: var(--accent);
  color: var(--accent-fg);
  font-family: var(--sans);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 150ms ease, transform 120ms ease;
}
.btn-primary:hover:not(:disabled) { opacity: 0.92; }
.btn-primary:active:not(:disabled) { transform: scale(0.985); }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 8px 12px;
  border-radius: var(--r-sm);
  border: 1px solid color-mix(in srgb, var(--danger) 40%, transparent);
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  color: var(--danger);
  font-family: var(--sans);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 150ms ease;
}
.btn-danger:hover { background: color-mix(in srgb, var(--danger) 20%, transparent); }

/* History */
.history-wrap { padding: 12px; flex: 1; overflow-y: auto; }
.history-empty { padding: 16px 8px; font-size: 12px; color: var(--text-3); }
.history-item {
  width: 100%;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 9px 10px;
  margin-bottom: 4px;
  border-radius: var(--r-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  font-family: var(--sans);
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}
.history-item:hover { background: var(--surface); }
.history-item.active {
  background: var(--surface);
  border-color: var(--border-2);
}
.hist-title {
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hist-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

/* ── Main Stage ────────────────────────────────────────── */
.stage {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--bg);
}
.stage-scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

/* Empty Onboarding State */
.empty-stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
  text-align: center;
}
.empty-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--accent);
  display: grid;
  place-items: center;
  margin-bottom: 16px;
}
.empty-stage h1 {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  margin-bottom: 8px;
}
.empty-stage p {
  max-width: 46ch;
  color: var(--text-2);
  font-size: 13px;
  margin-bottom: 20px;
}
.quick-prompts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  width: 100%;
  max-width: 720px;
}
.quick-card {
  text-align: left;
  padding: 12px 14px;
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--rail);
  color: var(--text);
  font-family: var(--sans);
  cursor: pointer;
  transition: border-color 150ms ease, background-color 150ms ease;
}
.quick-card:hover { border-color: var(--border-2); background: var(--surface); }
.quick-card strong { display: block; font-size: 12.5px; font-weight: 600; margin-bottom: 3px; }
.quick-card span { font-size: 11.5px; color: var(--text-2); }

/* Mission Header */
.mission-bar {
  padding: 16px 22px;
  border-bottom: 1px solid var(--border);
  background: var(--rail);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.mission-info { min-width: 0; flex: 1; }
.mission-title {
  font-size: 15.5px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text);
  word-break: break-word;
}
.mission-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  text-transform: capitalize;
}
.status-pill.planning  { color: var(--lead); border-color: color-mix(in srgb, var(--lead) 35%, transparent); }
.status-pill.executing { color: var(--info); border-color: color-mix(in srgb, var(--info) 35%, transparent); }
.status-pill.reviewing { color: var(--warning); border-color: color-mix(in srgb, var(--warning) 35%, transparent); }
.status-pill.completed { color: var(--success); border-color: color-mix(in srgb, var(--success) 35%, transparent); }
.status-pill.failed, .status-pill.cancelled { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, transparent); }

/* Roster Strip */
.roster-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(185px, 1fr));
  gap: 10px;
  padding: 16px 22px 10px;
}
.agent-tile {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 13px;
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--rail);
  text-align: left;
  cursor: pointer;
  font-family: var(--sans);
  color: var(--text);
  transition: border-color 180ms ease, background-color 180ms ease;
}
.agent-tile:hover { border-color: var(--border-2); background: var(--surface); }
.agent-tile.selected { border-color: var(--accent); background: var(--surface); }
.agent-tile.thinking, .agent-tile.tool {
  border-color: color-mix(in srgb, var(--info) 60%, transparent);
  background: var(--surface);
}
.agent-tile.done { border-color: color-mix(in srgb, var(--success) 32%, transparent); }
.agent-tile.error, .agent-tile.cancelled { border-color: color-mix(in srgb, var(--danger) 35%, transparent); }

.tile-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.tile-id {
  display: flex;
  align-items: center;
  gap: 7px;
  font-weight: 600;
  font-size: 12.5px;
  min-width: 0;
}
.tile-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: var(--surface-2);
  color: var(--text-2);
  flex-shrink: 0;
}
.agent-tile.is-lead .tile-icon { color: var(--lead); }
.agent-tile.thinking .tile-icon, .agent-tile.tool .tile-icon { color: var(--info); }
.agent-tile.done .tile-icon { color: var(--success); }

.tile-time {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.tile-activity {
  font-size: 11.5px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-height: 17px;
}
.tile-activity.tool-call { font-family: var(--mono); font-size: 11px; color: var(--info); }
.tile-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.state-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 500;
}
.state-tag.waiting { color: var(--text-3); }
.state-tag.thinking, .state-tag.tool { color: var(--info); }
.state-tag.done { color: var(--success); }
.state-tag.error, .state-tag.cancelled { color: var(--danger); }

.spin {
  width: 10px;
  height: 10px;
  border: 1.75px solid color-mix(in srgb, var(--info) 25%, transparent);
  border-top-color: var(--info);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Main Split Panels ─────────────────────────────────── */
.workspace-grid {
  display: grid;
  grid-template-columns: minmax(300px, 0.95fr) minmax(360px, 1.25fr);
  gap: 14px;
  padding: 10px 22px 22px;
  flex: 1;
}

.panel {
  display: flex;
  flex-direction: column;
  border-radius: var(--r-lg);
  border: 1px solid var(--border);
  background: var(--rail);
  min-height: 320px;
  overflow: hidden;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.panel-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 7px;
}
.count-pill {
  font-family: var(--mono);
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.tabs { display: flex; gap: 4px; }
.tab-btn {
  padding: 4px 10px;
  border-radius: var(--r-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-2);
  font-family: var(--sans);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}
.tab-btn:hover { color: var(--text); background: var(--surface-2); }
.tab-btn.active {
  background: var(--bg);
  color: var(--text);
  border-color: var(--border-2);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 540px;
}

/* Task Board Rows */
.task-row {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--surface);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.task-row.in_progress { border-color: color-mix(in srgb, var(--info) 45%, transparent); }
.task-row.completed { border-color: color-mix(in srgb, var(--success) 30%, transparent); }
.task-row.failed, .task-row.blocked { border-color: color-mix(in srgb, var(--danger) 35%, transparent); }
.task-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.task-id-badge {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-2);
  margin-right: 6px;
}
.task-title { font-size: 12.5px; font-weight: 600; color: var(--text); }
.task-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-2);
}
.assignee-tag {
  font-family: var(--mono);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--accent);
}
.dep-tag {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-3);
}
.task-result {
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}

/* Message Feed */
.msg-card {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--surface);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.msg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
}
.msg-route {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.msg-sender { color: var(--info); }
.msg-sender.lead { color: var(--lead); }
.msg-sender.user { color: var(--accent); }
.msg-kind {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--text-3);
}
.msg-time { font-family: var(--mono); font-size: 10.5px; color: var(--text-3); }
.msg-body {
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-body code, .task-result code {
  font-family: var(--mono);
  font-size: 11.5px;
  background: var(--bg);
  color: var(--info);
  padding: 1px 5px;
  border-radius: 4px;
}
.code-pre {
  margin: 6px 0;
  padding: 10px 12px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--bg);
  font-family: var(--mono);
  font-size: 11.5px;
  color: #b7d4f6;
  overflow-x: auto;
  white-space: pre;
}

/* Tool Trace */
.tool-row {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--surface);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tool-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
}
.tool-left {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}
.tool-agent { font-weight: 600; color: var(--text-2); }
.tool-fn { font-family: var(--mono); font-size: 11.5px; color: var(--info); font-weight: 500; }
.tool-args {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tool-res {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 8px;
  max-height: 110px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Files Touched + Inline Preview */
.file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 11px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-family: var(--sans);
  cursor: pointer;
  width: 100%;
  text-align: left;
  transition: border-color 150ms ease, background-color 150ms ease;
}
.file-row:hover { border-color: var(--border-2); background: var(--surface-2); }
.file-path { font-family: var(--mono); font-size: 12px; color: var(--accent); word-break: break-all; }
.file-meta { font-size: 11px; color: var(--text-3); white-space: nowrap; }
.file-preview-box {
  border: 1px solid var(--border-2);
  border-radius: var(--r-md);
  background: var(--bg);
  overflow: hidden;
}
.file-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 11px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  font-family: var(--mono);
  font-size: 11.5px;
}
.file-preview-code {
  padding: 12px;
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--text);
  max-height: 280px;
  overflow: auto;
  white-space: pre;
}

/* Follow-up Steering Bar */
.followup-bar {
  display: flex;
  gap: 8px;
  padding: 12px 22px;
  border-top: 1px solid var(--border);
  background: var(--rail);
}
.followup-input {
  flex: 1;
  padding: 9px 12px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-family: var(--sans);
  font-size: 13px;
  caret-color: var(--accent);
}
.followup-input:focus { outline: none; border-color: var(--accent); }
.followup-input::placeholder { color: var(--text-3); }

/* Toast */
.toast {
  position: fixed;
  bottom: 18px;
  right: 18px;
  padding: 9px 14px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border-2);
  background: var(--surface-2);
  color: var(--text);
  font-size: 12.5px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
  z-index: 100;
  display: none;
}
.toast.show { display: block; }
.toast.err { border-color: color-mix(in srgb, var(--danger) 50%, transparent); color: var(--danger); }

/* Responsive */
@media (max-width: 960px) {
  .shell { grid-template-columns: 1fr; }
  .menu-toggle { display: inline-flex; }
  .rail {
    position: fixed;
    top: 52px;
    left: 0;
    bottom: 0;
    width: 300px;
    z-index: 40;
    transform: translateX(-100%);
    transition: transform 200ms ease;
    box-shadow: 8px 0 32px rgba(0,0,0,0.6);
  }
  .rail.open { transform: translateX(0); }
  .workspace-grid { grid-template-columns: 1fr; padding: 10px 14px 18px; }
  .roster-strip { padding: 14px 14px 8px; }
  .mission-bar, .followup-bar { padding: 12px 14px; }
  .top-meta .hide-sm { display: none; }
}
</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <div class="brand">
      <button class="menu-toggle" onclick="toggleRail()" aria-label="Toggle sidebar">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <div class="brand-mark" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
      </div>
      <span>Nolthira AI Team</span>
    </div>

    <div class="top-meta">
      <span class="chip mono hide-sm" id="workspace-chip" title="Active Workspace Directory">-</span>
      <span class="chip mono hide-sm" id="model-chip">-</span>
      <span class="chip offline" id="conn-chip"><span class="dot"></span><span id="conn-label">Connecting</span></span>
    </div>

    <div class="top-actions">
      <button class="icon-btn" onclick="window.open(location.href, '_blank')">
        <span>New Tab</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </button>
    </div>
  </header>

  <aside class="rail" id="rail">
    <div class="rail-block">
      <div class="rail-heading">
        <span>Launch Team Mission</span>
      </div>
      <label class="field-label" for="prompt-input">Goal or Instruction</label>
      <textarea class="composer" id="prompt-input" placeholder="Describe what the AI-Team should inspect, build, verify, or audit in your workspace..."></textarea>

      <div class="controls-stack">
        <div>
          <label class="field-label" for="preset-select">Squad Preset</label>
          <select class="select" id="preset-select">
            <option value="dev">dev — Lead + Planner, Coder, Reviewer, Tester</option>
            <option value="fulldev">fulldev — Full squad (+ Writer, DevOps)</option>
            <option value="audit">audit — Security + Code Reviewer</option>
            <option value="review">review — Reviewer + Security</option>
            <option value="docs">docs — Technical Writer</option>
            <option value="analysis">analysis — Data Analyst</option>
            <option value="custom">Custom roster</option>
          </select>
        </div>

        <div>
          <span class="field-label">Coordination</span>
          <div class="seg" role="group" aria-label="Coordination mode">
            <button type="button" class="seg-btn active" id="mode-auto" onclick="setMode('auto')">Lead (Auto)</button>
            <button type="button" class="seg-btn" id="mode-parallel" onclick="setMode('parallel')">Parallel</button>
            <button type="button" class="seg-btn" id="mode-sequential" onclick="setMode('sequential')">Sequential</button>
          </div>
        </div>

        <div id="custom-roles-box" style="display:none">
          <span class="field-label">Select Specialists</span>
          <div class="role-grid" id="role-grid"></div>
        </div>
      </div>

      <div class="btn-row">
        <button type="button" class="btn-primary" id="run-btn" onclick="submitMission()" disabled>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>
          <span>Launch Team</span>
        </button>
        <button type="button" class="btn-danger" id="stop-btn" onclick="stopMission()" style="display:none">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
          <span>Stop</span>
        </button>
      </div>
    </div>

    <div class="history-wrap">
      <div class="rail-heading">
        <span>Mission History</span>
        <span class="count-pill" id="history-count">0</span>
      </div>
      <div id="history-list">
        <div class="history-empty">No missions recorded in this session yet.</div>
      </div>
    </div>
  </aside>

  <main class="stage">
    <div class="stage-scroll" id="stage-scroll">
      <div class="empty-stage" id="empty-stage">
        <div class="empty-icon" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
        </div>
        <h1>Autonomous AI-Team Workspace</h1>
        <p>Launch a mission from the sidebar or run <code style="font-family:var(--mono);background:var(--surface);padding:2px 6px;border-radius:4px">/team run</code> in Nolthira CLI. The Team Lead plans a Shared Task Board, specialists execute with real workspace tools, and everything updates live here.</p>
        <div class="quick-prompts">
          <button type="button" class="quick-card" onclick="fillPrompt('Inspect the repository, find bugs or missing edge cases, and report concrete fixes.', 'audit')">
            <strong>Codebase & Security Audit</strong>
            <span>Reviewer + Security inspect files and report concrete issues.</span>
          </button>
          <button type="button" class="quick-card" onclick="fillPrompt('Create a clean landing page in web/ with responsive layout, CSS, and interactive JS, then verify it.', 'dev')">
            <strong>Build & Verify Feature</strong>
            <span>Lead + Planner, Coder, Reviewer, Tester work in waves.</span>
          </button>
          <button type="button" class="quick-card" onclick="fillPrompt('Inspect existing modules and write concise developer documentation in README_TEAM.md.', 'docs')">
            <strong>Ground-Truth Docs</strong>
            <span>Writer reads workspace source files and writes accurate docs.</span>
          </button>
        </div>
      </div>
    </div>

    <form class="followup-bar" id="followup-bar" style="display:none" onsubmit="submitFollowup(event)">
      <input class="followup-input" id="followup-input" type="text" placeholder="Steer the team or mention a role (e.g. @coder update the CSS color, @tester run pytest)...">
      <button type="submit" class="btn-primary" style="flex:0 0 auto" id="followup-btn">Send</button>
    </form>
  </main>
</div>

<div class="toast" id="toast"></div>

<script>
const ROLE_ICONS = {
  lead: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>',
  planner: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>',
  coder: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  reviewer: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  tester: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6"/><path d="M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3"/></svg>',
  writer: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  analyst: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
  devops: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  security: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>'
};

let ws = null;
let modeChoice = 'auto';
let selectedCustomRoles = [];
let activeRun = null;
let historyList = [];
let activeStreamTab = 'feed'; // feed | tools | files
let agentFilter = null;
let previewFile = null; // {path, content, size, truncated}
let timerHandle = null;
let runStartLocal = 0;

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    setConnection(true);
  };
  ws.onclose = () => {
    setConnection(false);
    setTimeout(connectWS, 2500);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'init') {
      document.getElementById('workspace-chip').textContent = msg.workspace_dir || '-';
      document.getElementById('workspace-chip').title = msg.workspace_dir || '';
      document.getElementById('model-chip').textContent = msg.model || '-';
      setConnection(!!msg.connected);
      renderRoleChips(msg.roles || []);
      historyList = msg.history || [];
      renderHistory();
      if (msg.current_run && msg.current_run.id) {
        loadRun(msg.current_run);
      }
      updateRunControls(!!msg.running);
    } else if (msg.type === 'run_start') {
      historyList = [msg.run, ...historyList.filter(h => h.id !== msg.run.id)].slice(0, 20);
      loadRun(msg.run);
      renderHistory();
      updateRunControls(true);
    } else if (msg.type === 'agent_update') {
      if (activeRun && activeRun.id === msg.run_id) {
        activeRun.agents[msg.role_id] = msg.agent;
        renderRoster();
        renderHeaderStats();
      }
    } else if (msg.type === 'board_update') {
      if (activeRun && activeRun.id === msg.run_id) {
        activeRun.tasks = msg.tasks || [];
        renderTasks();
        renderHeaderStats();
      }
    } else if (msg.type === 'message') {
      if (activeRun && activeRun.id === msg.run_id) {
        activeRun.messages.push(msg.message);
        if (activeStreamTab === 'feed') renderStreamBody();
      }
    } else if (msg.type === 'tool_event') {
      if (activeRun && activeRun.id === msg.run_id) {
        const idx = activeRun.tool_events.findIndex(e => e.id === msg.event.id);
        if (idx >= 0) activeRun.tool_events[idx] = msg.event;
        else activeRun.tool_events.push(msg.event);
        renderHeaderStats();
        if (activeStreamTab === 'tools') renderStreamBody();
      }
    } else if (msg.type === 'file_touched') {
      if (activeRun && activeRun.id === msg.run_id) {
        activeRun.files_touched = msg.files || [];
        renderHeaderStats();
        if (activeStreamTab === 'files') renderStreamBody();
      }
    } else if (msg.type === 'run_done') {
      if (msg.run) {
        historyList = [msg.run, ...historyList.filter(h => h.id !== msg.run.id)].slice(0, 20);
        if (!activeRun || activeRun.id === msg.run.id) {
          loadRun(msg.run);
        }
        renderHistory();
      }
      updateRunControls(false);
    } else if (msg.type === 'history_update') {
      historyList = msg.history || [];
      renderHistory();
    } else if (msg.type === 'status_notice') {
      toast(msg.msg, false);
    } else if (msg.type === 'error') {
      toast(msg.msg, true);
      updateRunControls(false);
    }
  };
}

setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try { ws.send(JSON.stringify({ type: 'ping' })); } catch (_) {}
  }
}, 20000);

function setConnection(online) {
  const chip = document.getElementById('conn-chip');
  const label = document.getElementById('conn-label');
  const btn = document.getElementById('run-btn');
  chip.className = `chip ${online ? 'online' : 'offline'}`;
  label.textContent = online ? 'Connected' : 'Reconnecting';
  btn.disabled = !online;
}

function updateRunControls(running) {
  const stopBtn = document.getElementById('stop-btn');
  const runBtn = document.getElementById('run-btn');
  stopBtn.style.display = running ? 'inline-flex' : 'none';
  runBtn.disabled = running || !ws || ws.readyState !== WebSocket.OPEN;
}

function renderRoleChips(roles) {
  const grid = document.getElementById('role-grid');
  grid.innerHTML = '';
  for (const r of roles) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `role-chip ${selectedCustomRoles.includes(r.id) ? 'selected' : ''}`;
    btn.title = r.description;
    btn.innerHTML = `${ROLE_ICONS[r.id] || ''}<span>${esc(r.id)}</span>`;
    btn.onclick = () => {
      if (selectedCustomRoles.includes(r.id)) {
        selectedCustomRoles = selectedCustomRoles.filter(x => x !== r.id);
        btn.classList.remove('selected');
      } else {
        selectedCustomRoles.push(r.id);
        btn.classList.add('selected');
      }
    };
    grid.appendChild(btn);
  }
}

document.getElementById('preset-select').addEventListener('change', (e) => {
  document.getElementById('custom-roles-box').style.display = e.target.value === 'custom' ? 'block' : 'none';
});

function setMode(m) {
  modeChoice = m;
  ['auto', 'parallel', 'sequential'].forEach(k => {
    document.getElementById('mode-' + k).classList.toggle('active', k === m);
  });
}

function fillPrompt(text, preset) {
  document.getElementById('prompt-input').value = text;
  document.getElementById('preset-select').value = preset;
  document.getElementById('custom-roles-box').style.display = 'none';
  document.getElementById('prompt-input').focus();
}

function submitMission() {
  const input = document.getElementById('prompt-input');
  const task = input.value.trim();
  if (!task || !ws || ws.readyState !== WebSocket.OPEN) return;
  const preset = document.getElementById('preset-select').value;
  if (preset === 'custom' && selectedCustomRoles.length === 0) {
    toast('Select at least one specialist role for a custom roster.', true);
    return;
  }
  const roles = preset === 'custom' ? [...selectedCustomRoles] : [];
  const mode = modeChoice === 'auto' ? null : modeChoice;
  ws.send(JSON.stringify({ type: 'run', task, preset, roles, mode }));
  input.value = '';
  closeRailMobile();
}

function stopMission() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'stop' }));
  }
}

function submitFollowup(ev) {
  ev.preventDefault();
  const input = document.getElementById('followup-input');
  const prompt = input.value.trim();
  if (!prompt || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'followup', prompt }));
  input.value = '';
}

document.getElementById('prompt-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitMission();
  }
});

function loadRun(run) {
  activeRun = JSON.parse(JSON.stringify(run));
  agentFilter = null;
  previewFile = null;
  if (timerHandle) clearInterval(timerHandle);

  const stage = document.getElementById('stage-scroll');
  stage.innerHTML = `
    <div class="mission-bar">
      <div class="mission-info">
        <div class="mission-title" id="m-goal"></div>
        <div class="mission-sub" id="m-sub"></div>
      </div>
      <div class="top-actions" id="m-actions"></div>
    </div>
    <div class="roster-strip" id="roster-strip"></div>
    <div class="workspace-grid">
      <section class="panel" aria-label="Shared Task Board">
        <div class="panel-head">
          <div class="panel-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="16" y2="14"/><line x1="8" y1="18" x2="12" y2="18"/></svg>
            <span>Shared Task Board</span>
          </div>
          <span class="count-pill" id="tasks-count">0/0</span>
        </div>
        <div class="panel-body" id="tasks-body"></div>
      </section>

      <section class="panel" aria-label="Collaboration Stream">
        <div class="panel-head">
          <div class="tabs" role="tablist">
            <button type="button" class="tab-btn active" id="tab-feed" onclick="switchTab('feed')">Team Feed</button>
            <button type="button" class="tab-btn" id="tab-tools" onclick="switchTab('tools')">Tool Trace <span id="tools-badge">0</span></button>
            <button type="button" class="tab-btn" id="tab-files" onclick="switchTab('files')">Files <span id="files-badge">0</span></button>
          </div>
          <span class="count-pill" id="filter-pill" style="display:none;cursor:pointer" onclick="clearAgentFilter()" title="Clear agent filter"></span>
        </div>
        <div class="panel-body" id="stream-body"></div>
      </section>
    </div>
  `;

  document.getElementById('followup-bar').style.display = 'flex';
  document.getElementById('m-goal').textContent = activeRun.goal || activeRun.task;

  runStartLocal = Date.now() - (activeRun.total_elapsed || 0) * 1000;
  if (!activeRun.done) {
    timerHandle = setInterval(() => {
      const el = document.getElementById('m-timer');
      if (el) el.textContent = ((Date.now() - runStartLocal) / 1000).toFixed(1) + 's';
    }, 200);
  }

  renderHeaderStats();
  renderRoster();
  renderTasks();
  renderStreamBody();
  updateRunControls(!activeRun.done);
}

function renderHeaderStats() {
  if (!activeRun) return;
  const sub = document.getElementById('m-sub');
  const actions = document.getElementById('m-actions');
  if (!sub) return;

  const totalTasks = (activeRun.tasks || []).length;
  const doneTasks = (activeRun.tasks || []).filter(t => t.status === 'completed').length;
  const toolCount = (activeRun.tool_events || []).length;
  const fileCount = (activeRun.files_touched || []).length;
  const st = activeRun.done ? (activeRun.status || 'completed') : (activeRun.status || 'executing');

  sub.innerHTML = `
    <span class="status-pill ${esc(st)}">${esc(st)}</span>
    <span>Squad: <strong style="color:var(--text)">${esc(activeRun.preset)}</strong> (${esc(activeRun.mode)})</span>
    <span>Tasks: <strong style="color:var(--text)">${doneTasks}/${totalTasks}</strong></span>
    <span>Tools: <strong style="color:var(--text)">${toolCount}</strong></span>
    <span>Files: <strong style="color:var(--text)">${fileCount}</strong></span>
    <span id="m-timer" style="font-family:var(--mono);color:var(--text)">${activeRun.total_elapsed || 0}s</span>
  `;

  if (actions) {
    actions.innerHTML = !activeRun.done
      ? `<button type="button" class="btn-danger" onclick="stopMission()">Stop Team</button>`
      : '';
  }

  const tc = document.getElementById('tasks-count');
  if (tc) tc.textContent = `${doneTasks}/${totalTasks}`;
  const tb = document.getElementById('tools-badge');
  if (tb) tb.textContent = String(toolCount);
  const fb = document.getElementById('files-badge');
  if (fb) fb.textContent = String(fileCount);
}

function renderRoster() {
  const strip = document.getElementById('roster-strip');
  if (!strip || !activeRun) return;
  strip.innerHTML = '';
  const orderedIds = Object.keys(activeRun.agents || {});
  orderedIds.sort((a, b) => (a === 'lead' ? -1 : b === 'lead' ? 1 : 0));

  for (const rid of orderedIds) {
    const a = activeRun.agents[rid];
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `agent-tile ${a.state || 'waiting'} ${a.is_lead ? 'is-lead' : ''} ${agentFilter === rid ? 'selected' : ''}`;
    btn.onclick = () => {
      agentFilter = agentFilter === rid ? null : rid;
      const fp = document.getElementById('filter-pill');
      if (fp) {
        fp.style.display = agentFilter ? 'inline-block' : 'none';
        fp.textContent = agentFilter ? `@${agentFilter} ×` : '';
      }
      renderRoster();
      renderStreamBody();
    };

    const actText = a.state === 'tool' && a.current_tool
      ? a.current_tool
      : (a.current_task || (a.is_lead ? 'Coordinating team' : 'Standby'));
    const actClass = a.state === 'tool' ? 'tile-activity tool-call' : 'tile-activity';

    let stHtml = '';
    if (a.state === 'thinking' || a.state === 'tool') {
      stHtml = `<span class="state-tag ${a.state}"><span class="spin"></span>${a.state === 'tool' ? 'running tool' : 'thinking'}</span>`;
    } else {
      stHtml = `<span class="state-tag ${a.state || 'waiting'}"><span class="dot"></span>${esc(a.state || 'waiting')}</span>`;
    }

    btn.innerHTML = `
      <div class="tile-top">
        <div class="tile-id">
          <div class="tile-icon">${ROLE_ICONS[rid] || ROLE_ICONS.coder}</div>
          <span>${esc(a.name || rid)}</span>
        </div>
        <span class="tile-time">${a.elapsed ? a.elapsed + 's' : ''}</span>
      </div>
      <div class="${actClass}" title="${esc(actText)}">${esc(actText)}</div>
      <div class="tile-foot">
        ${stHtml}
        <span>${a.tool_count || 0} tools</span>
      </div>
    `;
    strip.appendChild(btn);
  }
}

function clearAgentFilter() {
  agentFilter = null;
  const fp = document.getElementById('filter-pill');
  if (fp) fp.style.display = 'none';
  renderRoster();
  renderStreamBody();
}

function renderTasks() {
  const body = document.getElementById('tasks-body');
  if (!body || !activeRun) return;
  const tasks = activeRun.tasks || [];
  if (!tasks.length) {
    body.innerHTML = `<div class="history-empty">Team Lead is inspecting the workspace and creating board tasks...</div>`;
    return;
  }
  body.innerHTML = '';
  for (const t of tasks) {
    const row = document.createElement('div');
    row.className = `task-row ${t.status || 'pending'}`;
    const deps = (t.depends_on && t.depends_on.length) ? `<span class="dep-tag">after ${t.depends_on.join(', ')}</span>` : '';
    const resHtml = t.result ? `<div class="task-result">${fmtText(t.result)}</div>` : '';
    row.innerHTML = `
      <div class="task-top">
        <div>
          <span class="task-id-badge">${esc(t.id)}</span>
          <span class="task-title">${esc(t.title)}</span>
        </div>
        <span class="status-pill ${esc(t.status)}">${esc(t.status.replace('_', ' '))}</span>
      </div>
      <div class="task-tags">
        <span class="assignee-tag">@${esc(t.assigned_to)}</span>
        ${deps}
      </div>
      ${resHtml}
    `;
    body.appendChild(row);
  }
}

function switchTab(tab) {
  activeStreamTab = tab;
  ['feed', 'tools', 'files'].forEach(t => {
    const el = document.getElementById('tab-' + t);
    if (el) el.classList.toggle('active', t === tab);
  });
  renderStreamBody();
}

function renderStreamBody() {
  const body = document.getElementById('stream-body');
  if (!body || !activeRun) return;

  if (activeStreamTab === 'feed') {
    let msgs = activeRun.messages || [];
    if (agentFilter) msgs = msgs.filter(m => m.sender === agentFilter || m.recipient === agentFilter);
    if (!msgs.length) {
      body.innerHTML = `<div class="history-empty">No messages yet. Team Lead and specialists will post handoffs and reports here.</div>`;
      return;
    }
    body.innerHTML = '';
    for (const m of msgs) {
      const card = document.createElement('div');
      card.className = 'msg-card';
      const senderClass = m.sender === 'lead' ? 'lead' : (m.sender === 'user' ? 'user' : '');
      card.innerHTML = `
        <div class="msg-head">
          <div class="msg-route">
            <span class="msg-sender ${senderClass}">@${esc(m.sender)}</span>
            <span style="color:var(--text-3)">-></span>
            <span style="color:var(--text-2)">@${esc(m.recipient)}</span>
            <span class="msg-kind">${esc(m.kind)}</span>
          </div>
          <span class="msg-time">${esc(m.timestamp)}</span>
        </div>
        <div class="msg-body">${fmtText(m.content)}</div>
      `;
      body.appendChild(card);
    }
    body.scrollTop = body.scrollHeight;
    return;
  }

  if (activeStreamTab === 'tools') {
    let evs = activeRun.tool_events || [];
    if (agentFilter) evs = evs.filter(e => e.agent_id === agentFilter);
    if (!evs.length) {
      body.innerHTML = `<div class="history-empty">No workspace tool calls executed yet.</div>`;
      return;
    }
    body.innerHTML = '';
    for (const ev of evs) {
      const row = document.createElement('div');
      row.className = 'tool-row';
      const stColor = ev.status === 'done' ? 'var(--success)' : (ev.status === 'error' ? 'var(--danger)' : 'var(--info)');
      row.innerHTML = `
        <div class="tool-head">
          <div class="tool-left">
            <span class="tool-agent">@${esc(ev.agent_id)}</span>
            <span class="tool-fn">${esc(ev.tool_name)}</span>
          </div>
          <span style="font-family:var(--mono);font-size:11px;color:${stColor}">${ev.status === 'running' ? 'running' : `${ev.elapsed}s`}</span>
        </div>
        <div class="tool-args">${esc(ev.args_summary)}</div>
        ${ev.result_preview ? `<div class="tool-res">${esc(ev.result_preview)}</div>` : ''}
      `;
      body.appendChild(row);
    }
    body.scrollTop = body.scrollHeight;
    return;
  }

  if (activeStreamTab === 'files') {
    let files = activeRun.files_touched || [];
    if (agentFilter) files = files.filter(f => f.by === agentFilter);
    if (!files.length) {
      body.innerHTML = `<div class="history-empty">No files created or modified in the workspace yet.</div>`;
      return;
    }
    body.innerHTML = '';
    for (const f of files) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'file-row';
      btn.onclick = () => loadFilePreview(f.path);
      btn.innerHTML = `
        <span class="file-path">${esc(f.path)}</span>
        <span class="file-meta">${esc(f.action)} by @${esc(f.by)} · ${esc(f.timestamp)}</span>
      `;
      body.appendChild(btn);
    }
    if (previewFile) {
      const box = document.createElement('div');
      box.className = 'file-preview-box';
      box.innerHTML = `
        <div class="file-preview-head">
          <span>${esc(previewFile.path)}</span>
          <span style="color:var(--text-3)">${previewFile.size} chars</span>
        </div>
        <pre class="file-preview-code">${esc(previewFile.content)}</pre>
      `;
      body.appendChild(box);
    }
  }
}

async function loadFilePreview(path) {
  try {
    const res = await fetch('/api/file?path=' + encodeURIComponent(path));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Cannot read file' }));
      toast(err.detail || 'Cannot preview file', true);
      return;
    }
    previewFile = await res.json();
    switchTab('files');
  } catch (e) {
    toast('Failed to load file preview', true);
  }
}

function renderHistory() {
  const list = document.getElementById('history-list');
  const countEl = document.getElementById('history-count');
  countEl.textContent = String(historyList.length);
  if (!historyList.length) {
    list.innerHTML = '<div class="history-empty">No missions recorded in this session yet.</div>';
    return;
  }
  list.innerHTML = '';
  for (const run of historyList) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `history-item ${activeRun && activeRun.id === run.id ? 'active' : ''}`;
    btn.onclick = () => { loadRun(run); renderHistory(); closeRailMobile(); };
    btn.innerHTML = `
      <div class="hist-title">${esc(run.goal || run.task)}</div>
      <div class="hist-meta">
        <span>${esc(run.preset)}</span>
        <span>·</span>
        <span>${esc(run.status || (run.done ? 'completed' : 'running'))}</span>
        <span>·</span>
        <span>${run.total_elapsed || 0}s</span>
      </div>
    `;
    list.appendChild(btn);
  }
}

function toggleRail() {
  document.getElementById('rail').classList.toggle('open');
}
function closeRailMobile() {
  document.getElementById('rail').classList.remove('open');
}

function esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmtText(s) {
  return esc(s)
    .replace(/```[\w-]*\n?([\s\S]*?)```/g, '<pre class="code-pre">$1</pre>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}

let toastTimer = null;
function toast(msg, isErr) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show ${isErr ? 'err' : ''}`;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 4000);
}

connectWS();
</script>
</body>
</html>'''
