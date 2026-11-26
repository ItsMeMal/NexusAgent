import sys
import os
import json
import uuid
import inspect
import asyncio
import datetime
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from .llm import LLMClient, sanitize_messages
from .modes import get_mode, AgentMode
from ..memory import SQLiteMemory
from ..skills import SkillManager
from ..tools.base import ToolRegistry
from ..config import config

class NexusAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        memory: SQLiteMemory,
        skill_manager: SkillManager,
        registry: ToolRegistry,
        soul_path: Path = config.SOUL_PATH,
        max_steps: int = config.MAX_STEPS,
        session_id: Optional[str] = None,
        mode: Optional[str] = None,
        on_thought: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_tool_result: Optional[Callable[[str, str, float], None]] = None,
        on_retry: Optional[Callable[[int, int, str], None]] = None,
    ):
        self.llm = llm_client
        self.memory = memory
        self.skill_manager = skill_manager
        self.registry = registry
        self.soul_path = soul_path
        self.max_steps = max_steps
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.mode: str = get_mode(mode or getattr(config, "AGENT_MODE", "auto")).id
        
        # UI Callbacks
        self.on_thought = on_thought
        self.on_token = on_token
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_retry = on_retry

        # Ensure session exists in SQLite
        self.memory.create_session(self.session_id, title=f"Session {self.session_id}")

    def set_mode(self, mode_id: str) -> AgentMode:
        """Switch operating mode cleanly."""
        spec = get_mode(mode_id)
        self.mode = spec.id
        return spec

    def build_system_prompt(self) -> str:
        soul_content = ""
        if self.soul_path.exists():
            soul_content = self.soul_path.read_text(encoding="utf-8")
        else:
            soul_content = "You are Nexus Agent, an autonomous multi-agent AI orchestrator."

        skills_summary = self.skill_manager.get_skills_summary()
        
        # Recent persistent memories
        recent_memories = self.memory.get_all_memories(limit=8)
        memories_text = ""
        if recent_memories:
            memories_text = "### Known Persistent Memories / User Facts:\n" + "\n".join(
                f"- [{m.get('category')}] {m.get('key')}: {m.get('content')}" for m in recent_memories
            )

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cwd_str = str(config.ROOT_DIR)

        system_prompt = f"""{soul_content}

## Runtime Environment
- Current Local Time: {now_str}
- Working Directory: {cwd_str}
- Operating System: {sys.platform}

## Learned Skills (.skills)
{skills_summary}

{memories_text}

## Conversational, Identity & Language Rules
- Your identity is strictly **Nexus Agent**, the Universal Autonomous Orchestrator created by **Mallss** (`ItsMeMal`).
- NEVER reveal, claim, or leak any underlying LLM vendor/model identity (do NOT say "I am Gemini/Claude/GPT/Agnes" or "developed by Google/OpenAI/etc."). When asked who or what you are or who made you, answer in character as Nexus Agent created by Mallss.
- **DEFAULT LANGUAGE IS ENGLISH.** Always match the exact language of the user's **LATEST** message. If the user writes in English (e.g., "who are you", "hello", "test"), you MUST respond in English—never carry over Indonesian from prior turns or memory entries.
- You are a UNIVERSAL Autonomous Orchestrator (not just a coding bot). You handle research, planning, writing, automation, workflows, analysis, and general problem solving.
- NEVER assume the user's complaints or venting (e.g., "exhausted", "bored", "frustrated") are about code or bugs! Treat them naturally across any life or work context.
- NEVER act like an annoying customer service bot or waiter.
- NEVER end messages with work menus or task offerings (e.g., NEVER ask: "What would you like to work on?", "How can I assist you today?", "Want to code or just chat?").
- When the user jokes, drops memes, or chats casually, match their vibe and stop naturally like a sharp human peer.

## Tool & Skill Usage Rules
- **MANDATORY SKILL-FIRST PROTOCOL**: Whenever the user's request involves a real task (coding, UI/frontend, design, architecture, debugging, data analysis, DevOps, security, writing, automation, video/typography, etc.), you **MUST** check the `## Learned Skills (.skills)` catalog above first!
  - Call `read_skill(skill_name)` on the **1–2 most relevant skills** BEFORE planning, writing files, or executing other tools, and **strictly apply** their instructions and standards. (Avoid loading 4+ large skills at once to keep context lean.)
  - Only skip `read_skill` for casual greetings/banter or when no listed skill is relevant.
- **DECISIVE ACTION RULE**: When the user asks to build/make/create something — even phrased casually like *"bisa buat website X?"*, *"can you make X?"*, *"bebas"*, or *"use your skills"* — treat it as an execution order (unless in `PLAN` or `ASK` mode). Do NOT ask questionnaires ("what tech stack? what vibe? ready to proceed?"): inspect the workspace briefly, pick strong modern defaults informed by your skills, execute with `write_file`/`patch_file`/`run_command`, and deliver working results!
- For simple greetings, identity questions ("who are you"), banter, or small talk (e.g., "yo", "hello", "lol", "hey"), DO NOT call any tools.
- Only call tools when the user's prompt actually requires action, web search, system execution, or specific memory recall.
- When you execute a tool, inspect its result carefully before taking your next step.
- If you solve a reusable workflow or discover a useful repeatable procedure, use `create_skill` to save it!
"""
        mode_spec = get_mode(self.mode)
        if mode_spec.system_directive:
            system_prompt += "\n" + mode_spec.system_directive + "\n"
        return system_prompt.strip()

    def _heal_history(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Repair poisoned history (dangling tool_calls or missing/null content) before sending to LLM."""
        healed: List[Dict[str, Any]] = []
        answered_ids = {
            m.get("tool_call_id") for m in history if m.get("role") == "tool" and m.get("tool_call_id")
        }
        for msg in history:
            healed.append(msg)
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tid = tc.get("id")
                    if tid and tid not in answered_ids:
                        repair_msg = {
                            "role": "tool",
                            "tool_call_id": tid,
                            "content": "[Recovered from aborted previous turn]",
                        }
                        healed.append(repair_msg)
                        answered_ids.add(tid)
                        try:
                            self.memory.save_message(
                                session_id=self.session_id,
                                role="tool",
                                content=repair_msg["content"],
                                tool_call_id=tid,
                            )
                        except Exception:
                            pass
        return sanitize_messages(healed)

    async def _call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        on_token: Optional[Callable[[str], None]],
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "on_token": on_token,
        }
        try:
            sig = inspect.signature(self.llm.chat_completion)
            if "on_retry" in sig.parameters and self.on_retry is not None:
                kwargs["on_retry"] = self.on_retry
        except Exception:
            pass
        return await self.llm.chat_completion(**kwargs)

    async def run(self, user_prompt: str) -> str:
        """Run the autonomous ReAct cycle for the given user prompt."""
        mode_spec = get_mode(self.mode)
        effective_max_steps = max(self.max_steps, mode_spec.max_steps_floor)
        if mode_spec.max_steps_cap is not None:
            effective_max_steps = min(effective_max_steps, mode_spec.max_steps_cap)

        # 1. Load & heal existing session history
        history = self._heal_history(self.memory.get_session_history(self.session_id))
        
        # 2. Append new user message
        self.memory.save_message(session_id=self.session_id, role="user", content=user_prompt)
        history.append({"role": "user", "content": user_prompt})

        # 3. Assemble full messages payload with fresh system prompt
        system_prompt = self.build_system_prompt()

        # Lightweight skill auto-detection hint injected cleanly into system prompt (zero SQLite pollution)
        if self.registry.get("read_skill") is not None and hasattr(self.skill_manager, "match_skills"):
            matched_skills = self.skill_manager.match_skills(user_prompt, top_k=3)
            if matched_skills:
                skill_list = ", ".join(f"`{s.name}`" for s in matched_skills)
                system_prompt += (
                    f"\n\n## Active Task Skill Match\n"
                    f"Relevant skill(s) detected for the user's request: {skill_list}.\n"
                    f"You MUST call `read_skill` on the top 1-2 applicable skill(s) FIRST before planning, coding, or executing other tools."
                )

        messages: List[Dict[str, Any]] = sanitize_messages([{"role": "system", "content": system_prompt}] + history)
        all_schemas = self.registry.to_openai_schemas()
        if mode_spec.blocked_tools:
            tools_schema = [
                s for s in all_schemas
                if s.get("function", {}).get("name") not in mode_spec.blocked_tools
            ]
        else:
            tools_schema = all_schemas

        final_response_text = ""
        recent_call_signatures: List[str] = []
        pending_tc_ids: List[str] = []

        # Temporarily enforce mode temperature cap if applicable
        has_temp = hasattr(self.llm, "temperature")
        orig_temp = getattr(self.llm, "temperature", None)
        if has_temp and mode_spec.max_temperature is not None and isinstance(orig_temp, (int, float)):
            self.llm.temperature = min(orig_temp, mode_spec.max_temperature)

        # 4. Autonomous ReAct loop
        try:
            for step in range(effective_max_steps):
                try:
                    response_msg = await self._call_llm(
                        messages=messages,
                        tools=tools_schema if tools_schema else None,
                        on_token=self.on_token,
                    )
                except Exception as e:
                    err_text = f"Agent Error during LLM completion: {str(e)}"
                    if self.on_thought:
                        self.on_thought(err_text)
                    return err_text

                content = response_msg.get("content")
                tool_calls = response_msg.get("tool_calls")

                # Ensure every tool_call has a stable ID before saving assistant turn
                if tool_calls:
                    for tc in tool_calls:
                        if not tc.get("id"):
                            tc["id"] = str(uuid.uuid4())
                    pending_tc_ids = [tc["id"] for tc in tool_calls]

                safe_content = content if (content is not None and str(content).strip()) else (
                    "[calling tools]" if tool_calls else ""
                )
                normalized_msg = dict(response_msg)
                normalized_msg["content"] = safe_content

                # Save assistant message to memory and context
                self.memory.save_message(
                    session_id=self.session_id,
                    role="assistant",
                    content=safe_content,
                    tool_calls=tool_calls,
                )
                messages.append(normalized_msg)

                if content and str(content).strip() and content != "[calling tools]":
                    final_response_text = content
                    if self.on_thought and not self.on_token and not tool_calls:
                        self.on_thought(content)

                # If no tool calls, task is finished!
                if not tool_calls:
                    break

                # Process each tool call
                for tc in tool_calls:
                    tc_id = tc["id"]
                    function_info = tc.get("function", {})
                    tool_name = function_info.get("name")
                    raw_args = function_info.get("arguments", "{}")

                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}

                    if self.on_tool_call:
                        self.on_tool_call(tool_name, args)

                    # Generate signature for duplicate loop detection
                    sig = f"{tool_name}:{json.dumps(args, sort_keys=True) if isinstance(args, dict) else str(args)}"
                    same_call_count = recent_call_signatures.count(sig)
                    recent_call_signatures.append(sig)

                    if same_call_count >= 2:
                        # Halt loop locally to avoid spinning and prevent upstream StalledToolLoopDetected
                        result = (
                            f"[System Loop Guard]: You have called '{tool_name}' multiple times with identical arguments. "
                            "Stop repeating this call. Synthesize your final answer for the user using the information already retrieved."
                        )
                        elapsed = 0.001
                    elif tool_name in mode_spec.blocked_tools:
                        result = (
                            f"[Mode Guard ({mode_spec.label})]: Tool '{tool_name}' is disabled in {mode_spec.label} mode "
                            f"({mode_spec.short_desc}). Complete your response without mutating workspace files or switch mode."
                        )
                        elapsed = 0.001
                    else:
                        # Execute tool via registry with timing measurement
                        start_t = time.perf_counter()
                        result = await self.registry.execute_tool(tool_name, args)
                        elapsed = time.perf_counter() - start_t

                    if self.on_tool_result:
                        self.on_tool_result(tool_name, result, elapsed)

                    safe_result = result if (result is not None and str(result).strip()) else "(empty tool output)"
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": safe_result,
                    }
                    self.memory.save_message(
                        session_id=self.session_id,
                        role="tool",
                        content=safe_result,
                        tool_call_id=tc_id,
                    )
                    if tc_id in pending_tc_ids:
                        pending_tc_ids.remove(tc_id)
                    messages.append(tool_msg)

            # Guarantee user never receives a silent blank output after tools/empty LLM turn
            if not (final_response_text or "").strip():
                try:
                    synth_payload = sanitize_messages(
                        messages + [{
                            "role": "user",
                            "content": "Provide your clear final response or execute summary directly now (do not call tools or return empty text).",
                        }],
                        force_non_empty=True,
                    )
                    synth_resp = await self._call_llm(
                        messages=synth_payload,
                        tools=None,
                        on_token=self.on_token,
                    )
                    synth_text = (synth_resp.get("content") or "").strip()
                    if synth_text:
                        final_response_text = synth_text
                        self.memory.save_message(
                            session_id=self.session_id,
                            role="assistant",
                            content=synth_text,
                        )
                        if self.on_thought and not self.on_token:
                            self.on_thought(synth_text)
                except Exception:
                    pass
        except asyncio.CancelledError:
            # Close out any unanswered tool calls so SQLite history remains schema-valid
            for pid in pending_tc_ids:
                try:
                    self.memory.save_message(
                        session_id=self.session_id,
                        role="tool",
                        content="[Interrupted by user]",
                        tool_call_id=pid
                    )
                except Exception:
                    pass
            raise
        finally:
            if has_temp and orig_temp is not None:
                self.llm.temperature = orig_temp

        return final_response_text
