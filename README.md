# ⚡ Nexus Agent Orchestrator (v1)

An autonomous, persistent, universal, and self-improving AI Agent Orchestrator built to plan, execute, research, and solve complex workflows across any domain.

---

## 🌟 Key Nexus Orchestrator Pillars

1. **Universal Autonomous Orchestrator (Multi-Domain)**:
   - Not restricted to coding. Nexus is a general-purpose orchestrator for research, automation, web intelligence, visual analysis, business strategy, technical writing, and problem-solving.
2. **Multi-Agent Orchestration (`delegate_task`)**:
   - Decomposes large objectives across scoped subagents (researcher, analyst, executor) with isolated context windows.
3. **Multimodal Vision (`view_image`)**:
   - Inspects and analyzes local screenshots, architecture diagrams, flow charts, visual errors, UI mockups, and image documents.
4. **Information Gathering & Live Web Intelligence**:
   - `web_search`: Live search for up-to-date documentation and web knowledge.
   - `web_extract`: Clean text extraction from web URLs in real-time.
   - `search_files`: Instant fast grep across the codebase.
   - `recall_memory`: Keyword and semantic recall from persistent SQLite FTS5 memory.
5. **Interactive Session Resuming (`/resume`)**:
   - Interactive arrow-key session browser to restore and continue past conversation sessions.
6. **Model Context Protocol (MCP)**:
   - Full support for industry-standard MCP servers via `.mcp.json` / `mcp_servers.json` (`/mcp`).
7. **Modular Plugins (`plugins/`)**:
   - Extensible `plugins/` directory (`/plugins`) to load dynamic custom tools and agent behaviors.
8. **Security & Anti-Jailbreak Guardrails (`/security`)**:
   - Destructive command interceptor (`rm -rf`, disk wipes, fork bombs), system path sandboxing (`C:\Windows`, `/etc`), credential protection (`.env`, SSH keys), and prompt injection resistance.
9. **Governed Persistent Memory (SQLite + FTS5)**:
   - Cross-session storage with provenance, confidence, and supporting evidence.
   - Inferred facts and reusable lessons enter a review queue; pending proposals never affect normal recall.
   - Approval/rejection, archive/restore, revision history, and permanent deletion controls.
10. **Autonomous Cron / Background Automation**:
    - Deferred or recurring task scheduling via `schedule_task` (`/cron`).
11. **Managed Skills & Reviewable Learning**:
    - Discovers skills from local, shared, plugin, and bundled sources with source precedence.
    - Creates, updates, deletes, and structurally validates Nexus-owned skills; external/bundled skills remain read-only.
    - Stores corrections and verified lessons as reviewable memory proposals instead of silently promoting guesses.

---

## 🛠 Core Autonomous Toolsets

* **Computer Use & GUI Automation**: `computer` (desktop screenshots with vision analysis, mouse click/move/drag, typing, hotkeys, scrolling, app launch)
* **Filesystem & Code**: `read_file`, `write_file`, `patch_file`, `list_dir`, `search_files`
* **Terminal**: `run_command` (guarded shell execution)
* **Vision**: `view_image` (multimodal image & diagram analysis)
* **Web Intelligence**: `web_search`, `web_extract`
* **Workspace Checkpoints & Recovery**: `create_checkpoint`, `list_checkpoints`, `inspect_checkpoint`, `restore_checkpoint` (safe overlay by default; exact rollback requires explicit confirmation)
* **Governed Memory**: `store_memory`, `propose_memory`, `record_learning`, `recall_memory`, `list_all_memories`, `list_memory_proposals`, `review_memory_proposal`, `archive_memory`, `restore_memory`, `delete_memory`, `memory_history`, `session_search`
* **Managed Skills**: `list_skills`, `read_skill`, `create_skill`, `update_skill`, `delete_skill`, `validate_skill`
* **Background Automations**: `schedule_task`, `list_scheduled_tasks`, `cancel_scheduled_task`
* **Multi-Agent Orchestration**: `delegate_task`

