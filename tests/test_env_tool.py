import os
import tempfile
import unittest
from pathlib import Path

from dotenv import dotenv_values

from nexus.tools.filesystem import get_filesystem_tools
from nexus.tools.terminal import get_terminal_tools
from nexus.security import SecurityGuard
from nexus.tools.base import ToolRegistry
from nexus.toolsets import ToolsetManager


class SafeEnvironmentUpdateTests(unittest.IsolatedAsyncioTestCase):
    def _tool(self, root: Path):
        return next(tool for tool in get_filesystem_tools(root) if tool.name == "update_env")

    async def test_updates_only_selected_keys_without_returning_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_path = root / ".env"
            env_path.write_text(
                "# keep this comment\nEXISTING_SETTING=preserve-me\nDATABASE_URL=old-value\n",
                encoding="utf-8",
            )
            secret = "postgresql://db-user:super-secret@db.example.test:5432/app?sslmode=require"
            old_value = os.environ.get("DATABASE_URL")
            try:
                result = await self._tool(root).execute(
                    path=".env",
                    updates={"DATABASE_URL": secret, "NODE_ENV": "development"},
                )

                self.assertIn("DATABASE_URL", result)
                self.assertIn("NODE_ENV", result)
                self.assertNotIn(secret, result)
                self.assertNotIn("super-secret", result)
                parsed = dotenv_values(env_path)
                self.assertEqual(parsed["DATABASE_URL"], secret)
                self.assertEqual(parsed["NODE_ENV"], "development")
                self.assertEqual(parsed["EXISTING_SETTING"], "preserve-me")
                self.assertTrue(env_path.read_text(encoding="utf-8").startswith("# keep this comment"))
                self.assertEqual(os.environ["DATABASE_URL"], secret)
            finally:
                if old_value is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = old_value
                os.environ.pop("NODE_ENV", None)

    async def test_rejects_nested_or_example_env_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tool = self._tool(root)

            example_result = await tool.execute(path=".env.example", updates={"DATABASE_URL": "not-written"})
            nested_result = await tool.execute(path="config/.env", updates={"DATABASE_URL": "not-written"})
            escape_result = await tool.execute(path="../outside/.env", updates={"DATABASE_URL": "not-written"})

            self.assertIn("Security Guard", example_result)
            self.assertIn("workspace root", nested_result)
            self.assertIn("workspace root", escape_result)
            self.assertFalse((root / ".env.example").exists())
            self.assertFalse((root / "config" / ".env").exists())

    async def test_rejects_invalid_names_and_multiline_values_without_partial_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_path = root / ".env"
            env_path.write_text("KEEP=unchanged\n", encoding="utf-8")
            tool = self._tool(root)

            bad_name = await tool.execute(path=".env", updates={"BAD=NAME": "value"})
            bad_value = await tool.execute(path=".env", updates={"NEW_VALUE": "line1\nline2"})

            self.assertIn("Invalid environment variable name", bad_name)
            self.assertIn("single-line strings", bad_value)
            self.assertEqual(dotenv_values(env_path)["KEEP"], "unchanged")
            self.assertIsNone(dotenv_values(env_path).get("NEW_VALUE"))

    async def test_terminal_cannot_bypass_dotenv_file_protection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            node_write = "node -e \"require('fs').writeFileSync('.env','LEAK=1')\""
            powershell_read = 'powershell -Command "Get-Content .env"'

            self.assertTrue(SecurityGuard.is_secret_file_access_command(node_write))
            self.assertTrue(SecurityGuard.is_secret_file_access_command(powershell_read))
            self.assertFalse(SecurityGuard.is_secret_file_access_command("dir /b /a .env*"))
            self.assertFalse(SecurityGuard.is_secret_file_access_command("dir /b /a .env* > env-files.txt"))
            self.assertFalse(SecurityGuard.is_secret_file_access_command("npx prisma migrate deploy"))

            run_command = next(tool for tool in get_terminal_tools(root) if tool.name == "run_command")
            result = await run_command.execute(command=node_write)
            self.assertIn("Security Guard", result)
            self.assertFalse((root / ".env").exists())

    async def test_researcher_toolset_cannot_mutate_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tool = self._tool(root)
            registry = ToolRegistry()
            registry.register(tool, toolset="filesystem")
            manager = ToolsetManager(root / "toolsets.json")

            manager.apply(registry, profile="researcher")
            self.assertIsNone(registry.get("update_env"))

            manager.apply(registry, profile="coder")
            self.assertIsNotNone(registry.get("update_env"))


if __name__ == "__main__":
    unittest.main()
