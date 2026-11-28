import asyncio
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


if __name__ == "__main__":
    unittest.main()
