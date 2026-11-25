import sys
import os
import json
import uuid
import datetime
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from .llm import LLMClient
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
        on_thought: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_tool_result: Optional[Callable[[str, str, float], None]] = None,
    ):
        self.llm = llm_client
        self.memory = memory
        self.skill_manager = skill_manager
        self.registry = registry
        self.soul_path = soul_path
        self.max_steps = max_steps
        self.session_id = session_id or str(uuid.uuid4())[:8]
        
        # UI Callbacks
        self.on_thought = on_thought
        self.on_token = on_token
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result

        # Ensure session exists in SQLite
        self.memory.create_session(self.session_id, title=f"Session {self.session_id}")

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

## Tool Usage Rules
- For simple greetings, identity questions ("who are you"), banter, or small talk (e.g., "yo", "hello", "lol", "hey"), DO NOT call any tools.
- Only call tools when the user's prompt actually requires action, web search, system execution, or specific memory recall.
- When you execute a tool, inspect its result carefully before taking your next step.
- If you solve a reusable workflow or discover a useful repeatable procedure, use `create_skill` to save it!
"""
        return system_prompt.strip()

    async def run(self, user_prompt: str) -> str:
        """Run the autonomous ReAct cycle for the given user prompt."""
        # 1. Load existing session history
        history = self.memory.get_session_history(self.session_id)
        
        # 2. Append new user message
        self.memory.save_message(session_id=self.session_id, role="user", content=user_prompt)
        history.append({"role": "user", "content": user_prompt})

        # 3. Assemble full messages payload with fresh system prompt
        system_prompt = self.build_system_prompt()
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}] + history
        tools_schema = self.registry.to_openai_schemas()

        final_response_text = ""
        recent_call_signatures: List[str] = []

        # 4. Autonomous ReAct loop
        for step in range(self.max_steps):
            try:
                # Provide on_token for real-time live streaming
                response_msg = await self.llm.chat_completion(
                    messages=messages,
                    tools=tools_schema if tools_schema else None,
                    on_token=self.on_token
                )
            except Exception as e:
                err_text = f"Agent Error during LLM completion: {str(e)}"
                if self.on_thought:
                    self.on_thought(err_text)
                return err_text

            content = response_msg.get("content")
            tool_calls = response_msg.get("tool_calls")

            # Save assistant message to memory and context
            self.memory.save_message(
                session_id=self.session_id,
                role="assistant",
                content=content,
                tool_calls=tool_calls
            )
            messages.append(response_msg)

            if content:
                final_response_text = content
                # If non-streaming was used and on_thought is provided
                if self.on_thought and not self.on_token and not tool_calls:
                    self.on_thought(content)

            # If no tool calls, task is finished!
            if not tool_calls:
                break

            # Process each tool call
            for tc in tool_calls:
                tc_id = tc.get("id", str(uuid.uuid4()))
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
                else:
                    # Execute tool via registry with timing measurement
                    start_t = time.perf_counter()
                    result = await self.registry.execute_tool(tool_name, args)
                    elapsed = time.perf_counter() - start_t

                if self.on_tool_result:
                    self.on_tool_result(tool_name, result, elapsed)

                # Append tool result to conversation history
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result
                }
                self.memory.save_message(
                    session_id=self.session_id,
                    role="tool",
                    content=result,
                    tool_call_id=tc_id
                )
                messages.append(tool_msg)

        return final_response_text
