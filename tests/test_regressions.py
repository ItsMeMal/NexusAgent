import asyncio
import hashlib
import hmac
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.gateways.manager import GatewayManager
from nexus.gateways.slack import SlackGateway, parse_slack_api_response
from nexus.gateways.whatsapp import WhatsAppGateway
from nexus.tools.filesystem import get_filesystem_tools
from nexus.tools.base import ToolRegistry
from nexus.tools.project import inspect_project, get_project_tools


class CodingEngineRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_recovery_does_not_reintroduce_chunked_source_assembly(self):
        agent_source = (Path(__file__).resolve().parents[1] / "nexus" / "core" / "agent.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("write_file` + `append_file` calls", agent_source)
        self.assertNotIn("<= 80 lines", agent_source)
        self.assertNotIn("<=100 lines per call", agent_source)
        self.assertIn("Never assemble source files", agent_source)

    async def test_project_inspection_finds_manifests_and_instructions_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                '{"name":"sample","scripts":{"build":"next build","test":"vitest run"}}',
                encoding="utf-8",
            )
            (root / "AGENTS.md").write_text("Use the existing design system.", encoding="utf-8")
            (root / ".env").write_text("SECRET_VALUE=do-not-print", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "index.ts").write_text("export const ok = true;", encoding="utf-8")

            report = inspect_project(root)

            self.assertIn("package.json", report)
            self.assertIn("next build", report)
            self.assertIn("AGENTS.md", report)
            self.assertIn("Use the existing design system.", report)
            self.assertIn("src/index.ts", report)
            self.assertNotIn("SECRET_VALUE", report)
            self.assertNotIn("do-not-print", report)

    async def test_inspect_project_is_registered_as_a_first_class_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = {tool.name: tool for tool in get_project_tools(Path(tmp))}
            self.assertIn("inspect_project", tools)
            result = await tools["inspect_project"].execute()
            self.assertIn("Project root:", result)

    async def test_write_file_is_atomic_and_patch_refuses_ambiguous_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = {tool.name: tool for tool in get_filesystem_tools(root)}
            write_result = await tools["write_file"].execute(path="schema.prisma", content="model A {}\n")
            self.assertIn("Successfully wrote", write_result)
            self.assertEqual((root / "schema.prisma").read_text(encoding="utf-8"), "model A {}\n")

            await tools["write_file"].execute(path="duplicate.txt", content="token\ntoken\n")
            ambiguous = await tools["patch_file"].execute(
                path="duplicate.txt", target="token", replacement="changed"
            )
            self.assertIn("matched 2 times", ambiguous)
            self.assertEqual((root / "duplicate.txt").read_text(encoding="utf-8"), "token\ntoken\n")

            replaced = await tools["patch_file"].execute(
                path="duplicate.txt", target="token", replacement="changed", replace_all=True
            )
            self.assertIn("2 occurrence", replaced)
            self.assertEqual((root / "duplicate.txt").read_text(encoding="utf-8"), "changed\nchanged\n")


class GatewayRegressionTests(unittest.IsolatedAsyncioTestCase):
    def _whatsapp(self):
        return WhatsAppGateway(object(), object(), object(), ToolRegistry())

    def test_whatsapp_enabled_flag_alone_does_not_claim_a_send_capable_gateway(self):
        with patch.dict(os.environ, {"WHATSAPP_ENABLED": "true"}, clear=True):
            self.assertFalse(self._whatsapp().is_configured())

    def test_baileys_group_allowlist_uses_participant_not_group_jid(self):
        gateway = self._whatsapp()
        payload = {
            "data": {
                "key": {
                    "remoteJid": "120363000000000000@g.us",
                    "participant": "6281234567890@s.whatsapp.net",
                    "id": "MSG-1",
                    "fromMe": False,
                },
                "pushName": "Mallss",
                "message": {"conversation": "hello"},
            }
        }

        messages = gateway.extract_incoming_messages(payload)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].chat_id, "120363000000000000@g.us")
        self.assertEqual(messages[0].user_id, "6281234567890")
        self.assertTrue(messages[0].is_group)

    def test_meta_signature_verification(self):
        body = b'{"object":"whatsapp_business_account"}'
        secret = "test-app-secret"
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(WhatsAppGateway.verify_meta_signature(secret, body, f"sha256={digest}"))
        self.assertFalse(WhatsAppGateway.verify_meta_signature(secret, body, "sha256=invalid"))

    def test_slack_api_errors_are_not_treated_as_empty_success(self):
        message = parse_slack_api_response(
            {"ok": False, "error": "missing_scope"},
            status_code=200,
            operation="conversations.history",
        )
        self.assertIn("missing_scope", message)
        self.assertIsNone(
            parse_slack_api_response({"ok": True, "messages": []}, status_code=200, operation="conversations.history")
        )

    async def test_gateway_manager_reports_startup_exceptions(self):
        class BrokenGateway:
            running = False
            last_error = ""

            def is_configured(self):
                return True

            async def start(self):
                raise RuntimeError("invalid credentials")

            async def stop(self):
                self.running = False

        manager = GatewayManager(object(), object(), object(), ToolRegistry())
        manager.gateways = {"broken": BrokenGateway()}
        result = await manager.start_gateway("broken")

        self.assertEqual(result["broken"], "failed")
        self.assertIn("invalid credentials", manager.gateways["broken"].last_error)


if __name__ == "__main__":
    unittest.main()
