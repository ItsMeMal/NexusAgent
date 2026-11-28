import unittest

from nexus.tools.base import Tool, ToolRegistry


class ToolAliasTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_and_cat_aliases_resolve_to_read_file(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="read_file",
            description="Read a workspace file.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            handler=lambda path: "read:" + path,
        ))
        self.assertEqual(await registry.execute_tool("read", {"path": "AGENTS.md"}), "read:AGENTS.md")
        self.assertEqual(await registry.execute_tool("cat", {"path": "AGENTS.md"}), "read:AGENTS.md")


if __name__ == "__main__":
    unittest.main()
