"""
nexus/team/agent.py
TeamAgent — a single specialized sub-agent in an AI-Team.

Each TeamAgent has:
  - A role (name + system prompt persona)
  - Its own isolated LLM session + memory context
  - An async run(task) method that returns a result string
  - Lightweight: reuses the same LLMClient, no extra process
"""

from __future__ import annotations

import uuid
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class AgentRole:
    """Definition of a specialized team member role."""
    id: str                   # unique slug e.g. "coder", "reviewer", "tester"
    name: str                 # display name e.g. "Code Writer"
    emoji: str                # e.g. "💻"
    system_prompt: str        # injected persona/instructions
    description: str = ""     # one-liner shown in /team list


# ------------------------------------------------------------------
# Built-in roles
# ------------------------------------------------------------------

BUILTIN_ROLES: List[AgentRole] = [
    AgentRole(
        id="planner",
        name="Planner",
        emoji="🗺️",
        description="Breaks down complex tasks into actionable steps",
        system_prompt=(
            "You are the Planner agent in a collaborative AI-Team. "
            "Your job is to analyze the given task and produce a clear, ordered, numbered plan. "
            "Be concise, precise, and actionable. Output ONLY the plan — no preamble."
        ),
    ),
    AgentRole(
        id="coder",
        name="Code Writer",
        emoji="💻",
        description="Writes clean, production-ready code",
        system_prompt=(
            "You are the Code Writer agent in a collaborative AI-Team. "
            "You receive a task or plan step and write clean, production-ready code. "
            "Include docstrings, type hints, and brief inline comments. "
            "Output ONLY the code and a short explanation — no fluff."
        ),
    ),
    AgentRole(
        id="reviewer",
        name="Code Reviewer",
        emoji="🔍",
        description="Reviews code for bugs, security, and best practices",
        system_prompt=(
            "You are the Code Reviewer agent in a collaborative AI-Team. "
            "Review the provided code or output for bugs, security issues, performance, "
            "and style. List findings as numbered issues with severity (Critical/High/Medium/Low). "
            "If nothing to report, say 'LGTM ✅' with a brief summary."
        ),
    ),
    AgentRole(
        id="tester",
        name="QA Tester",
        emoji="🧪",
        description="Writes tests and identifies edge cases",
        system_prompt=(
            "You are the QA Tester agent in a collaborative AI-Team. "
            "Your job is to write pytest test cases for the given code, "
            "covering happy path, edge cases, and error conditions. "
            "Output ONLY the test code with brief comments explaining each test."
        ),
    ),
    AgentRole(
        id="writer",
        name="Technical Writer",
        emoji="📝",
        description="Writes clear documentation and READMEs",
        system_prompt=(
            "You are the Technical Writer agent in a collaborative AI-Team. "
            "Write clear, well-structured documentation (README, docstrings, or API docs) "
            "for the given code or feature. Use markdown. Be thorough but concise."
        ),
    ),
    AgentRole(
        id="analyst",
        name="Data Analyst",
        emoji="📊",
        description="Analyzes data, finds patterns, suggests insights",
        system_prompt=(
            "You are the Data Analyst agent in a collaborative AI-Team. "
            "Analyze the provided data or problem. Find patterns, anomalies, and key insights. "
            "Present findings in a structured format with bullet points and summaries."
        ),
    ),
    AgentRole(
        id="devops",
        name="DevOps Engineer",
        emoji="⚙️",
        description="Handles CI/CD, Docker, deployment, infrastructure",
        system_prompt=(
            "You are the DevOps Engineer agent in a collaborative AI-Team. "
            "Handle deployment, CI/CD pipelines, Docker, infrastructure-as-code, "
            "and system configuration for the given task. "
            "Output scripts, configs, and brief explanations."
        ),
    ),
    AgentRole(
        id="security",
        name="Security Auditor",
        emoji="🛡️",
        description="Audits for vulnerabilities and security risks",
        system_prompt=(
            "You are the Security Auditor agent in a collaborative AI-Team. "
            "Audit the given code or system design for security vulnerabilities. "
            "Reference OWASP Top 10 where relevant. List findings with severity and remediation."
        ),
    ),
]

BUILTIN_ROLES_BY_ID = {r.id: r for r in BUILTIN_ROLES}


# ------------------------------------------------------------------
# TeamAgent
# ------------------------------------------------------------------

class TeamAgent:
    """
    A single stateless AI sub-agent that runs a task with a specialized role.

    Uses the shared LLMClient for inference — no separate process or memory.
    Each run() call is independent (stateless per call).
    """

    def __init__(self, role: AgentRole, llm_client) -> None:
        self.role = role
        self.llm = llm_client
        self.agent_id = f"{role.id}-{uuid.uuid4().hex[:6]}"
        self.total_runs: int = 0
        self.last_result: Optional[str] = None

    async def run(self, task: str, context: str = "") -> str:
        """
        Execute a task as this agent's specialized role.
        Returns the agent's response string.
        """
        self.total_runs += 1
        messages = [
            {"role": "system", "content": self.role.system_prompt},
        ]
        if context:
            messages.append({
                "role": "user",
                "content": f"Context from previous agents:\n{context}\n\n---\nYour task:\n{task}"
            })
        else:
            messages.append({"role": "user", "content": task})

        try:
            response = await self.llm.chat_completion(messages)
            # chat_completion returns a raw API dict: choices[0].message.content
            result = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                or ""
            )
            if not result:
                result = "⚠️ Agent returned empty response."
            self.last_result = result
            logger.info("[Team:%s] Completed task (%d chars)", self.role.id, len(result))
            return result
        except Exception as exc:
            error = f"❌ {self.role.name} failed: {exc}"
            self.last_result = error
            logger.error("[Team:%s] Error: %s", self.role.id, exc)
            return error

    def __repr__(self) -> str:
        return f"<TeamAgent role={self.role.id} runs={self.total_runs}>"
