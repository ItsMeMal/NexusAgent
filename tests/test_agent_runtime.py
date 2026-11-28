import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from nexus.core.agent import NexusAgent


class FakeMemory:
    def __init__(self):
        self.messages = []

    def create_session(self, session_id, title=""):
        self.session_id = session_id
        return session_id

    def get_session_history(self, session_id):
        return list(self.messages)

    def save_message(self, session_id, role, content, tool_calls=None, tool_call_id=None):
        message = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        if tool_call_id:
            message["tool_call_id"] = tool_call_id
        self.messages.append(message)

    def get_all_memories(self, limit=20):
        return []


class FakeSkills:
    def get_skills_summary(self, compact=True):
        return "No skills."


class FakeRegistry:
    def __init__(self):
        self.calls = []

    def get(self, name):
        return None

    def to_openai_schemas(self):
        return [{
            "type": "function",
            "function": {
                "name": "fake_tool",
                "description": "A test tool.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }]

    async def execute_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return "Tool completed: " + arguments.get("value", "")


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat_completion(self, messages, tools=None, on_token=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self.responses:
            raise AssertionError("Unexpected extra LLM call")
        return self.responses.pop(0)


def tool_call(call_id="call-1", value="ok", content=None):
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": "fake_tool",
                "arguments": '{"value":"' + value + '"}',
            },
        }],
    }


class AgentRuntimeContinuationTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, llm, max_steps=6):
        memory = FakeMemory()
        registry = FakeRegistry()
        agent = NexusAgent(
            llm_client=llm,
            memory=memory,
            skill_manager=FakeSkills(),
            registry=registry,
            soul_path=Path(tempfile.gettempdir()) / "nexus-test-soul-does-not-exist.md",
            max_steps=max_steps,
            mode="auto",
        )
        return agent, memory, registry

    async def test_tool_call_narration_is_not_mistaken_for_final_answer(self):
        llm = ScriptedLLM([
            tool_call(content="I found the issue. I am checking the file now."),
            {"role": "assistant", "content": "The file is correct and the check passed."},
        ])
        agent, memory, registry = self.make_agent(llm)

        result = await agent.run("Inspect and verify the file.")

        self.assertEqual(result, "The file is correct and the check passed.")
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[1]["messages"][-1]["role"], "tool")
        self.assertEqual(memory.messages[-1]["content"], result)

    async def test_empty_assistant_turn_after_tool_gets_one_continuation_retry(self):
        llm = ScriptedLLM([
            tool_call(content="I am applying the requested change."),
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "The change is complete and verified."},
        ])
        agent, _, registry = self.make_agent(llm)

        result = await agent.run("Apply and verify the change.")

        self.assertEqual(result, "The change is complete and verified.")
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(len(llm.calls), 3)
        self.assertIn(
            "Continue the existing task",
            llm.calls[2]["messages"][-1]["content"],
        )

    async def test_step_budget_after_tool_call_still_generates_a_truthful_summary(self):
        llm = ScriptedLLM([
            tool_call(content="I am creating the file."),
            {"role": "assistant", "content": "A file was created, but verification has not run yet."},
        ])
        agent, memory, registry = self.make_agent(llm, max_steps=1)

        result = await agent.run("Create a file and verify it.")

        self.assertEqual(result, "A file was created, but verification has not run yet.")
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(len(llm.calls), 2)
        self.assertIsNone(llm.calls[1]["tools"])
        self.assertEqual(memory.messages[-1]["content"], result)


class FakeCommandRegistry:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def get(self, name):
        return None

    def to_openai_schemas(self):
        return [{
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a shell command.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["command"],
                },
            },
        }]

    async def execute_tool(self, name, arguments):
        self.calls.append(dict(arguments))
        return self.results.pop(0)


def command_tool_call(call_id, command, timeout=120):
    return {
        "role": "assistant",
        "content": "[calling tools]",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": "run_command",
                "arguments": json.dumps({"command": command, "timeout": timeout}),
            },
        }],
    }


class FakeEnvRecoveryRegistry:
    def __init__(self, command_results):
        self.command_results = list(command_results)
        self.calls = []

    def get(self, name):
        return None

    def to_openai_schemas(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Run a shell command.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "timeout": {"type": "integer"},
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_env",
                    "description": "Safely update selected environment variables.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "updates": {"type": "object"},
                        },
                        "required": ["updates"],
                    },
                },
            },
        ]

    async def execute_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == "update_env":
            return "Successfully updated 1 environment variable(s) in '.env': DATABASE_URL. Existing values were not read or returned."
        if name == "run_command":
            return self.command_results.pop(0)
        raise AssertionError(f"Unexpected tool: {name}")


def env_update_tool_call(call_id, updates):
    return {
        "role": "assistant",
        "content": "[calling tools]",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": "update_env",
                "arguments": json.dumps({"path": ".env", "updates": updates}),
            },
        }],
    }


class AgentCommandRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, llm, registry, max_steps=8):
        memory = FakeMemory()
        agent = NexusAgent(
            llm_client=llm,
            memory=memory,
            skill_manager=FakeSkills(),
            registry=registry,
            soul_path=Path(tempfile.gettempdir()) / "nexus-test-soul-does-not-exist.md",
            max_steps=max_steps,
            mode="auto",
        )
        return agent, memory

    async def test_failed_command_cannot_bypass_loop_guard_by_changing_timeout(self):
        deploy = "npx prisma migrate deploy"
        status = "npx prisma migrate status"
        llm = ScriptedLLM([
            command_tool_call("cmd-1", deploy, timeout=300),
            command_tool_call("cmd-2", deploy, timeout=300),
            command_tool_call("cmd-3", deploy, timeout=180),
            command_tool_call("cmd-4", status, timeout=60),
            {"role": "assistant", "content": "Migration status was inspected; the failed deploy still needs its specific error repaired."},
        ])
        registry = FakeCommandRegistry([
            "Exit Code: 0\nSTDOUT:\nInitial deployment completed.",
            "[COMMAND FAILED: exit code 1]\nSTDERR:\nP3009: a previous migration failed.",
            "Exit Code: 0\nSTDOUT:\nNo pending migrations.",
        ])
        agent, _ = self.make_agent(llm, registry)

        result = await agent.run("Deploy database migrations and verify their status.")

        self.assertIn("Migration status was inspected", result)
        self.assertEqual(
            [call["command"] for call in registry.calls],
            [deploy, deploy, status],
        )
        guarded_turn = llm.calls[3]["messages"]
        self.assertTrue(any(
            "was NOT executed" in str(message.get("content", ""))
            and "Changing only its timeout does not fix that failure" in str(message.get("content", ""))
            for message in guarded_turn
        ))

    async def test_same_command_can_retry_after_successful_environment_remediation(self):
        command = "npx prisma migrate deploy"
        llm = ScriptedLLM([
            command_tool_call("cmd-fail", command, timeout=300),
            env_update_tool_call("env-fix", {"DATABASE_URL": "postgresql://mock/db"}),
            command_tool_call("cmd-retry", command, timeout=300),
            {"role": "assistant", "content": "Database URL was updated securely and the migration then completed."},
        ])
        registry = FakeEnvRecoveryRegistry([
            "[COMMAND FAILED: exit code 1]\nSTDERR:\nP1001: database server is unreachable.",
            "Exit Code: 0\nSTDOUT:\nMigrations applied.",
        ])
        agent, _ = self.make_agent(llm, registry)

        result = await agent.run("Configure the database connection and deploy migrations.")

        self.assertIn("migration then completed", result)
        self.assertEqual([name for name, _ in registry.calls], ["run_command", "update_env", "run_command"])
        self.assertEqual(registry.calls[0][1]["command"], command)
        self.assertEqual(registry.calls[2][1]["command"], command)
        self.assertTrue(any(
            "Successfully updated 1 environment variable" in str(message.get("content", ""))
            for message in llm.calls[2]["messages"]
        ))

    async def test_explicit_timeout_allows_one_retry_with_a_longer_timeout(self):
        command = "npx prisma generate"
        llm = ScriptedLLM([
            command_tool_call("timeout-1", command, timeout=120),
            command_tool_call("timeout-2", command, timeout=360),
            {"role": "assistant", "content": "Prisma generation completed after one longer-timeout retry."},
        ])
        registry = FakeCommandRegistry([
            "Error: Command timed out after 300 seconds (process tree terminated cleanly).",
            "Exit Code: 0\nSTDOUT:\nPrisma Client generated.",
        ])
        agent, _ = self.make_agent(llm, registry)

        result = await agent.run("Generate the Prisma client.")

        self.assertIn("completed after one longer-timeout retry", result)
        self.assertEqual(len(registry.calls), 2)
        self.assertEqual(registry.calls[1]["timeout"], 360)


class FakeRepeatableProcessRegistry:
    def __init__(self):
        self.calls = []

    def to_openai_schemas(self):
        return [{
            "type": "function",
            "function": {
                "name": "process",
                "description": "Read process output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["action", "session_id"],
                },
            },
        }]

    def get(self, name):
        return None

    async def execute_tool(self, name, arguments):
        self.calls.append(dict(arguments))
        return "Process log: still running; fresh output available."


def repeatable_log_call(call_id):
    return {
        "role": "assistant",
        "content": "[calling tools]",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": "process",
                "arguments": json.dumps({"action": "log", "session_id": "proc_test"}),
            },
        }],
    }


class RepeatableProcessReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_process_log_reads_are_allowed(self):
        llm = ScriptedLLM([
            repeatable_log_call("log-1"),
            repeatable_log_call("log-2"),
            repeatable_log_call("log-3"),
            {"role": "assistant", "content": "The background process is still running."},
        ])
        memory = FakeMemory()
        registry = FakeRepeatableProcessRegistry()
        agent = NexusAgent(
            llm_client=llm,
            memory=memory,
            skill_manager=FakeSkills(),
            registry=registry,
            soul_path=Path(tempfile.gettempdir()) / "nexus-test-soul-does-not-exist.md",
            max_steps=6,
            mode="auto",
        )
        result = await agent.run("Check the running background process logs.")
        self.assertEqual(result, "The background process is still running.")
        self.assertEqual(len(registry.calls), 3)
        self.assertTrue(all(
            call == {"action": "log", "session_id": "proc_test"}
            for call in registry.calls
        ))


if __name__ == "__main__":
    unittest.main()
