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
9. **Persistent Memory Across Sessions (SQLite + FTS5)**:
   - Permanent storage for facts, decisions, and preferences.
10. **Autonomous Cron / Background Automation**:
    - Deferred or recurring task scheduling via `schedule_task` (`/cron`).
11. **Dynamic Skills & Continuous Learning**:
    - Learns procedures from `.skills/*.md` and can generate new skills via `create_skill`.

---

## 🛠 Complete Autonomous Toolset (19 Tools)

* **Filesystem & Code**: `read_file`, `write_file`, `patch_file`, `list_dir`, `search_files`
* **Terminal**: `run_command` (guarded shell execution)
* **Vision**: `view_image` (multimodal image & diagram analysis)
* **Web Intelligence**: `web_search`, `web_extract`
* **Persistent Memory**: `store_memory`, `recall_memory`, `list_all_memories`
* **Dynamic Skills**: `list_skills`, `read_skill`, `create_skill`
* **Background Automations**: `schedule_task`, `list_scheduled_tasks`, `cancel_scheduled_task`
* **Multi-Agent Orchestration**: `delegate_task`

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
* `/tools` — Inspect all 19 active autonomous tools
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
