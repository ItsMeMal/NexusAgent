import tempfile
import unittest
from pathlib import Path

from nexus.core.agent import NexusAgent, _redact_learning_text
from nexus.memory import SQLiteMemory
from nexus.skills import SkillManager
from nexus.tools.base import Tool, ToolRegistry


class FakeLLM:
    temperature = 0.7
    api_key = ""
    api_base = ""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_messages = []

    async def chat_completion(self, messages, tools=None, on_token=None):
        self.seen_messages.append(messages)
        if not self.responses:
            raise AssertionError("Unexpected LLM call")
        return self.responses.pop(0)


class LearningGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.memory = SQLiteMemory(root / "memory.db")
        self.skills = SkillManager(root / ".skills", extra_dirs=[])

    def tearDown(self):
        self.tmp.cleanup()

    def test_observations_are_deduplicated_and_not_active_memory(self):
        first = self.memory.record_learning_observation(
            event_type="tool_failure",
            session_id="session-a",
            task_context="Build the project",
            subject="run_command",
            observation="Build failed with missing dependency.",
            evidence="Exit code 1.",
        )
        second = self.memory.record_learning_observation(
            event_type="tool_failure",
            session_id="session-a",
            task_context="Build the project",
            subject="run_command",
            observation="Build failed with missing dependency.",
            evidence="Exit code 1.",
        )

        self.assertEqual(first, second)
        self.assertEqual(len(self.memory.list_learning_observations("observed")), 1)
        self.assertEqual(self.memory.get_all_memories(), [])
        self.assertEqual(self.memory.recall_memories("missing dependency"), [])

    def test_verified_observation_creates_pending_proposal_and_requires_approval(self):
        observation_id = self.memory.record_learning_observation(
            event_type="tool_failure",
            session_id="session-b",
            task_context="Update Prisma schema",
            subject="run_command",
            observation="Prisma validation failed after appending partial schema fragments.",
            evidence="The schema was malformed before generation.",
        )
        proposal_id = self.memory.promote_learning_observation(
            observation_id=observation_id,
            key="prisma_schema_writes",
            lesson="Write Prisma schemas as complete files; validate the schema before generation.",
            verification="Replaced the schema atomically and prisma validate passed.",
            confidence=0.9,
        )

        self.assertIsInstance(proposal_id, int)
        self.assertEqual(
            self.memory.promote_learning_observation(
                observation_id=observation_id,
                key="prisma_schema_writes",
                lesson="Write Prisma schemas as complete files; validate the schema before generation.",
                verification="Re-checked with prisma validate.",
                confidence=0.9,
            ),
            proposal_id,
        )
        self.assertEqual(self.memory.get_all_memories(), [])
        self.assertEqual(self.memory.list_learning_observations("promoted")[0]["proposal_id"], proposal_id)
        pending = self.memory.list_memory_proposals("pending")
        self.assertEqual([item["id"] for item in pending], [proposal_id])
        self.assertIn("prisma validate passed", pending[0]["evidence"])

        self.assertTrue(self.memory.review_memory_proposal(proposal_id, "approve", reviewer="user"))
        self.assertEqual(self.memory.get_all_memories()[0]["category"], "learning")
        self.assertEqual(
            self.memory.recall_relevant_learnings("Prisma schema generation")[0]["key"],
            "prisma_schema_writes",
        )

    def test_unverified_observation_cannot_be_promoted(self):
        observation_id = self.memory.record_learning_observation(
            event_type="user_correction",
            session_id="session-c",
            task_context="Answer a question",
            subject="user_feedback",
            observation="That answer was incorrect.",
        )
        with self.assertRaises(ValueError):
            self.memory.promote_learning_observation(
                observation_id=observation_id,
                key="unverified",
                lesson="Do something differently.",
                verification="",
            )
        self.assertEqual(self.memory.list_learning_observations("observed")[0]["id"], observation_id)
        self.assertEqual(self.memory.get_all_memories(), [])

    def test_dismissed_observation_cannot_be_promoted(self):
        observation_id = self.memory.record_learning_observation(
            event_type="tool_failure",
            session_id="session-d",
            task_context="Run a command",
            subject="run_command",
            observation="Command was blocked by policy.",
        )
        self.assertTrue(self.memory.dismiss_learning_observation(observation_id, "Expected security block."))
        self.assertIsNone(
            self.memory.promote_learning_observation(
                observation_id=observation_id,
                key="not_a_lesson",
                lesson="This should not be promoted.",
                verification="A later test passed.",
            )
        )

    def test_relevant_learning_recall_excludes_pending_and_non_learning_facts(self):
        proposal_id = self.memory.propose_memory(
            key="pending_prisma",
            content="Use complete Prisma schema writes.",
            category="learning",
            evidence="Pending only.",
        )
        self.memory.store_memory(
            key="preferred_database",
            content="Prisma schema",
            category="preference",
            source="user_explicit",
            confidence=1.0,
        )
        self.assertEqual(self.memory.recall_relevant_learnings("Prisma schema"), [])

        self.assertTrue(self.memory.review_memory_proposal(proposal_id, "approve", reviewer="user"))
        hits = self.memory.recall_relevant_learnings("Prisma schema")
        self.assertEqual([item["key"] for item in hits], ["pending_prisma"])

    def test_learning_observation_tools_require_verification_and_allow_review(self):
        from nexus.tools.memory_tools import get_memory_tools

        tools = {tool.name: tool for tool in get_memory_tools(self.memory)}
        self.assertNotIn("review_memory_proposal", tools)
        observation_id = self.memory.record_learning_observation(
            event_type="tool_failure",
            session_id="session-e",
            task_context="Fix a failing build",
            subject="run_command",
            observation="Build failed.",
        )
        missing = tools["record_learning"].handler(
            key="build_recovery",
            lesson="Run the test suite after fixing the dependency.",
            evidence="Build failed.",
            verification="",
        )
        self.assertIn("verification is required", missing)
        listed = tools["list_learning_observations"].handler(status="observed")
        self.assertIn(f"#{observation_id}", listed)
        dismissed = tools["dismiss_learning_observation"].handler(
            observation_id=observation_id,
            reason="Transient failure.",
        )
        self.assertIn("dismissed", dismissed.lower())

    def test_learning_text_redacts_common_credentials(self):
        result = _redact_learning_text(
            "API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456 PASSWORD=hunter2 Bearer abcdefghijklmnop"
        )
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", result)
        self.assertNotIn("hunter2", result)
        self.assertNotIn("Bearer abcdefghijklmnop", result)
        self.assertIn("[REDACTED]", result)


class AgentLearningCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_failures_are_saved_as_observations_not_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SQLiteMemory(root / "memory.db")
            skills = SkillManager(root / ".skills", extra_dirs=[])
            registry = ToolRegistry()
            registry.register(Tool(
                name="simulate_failure",
                description="Return a simulated failure.",
                parameters={"type": "object", "properties": {}},
                handler=lambda: "Error: simulated dependency failure",
            ), toolset="custom")
            llm = FakeLLM([
                {
                    "content": None,
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "simulate_failure", "arguments": "{}"},
                    }],
                },
                {"content": "The failure was recorded for review.", "tool_calls": None},
            ])
            agent = NexusAgent(
                llm_client=llm,
                memory=memory,
                skill_manager=skills,
                registry=registry,
                soul_path=root / "missing-SOUL.md",
                session_id="failure-session",
            )

            result = await agent.run("Diagnose the build failure.")

            self.assertIn("recorded for review", result)
            observations = memory.list_learning_observations("observed")
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["event_type"], "tool_failure")
            self.assertEqual(observations[0]["subject"], "simulate_failure")
            self.assertEqual(memory.get_all_memories(), [])

    async def test_approved_learning_is_injected_into_relevant_future_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SQLiteMemory(root / "memory.db")
            skills = SkillManager(root / ".skills", extra_dirs=[])
            proposal_id = memory.propose_memory(
                key="prisma_schema_rule",
                content="Write the complete Prisma schema atomically, then run prisma validate.",
                category="learning",
                evidence="Verified by a schema validation regression test.",
            )
            self.assertTrue(memory.review_memory_proposal(proposal_id, "approve", reviewer="user"))
            llm = FakeLLM([
                {"content": "I will write the complete schema and validate it.", "tool_calls": None},
            ])
            agent = NexusAgent(
                llm_client=llm,
                memory=memory,
                skill_manager=skills,
                registry=ToolRegistry(),
                soul_path=root / "missing-SOUL.md",
                session_id="learning-recall-session",
            )

            await agent.run("Create a Prisma schema for the new project.")

            system_message = llm.seen_messages[0][0]["content"]
            self.assertIn("Relevant Approved Learning", system_message)
            self.assertIn("Write the complete Prisma schema atomically", system_message)

    async def test_explicit_user_corrections_are_captured_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SQLiteMemory(root / "memory.db")
            skills = SkillManager(root / ".skills", extra_dirs=[])
            agent = NexusAgent(
                llm_client=FakeLLM([
                    {"content": "Acknowledged. I will correct the answer.", "tool_calls": None},
                ]),
                memory=memory,
                skill_manager=skills,
                registry=ToolRegistry(),
                soul_path=root / "missing-SOUL.md",
                session_id="correction-session",
            )

            await agent.run("That's wrong. I already said use PostgreSQL. API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456")

            observations = memory.list_learning_observations("observed")
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["event_type"], "user_correction")
            self.assertIn("PostgreSQL", observations[0]["observation"])
            self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", observations[0]["observation"])
            self.assertEqual(memory.get_all_memories(), [])


if __name__ == "__main__":
    unittest.main()