---

## ⚡ Quick One-Line Installation

Install Nexus globally into your home directory (`~/.nexus`):

### Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/ItsMeMal/NexusAgent/main/install.ps1 | iex
```

### Linux & macOS (curl)
```bash
curl -fsSL https://raw.githubusercontent.com/ItsMeMal/NexusAgent/main/install.sh | bash
```

> **Home Directory Layout:**
> - **Windows:** `C:\Users\<username>\.nexus\`
> - **Linux:** `/home/<username>/.nexus/` (or `/root/.nexus/`)
> - **macOS:** `/Users/<username>/.nexus/`

---

## 🚀 Quick Usage

### 1. Launch Directly from Any Terminal
Open PowerShell or Command Prompt in any project folder:
```bash
nexus
```
*(or type `nexuss`)*

### 2. Single-Shot Prompt Execution
```bash
nexus -p "Research the latest cybersecurity vulnerability reports and summarize key takeaways"
```

### 3. API Configuration (`.env`)
```env
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_API_KEY=your_api_key_here
NEXUS_MODEL=anthropic/claude-3.5-sonnet
NEXUS_TEMPERATURE=0.7
```

---

## ⌨️ Command Palette (Slash Commands)

Type `/` in the prompt for real-time autocomplete:

* `/models` or `/model` — Select active model via interactive arrow-key selector (`↑`/`↓`)
* `/provider` or `/connect` — Switch or connect AI router via interactive menu
* `/resume` — Browse and resume past conversation sessions (`↑`/`↓`)
* `/computer` — Inspect GUI automation status, screen resolution, or capture screenshot (`/computer screenshot`)
* `/tools` — Inspect currently registered autonomous tools
* `/status` — View agent system diagnostics and active telemetry
* `/mcp` — Inspect connected Model Context Protocol (MCP) servers
* `/plugins` — View loaded modular plugins from `plugins/`
* `/security` — View security guardrails, command sandbox, and safety policy
* `/skills` — View learned procedures and dynamic skills
* `/memory` — Inspect persistent facts stored in SQLite FTS5
* `/cron` — View scheduled background jobs and automations
* `/sessions` — List past conversation sessions stored in SQLite
* `/new` — Start a fresh, clean context session
* `/clear` — Clear terminal screen and show banner
* `/help` — Display command palette
* `exit` or `quit` — Exit Nexus Agent CLI and persist session state

---
## 🧰 Configurable Toolsets & Subagent Runtime

Nexus stores toolset policy in `~/.nexus/toolsets.json`. The file is created atomically when a setting is changed. Profiles are applied to the live tool registry; disabled tools are unavailable to the model and are also rejected if called by name or alias.

Built-in profiles:

- `default` — all built-in capability groups and registered extensions.
- `researcher` — read-oriented workspace, memory, skill, and web access; terminal execution, file mutation, memory writes, plugins, MCP, and other extension tools are blocked.
- `analyst` — researcher profile with browser and vision capabilities enabled.
- `coder` — file editing, project inspection, checkpoints, terminal, and development tools.

CLI management:

```text
/toolsets
/toolsets use coder
/toolsets enable browser
/toolsets disable computer
/toolsets platform telegram researcher
/toolsets role debugger coder
```

Platform profiles are independently selectable for Telegram, Discord, WhatsApp, Slack, and Email. Changing a platform profile requires restarting that gateway to rebuild its isolated registry. Subagent role mappings take effect on the next delegation.

The subagent runtime supports role-scoped permissions, bounded execution time, step limits, and a global concurrency cap. Default limits are 3 concurrent workers, 600 seconds per worker, and 20 reasoning steps. These are configurable under the `limits` object in `toolsets.json`.

Use `delegate_task` for a single focused worker. Use `delegate_tasks` for 2–8 independent workstreams that can safely run concurrently. Do not delegate overlapping file edits or tasks that depend on one another in the same batch. Explicitly requested toolsets can narrow a role's access, but cannot widen it.
