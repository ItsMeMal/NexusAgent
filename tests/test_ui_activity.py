import io
import unittest
from unittest.mock import patch

from rich.console import Console

from nolthira import ui


class CodingActivityRenderingTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.console = Console(
            file=self.output,
            force_terminal=False,
            color_system=None,
            width=120,
        )

    def render_call(self, name, arguments):
        with patch.object(ui.tui, "console", self.console):
            ui.tui.render_tool_call(name, arguments)
        return self.output.getvalue()

    def render_result(self, name, result):
        with patch.object(ui.tui, "console", self.console):
            ui.tui.render_tool_result(name, result, elapsed=0.25)
        return self.output.getvalue()

    def test_write_file_displays_entire_source_and_line_numbers(self):
        source = (
            "export async function handler() {\n"
            "  return Response.json({ ok: true });\n"
            "}\n"
            "// final-source-marker-must-remain-visible\n"
        )
        output = self.render_call(
            "write_file",
            {"path": "src/app/api/route.ts", "content": source},
        )
        self.assertIn("WRITE", output)
        self.assertIn("src/app/api/route.ts", output)
        self.assertIn("export async function handler", output)
        self.assertIn("final-source-marker-must-remain-visible", output)
        self.assertIn("full payload", output)

    def test_write_file_redacts_secret_literals_from_display(self):
        output = self.render_call(
            "write_file",
            {
                "path": "src/config.ts",
                "content": 'export const API_KEY = "sk-this-is-a-fake-secret-value-123456";',
            },
        )
        self.assertIn("[REDACTED]", output)
        self.assertNotIn("sk-this-is-a-fake-secret-value-123456", output)

    def test_patch_file_displays_before_and_after_snippets(self):
        output = self.render_call(
            "patch_file",
            {
                "path": "src/config.ts",
                "target": 'const mode = "old";',
                "replacement": 'const mode = "new";',
            },
        )
        self.assertIn("PATCH BEFORE", output)
        self.assertIn("const mode = \"old\";", output)
        self.assertIn("PATCH AFTER", output)
        self.assertIn("const mode = \"new\";", output)

    def test_run_command_displays_complete_command(self):
        command = "npm run build -- --verbose --profile production"
        output = self.render_call("run_command", {"command": command, "timeout": 300})
        self.assertIn("COMMAND", output)
        self.assertIn(command, output)

    def test_read_file_displays_all_returned_lines(self):
        result = "1: const first = true;\n2: const last = 'visible-final-line';"
        output = self.render_result("read_file", result)
        self.assertIn("READ_FILE OUTPUT", output)
        self.assertIn("const first = true", output)
        self.assertIn("visible-final-line", output)

    def test_run_command_displays_full_captured_output(self):
        result = "Exit Code: 0\nSTDOUT:\nbuild started\nbuild finished successfully"
        output = self.render_result("run_command", result)
        self.assertIn("RUN_COMMAND OUTPUT", output)
        self.assertIn("build started", output)
        self.assertIn("build finished successfully", output)

    def test_update_env_never_displays_supplied_secret_values(self):
        output = self.render_call(
            "update_env",
            {"path": ".env", "updates": {"API_KEY": "super-secret-not-for-display"}},
        )
        self.assertIn("values hidden", output)
        self.assertNotIn("super-secret-not-for-display", output)


if __name__ == "__main__":
    unittest.main()
