import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nolthira.config import config
from nolthira.tools.processes import ProcessManager
from nolthira.tools.terminal import get_terminal_tools


class BackgroundProcessManagerTests(unittest.IsolatedAsyncioTestCase):
    def make_command(self, script):
        parts = [sys.executable, "-c", script]
        if os.name == "nt":
            return subprocess.list2cmdline(parts)
        return shlex.join(parts)

    def test_start_wait_and_log_preserve_exit_status_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProcessManager(Path(tmp) / "logs")
            started = manager.start(
                self.make_command("print('build started', flush=True); print('build complete', flush=True)"),
                Path(tmp),
            )

            self.assertEqual(started["status"], "running")
            self.assertTrue(started["session_id"].startswith("proc_"))

            result = manager.wait(started["session_id"], timeout=10)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["exit_code"], 0)
            self.assertIn("build started", result["output"])
            self.assertIn("build complete", result["output"])

    def test_write_sends_input_to_the_owned_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProcessManager(Path(tmp) / "logs")
            started = manager.start(
                self.make_command("import sys; print('received:' + sys.stdin.readline().strip(), flush=True)"),
                Path(tmp),
            )
            written = manager.write(started["session_id"], "hello-nexus\n")
            self.assertEqual(written["written_bytes"], len("hello-nexus\n".encode()))

            result = manager.wait(started["session_id"], timeout=10)

            self.assertEqual(result["status"], "completed")
            self.assertIn("received:hello-nexus", result["output"])

    def test_kill_only_terminates_a_process_started_by_the_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProcessManager(Path(tmp) / "logs")
            started = manager.start(self.make_command("import time; time.sleep(30)"), Path(tmp))
            self.assertEqual(manager.poll(started["session_id"])["status"], "running")

            stopped = manager.kill(started["session_id"])

            self.assertEqual(stopped["status"], "killed")
            self.assertIsNotNone(stopped["exit_code"])
            self.assertIn(started["session_id"], [x["session_id"] for x in manager.list()])

    def test_unknown_session_cannot_be_polled_or_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProcessManager(Path(tmp) / "logs")
            self.assertIn("Unknown process session", manager.poll("12345")["error"])
            self.assertIn("Unknown process session", manager.kill("12345")["error"])

    async def test_terminal_registry_exposes_background_and_process_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(config, "NOLTHIRA_HOME", root / ".nolthira"):
                tools = {tool.name: tool for tool in get_terminal_tools(root)}

                self.assertIn("process", tools)
                started = await tools["run_command"].execute(
                    command=self.make_command("print('registered process', flush=True)"),
                    background=True,
                )
                self.assertIn("session_id", started)
                result = await tools["process"].execute(action="wait", session_id=started["session_id"], timeout=10)

                self.assertEqual(result["status"], "completed")
                self.assertIn("registered process", result["output"])


if __name__ == "__main__":
    unittest.main()
