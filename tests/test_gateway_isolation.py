import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nolthira.core.agent import NolthiraAgent
from nolthira.gateways.base import BaseGateway, GatewayMessage
from nolthira.memory import SQLiteMemory
from nolthira.skills import SkillManager
from nolthira.tools.base import ToolRegistry
from nolthira.team.agent import BUILTIN_ROLES_BY_ID, TeamAgent
from nolthira.team.manager import TeamManager


class CapturingLLM:
    model = "test-model"
    temperature = 0.2
    api_key = ""
    api_base = ""

    def __init__(self):
        self.messages = []

    async def chat_completion(self, messages, tools=None, on_token=None):
        self.messages.append(messages)
        return {"content": "Gateway response.", "tool_calls": None}


class TestGateway(BaseGateway):
    platform_name = "test"

    def is_configured(self):
        return True

    def get_allowed_users(self):
        return []

    def is_authorized(self, user_id, username=""):
        return True

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False

    async def send_text(self, chat_id, text):
        return True


class GatewayMemoryIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_uses_chat_history_but_not_cli_memories_or_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SQLiteMemory(root / "memory.db")
            skills = SkillManager(root / ".skills", extra_dirs=[])
            memory.store_memory(
                key="private_cli_context",
                content="Private fact available only to the interactive CLI.",
                category="preference",
                source="user_explicit",
                confidence=1.0,
            )
            proposal_id = memory.propose_memory(
                key="approved_cli_lesson",
                content="Private learning should remain inside the CLI runtime.",
                category="learning",
                evidence="Verified in CLI only.",
            )
            self.assertTrue(memory.review_memory_proposal(proposal_id, "approve", reviewer="user"))

            llm = CapturingLLM()
            gateway = TestGateway(
                llm_client=llm,
                memory=memory,
                skill_manager=skills,
                registry=ToolRegistry(),
                soul_path=root / "missing-SOUL.md",
            )

            result = await gateway.process_message(GatewayMessage(
                platform="test",
                user_id="user-1",
                chat_id="chat-1",
                text="That's wrong. Please explain the public API.",
            ))

            self.assertEqual(result, "Gateway response.")
            system_prompt = llm.messages[0][0]["content"]
            self.assertNotIn("private_cli_context", system_prompt)
            self.assertNotIn("Private fact available only to the interactive CLI", system_prompt)
            self.assertNotIn("Relevant Approved Learning", system_prompt)
            self.assertNotIn("Private learning should remain inside the CLI runtime", system_prompt)
            self.assertEqual(memory.list_learning_observations("observed"), [])
            history = memory.get_session_history("test_chat-1")
            self.assertTrue(any(item.get("role") == "user" for item in history))


class TeamMemoryIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_team_profile_removes_memory_tools_and_disables_recall(self):
        class FakeBoard:
            id = "board-1"
            goal = "Audit a project"

            async def set_agent_state(self, *args, **kwargs):
                return None

        class FakeAgent:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.build_system_prompt = lambda: "base prompt"

            async def run(self, prompt):
                return "Team task completed."

        manager = TeamManager(
            llm_client=object(),
            memory=object(),
            skill_manager=object(),
            include_persistent_memory=False,
        )
        team_agent = manager._make_agent(BUILTIN_ROLES_BY_ID["planner"], FakeBoard())
        captured = {}

        def fake_build_registry(**kwargs):
            captured["toolsets"] = kwargs["toolsets"]
            return ToolRegistry()

        with patch("nolthira.team.agent.build_team_agent_registry", side_effect=fake_build_registry), patch(
            "nolthira.team.agent.NolthiraAgent", side_effect=lambda **kwargs: FakeAgent(**kwargs)
        ) as agent_constructor:
            result = await team_agent.run("Inspect the project.")

        self.assertEqual(result, "Team task completed.")
        self.assertNotIn("memory", captured["toolsets"])
        self.assertFalse(agent_constructor.call_args.kwargs["include_persistent_memory"])
        self.assertFalse(agent_constructor.call_args.kwargs["enable_learning_capture"])


if __name__ == "__main__":
    unittest.main()
