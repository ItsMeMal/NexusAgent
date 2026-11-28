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
* **Terminal**: `run_command` (guarded foreground/background execution), `process` (list/poll/log/wait/kill/write tracked background sessions)
* **Vision**: `view_image` (multimodal image & diagram analysis)
* **Web Intelligence**: `web_search`, `web_extract`
* **Workspace Checkpoints & Recovery**: `create_checkpoint`, `list_checkpoints`, `inspect_checkpoint`, `restore_checkpoint` (safe overlay by default; exact rollback requires explicit confirmation)
* **Governed Memory**: `store_memory`, `propose_memory`, `record_learning`, `recall_memory`, `list_all_memories`, `list_memory_proposals`, `review_memory_proposal`, `archive_memory`, `restore_memory`, `delete_memory`, `memory_history`, `session_search`
* **Managed Skills**: `list_skills`, `read_skill`, `create_skill`, `update_skill`, `delete_skill`, `validate_skill`
* **Background Automations**: `schedule_task`, `list_scheduled_tasks`, `cancel_scheduled_task`
* **Session Task Planning**: `todo` (session-scoped add, update, complete, remove, and list)
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

## 🔌 Provider Catalog

Nexus includes built-in profiles for hosted inference providers and local runtimes. The provider picker (`/provider`) now includes these additional OpenAI Chat Completions-compatible endpoints:

| Provider | Default base URL | Credential variable |
|---|---|---|
| Cerebras | `https://api.cerebras.ai/v1` | `CEREBRAS_API_KEY` |
| SambaNova Cloud | `https://api.sambanova.ai/v1` | `SAMBANOVA_API_KEY` |
| DeepInfra | `https://api.deepinfra.com/v1/openai` | `DEEPINFRA_API_KEY` |
| SiliconFlow | `https://api.siliconflow.com/v1` | `SILICONFLOW_API_KEY` |
| Novita AI | `https://api.novita.ai/v3/openai` | `NOVITA_API_KEY` |
| Nebius Token Factory | `https://api.tokenfactory.nebius.com/v1` | `NEBIUS_API_KEY` |
| Hyperbolic | `https://api.hyperbolic.ai/inference/v1` | `HYPERBOLIC_API_KEY` |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |
| Moonshot AI (Kimi) | `https://api.moonshot.ai/v1` | `MOONSHOT_API_KEY` |
| Alibaba Cloud Model Studio | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` |
| Z.ai (GLM) | `https://api.z.ai/api/paas/v4` | `ZAI_API_KEY` |
| MiniMax | `https://api.minimax.io/v1` | `MINIMAX_API_KEY` |
| BytePlus ModelArk | `https://ark.ap-southeast.bytepluses.com/api/v3` | `ARK_API_KEY` |
| Hugging Face Inference Providers | `https://router.huggingface.co/v1` | `HF_TOKEN` |
| Amazon Bedrock Mantle | `https://bedrock-mantle.us-east-1.api.aws/v1` | `AWS_BEDROCK_API_KEY` |

The catalog discovers models from the selected provider's `/models` endpoint where available; it does not depend on a stale hard-coded model list. When connecting a provider, Nexus saves its provider-specific credential and also updates the active `OPENAI_API_KEY` / `OPENAI_API_BASE` values used by the current runtime. Existing provider-specific credentials are preferred when reconnecting.

For regional services, the provider wizard lets you override the default base URL. This is important for Bedrock (the default profile is us-east-1) and Alibaba Model Studio (the default is the Singapore DashScope endpoint); use an endpoint and API key from the same region. Hugging Face model IDs may include a provider suffix such as `:novita` or a routing suffix such as `:fastest`.

**Compatibility note:** these new profiles use the OpenAI Chat Completions request format consumed by the current `LLMClient`. This does not imply that every model supports tool calling, vision, or streaming. Those capabilities and model availability must be verified for the selected model. Native adapters for Azure AI Foundry and Google Vertex AI are not included yet because they require authentication flows beyond the current Bearer-token client.

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
* `/memory` — Inspect approved persistent facts and evidence-backed learning
* `/memory proposals` — Review pending memory/learning proposals
* `/memory observations` — Inspect captured tool failures and explicit corrections
* `/memory review <id> approve|reject` — Explicitly approve or reject a proposal
* `/memory dismiss <id> [reason]` — Dismiss an observation without promoting it
* `/todo` — View the session task plan (`/todo add|start|block|complete|update|remove`)
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

### Evidence-Based Self-Improving Learning Loop

Nexus separates raw observations from durable memory:

1. Clear user corrections and tool failures are captured as bounded, deduplicated observations. Common credential patterns are redacted before observations are stored.
2. Observations remain diagnostic records. They do not enter long-term memory or change future behavior.
3. Nexus may promote an observation only after identifying a reusable root cause and supplying a concrete verification result. This creates a pending learning proposal.
4. The operator reviews proposals with `/memory proposals`, then explicitly approves or rejects one with `/memory review <id> approve|reject`. The model cannot approve its own proposals.
5. Only approved learning entries are retrieved by relevance and injected into later task contexts. They remain guidance to verify, not instructions that override the current user or security policy.

Use `/memory observations` to inspect captured failures/corrections and `/memory dismiss <id> [reason]` to discard transient noise. Pending proposals and dismissed observations never influence future task prompts.
