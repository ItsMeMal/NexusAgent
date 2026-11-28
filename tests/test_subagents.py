import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.orchestrator.subagent import SubagentManager
from nexus.toolsets import ToolsetManager


class FakeLLM:
    api_key = ""
    api_base = ""


class SubagentPermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.toolsets = ToolsetManager(Path(self.tmp.name) / "toolsets.json")
        self.manager = SubagentManager(
            llm=FakeLLM(),
            memory=object(),
            skill_manager=object(),
            root_dir=Path(self.tmp.name),
            toolset_manager=self.toolsets,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_researcher_cannot_edit_files_or_run_commands(self):
        registry = self.manager.build_scoped_registry(role="researcher")
        self.assertIsNotNone(registry.get("read_file"))
        self.assertIsNone(registry.get("write_file"))
        self.assertIsNone(registry.get("run_command"))

    def test_coder_role_receives_coding_tools(self):
        registry = self.manager.build_scoped_registry(role="coder")
        self.assertIsNotNone(registry.get("read_file"))
        self.assertIsNotNone(registry.get("write_file"))
        self.assertIsNotNone(registry.get("run_command"))
        self.assertIsNotNone(registry.get("inspect_project"))

    def test_explicit_toolsets_can_only_narrow_role_permissions(self):
        registry = self.manager.build_scoped_registry(
            toolset_names=["terminal", "filesystem"],
            role="researcher",
        )
        self.assertIsNotNone(registry.get("read_file"))
        self.assertIsNone(registry.get("run_command"))
        self.assertIsNone(registry.get("write_file"))


class SubagentConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegate_many_runs_independent_workers_with_a_concurrency_limit(self):
        state = {"active": 0, "maximum": 0}

        class FakeAgent:
            def __init__(self, **kwargs):
                pass

            def build_system_prompt(self):
                return "base prompt"

            async def run(self, prompt):
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
                try:
                    await asyncio.sleep(0.025)
                    return "verified worker result"
                finally:
                    state["active"] -= 1

        with tempfile.TemporaryDirectory() as tmp:
            manager = SubagentManager(
                llm=FakeLLM(),
                memory=object(),
                skill_manager=object(),
                root_dir=Path(tmp),
                max_concurrency=2,
                default_timeout=10,
                max_steps=8,
            )
            with patch("nexus.orchestrator.subagent.NexusAgent", FakeAgent):
                result = await manager.delegate_many(
                    "parent-session",
                    [{"goal": f"independent task {i}", "role": "researcher"} for i in range(4)],
                )

        self.assertIn("Completed 4 delegated task(s)", result)
        self.assertEqual(result.count("verified worker result"), 4)
        self.assertEqual(state["active"], 0)
        self.assertEqual(state["maximum"], 2)

    async def test_delegate_many_rejects_empty_and_oversized_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SubagentManager(
                llm=FakeLLM(),
                memory=object(),
                skill_manager=object(),
                root_dir=Path(tmp),
            )
            self.assertIn("non-empty list", await manager.delegate_many("s", []))
            self.assertIn("at most 8", await manager.delegate_many(
                "s", [{"goal": str(i)} for i in range(9)]
            ))

    async def test_observer_failure_does_not_break_subagent_execution(self):
        def broken_observer(event, message):
            raise RuntimeError("UI disconnected")

        with tempfile.TemporaryDirectory() as tmp:
            manager = SubagentManager(
                llm=FakeLLM(),
                memory=object(),
                skill_manager=object(),
                root_dir=Path(tmp),
                on_subagent_event=broken_observer,
            )
            manager._emit("start", "event")
            self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
