import json
import tempfile
import unittest
from pathlib import Path

from nexus.toolsets import BUILTIN_TOOLSETS, ToolsetConfigError, ToolsetManager
from nexus.tools.base import Tool, ToolRegistry


def make_tool(name):
    return Tool(
        name=name,
        description=f"Test tool {name}",
        parameters={"type": "object", "properties": {}},
        handler=lambda: f"{name}:ok",
    )


class ToolsetManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "toolsets.json"
        self.manager = ToolsetManager(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_profiles_include_researcher_and_coder_permissions(self):
        researcher = self.manager.resolve_profile("researcher")
        coder = self.manager.resolve_profile("coder")

        self.assertIn("filesystem", researcher["enabled_toolsets"])
        self.assertNotIn("terminal", researcher["enabled_toolsets"])
        self.assertIn("filesystem", coder["enabled_toolsets"])
        self.assertIn("terminal", coder["enabled_toolsets"])
        self.assertIn("write_file", researcher["disabled_tools"])
        self.assertIn("record_learning", researcher["disabled_tools"])
        self.assertIn("dismiss_learning_observation", researcher["disabled_tools"])
        self.assertNotIn("write_file", coder["disabled_tools"])
        self.assertNotIn("memory", self.manager.resolve_profile("gateway")["enabled_toolsets"])

    def test_registry_policy_blocks_tools_and_aliases_at_execution_time(self):
        registry = ToolRegistry()
        registry.register(make_tool("read_file"), toolset="filesystem")
        registry.register(make_tool("write_file"), toolset="filesystem")
        registry.register(make_tool("run_command"), toolset="terminal")
        self.manager.apply(registry, "researcher")

        self.assertIsNotNone(registry.get("read_file"))
        self.assertIsNone(registry.get("write_file"))
        self.assertIsNone(registry.get("run_command"))
        self.assertIn("Access denied", __import__("asyncio").run(registry.execute_tool("writefile", {})))
        self.assertEqual([tool.name for tool in registry.get_all()], ["read_file"])

    def test_clone_preserves_tool_categories_and_policy(self):
        registry = ToolRegistry()
        registry.register(make_tool("read_file"), toolset="filesystem")
        registry.register(make_tool("run_command"), toolset="terminal")
        self.manager.apply(registry, "researcher")

        cloned = registry.clone()
        self.assertIsNotNone(cloned.get("read_file"))
        self.assertIsNone(cloned.get("run_command"))
        cloned.set_toolset_policy(enabled_toolsets=BUILTIN_TOOLSETS, disabled_tools=[])
        self.assertIsNotNone(cloned.get("run_command"))
        self.assertIsNone(registry.get("run_command"))

    def test_profile_updates_persist_and_inheritance_is_applied(self):
        self.manager.set_toolset("researcher", "terminal", True)
        self.manager.set_default_profile("researcher")
        self.manager.set_platform_profile("telegram", "researcher")
        self.manager.set_role_profile("researcher", "coder")

        reloaded = ToolsetManager(self.path)
        self.assertEqual(reloaded.default_profile, "researcher")
        self.assertIn("terminal", reloaded.resolve_profile("researcher")["enabled_toolsets"])
        self.assertEqual(reloaded.profile_for_platform("telegram"), "researcher")
        self.assertEqual(reloaded.profile_for_role("researcher"), "coder")

    def test_gateway_registry_uses_read_oriented_profile_by_default(self):
        from nexus.gateways.manager import GatewayManager

        registry = ToolRegistry()
        registry.register(make_tool("read_file"), toolset="filesystem")
        registry.register(make_tool("write_file"), toolset="filesystem")
        registry.register(make_tool("run_command"), toolset="terminal")
        registry.register(make_tool("gateway_send"), toolset="gateway")
        registry.register(make_tool("recall_memory"), toolset="memory")

        gateways = GatewayManager(
            llm_client=object(),
            memory=object(),
            skill_manager=object(),
            registry=registry,
            toolset_manager=self.manager,
        )

        telegram_registry = gateways.gateways["telegram"].registry
        self.assertIsNotNone(telegram_registry.get("read_file"))
        self.assertIsNone(telegram_registry.get("write_file"))
        self.assertIsNone(telegram_registry.get("run_command"))
        self.assertIsNone(telegram_registry.get("gateway_send"))
        self.assertIsNone(telegram_registry.get("recall_memory"))
        # The main interactive registry remains unchanged.
        self.assertIsNotNone(registry.get("write_file"))
        self.assertIsNotNone(registry.get("run_command"))

        self.manager.set_platform_profile("telegram", "coder")
        gateways._apply_platform_profile("telegram")
        self.assertIsNotNone(telegram_registry.get("write_file"))
        self.assertIsNotNone(telegram_registry.get("run_command"))

    def test_older_toolset_files_migrate_to_restricted_gateway_defaults(self):
        from nexus.toolsets import _default_config

        legacy = _default_config()
        legacy["version"] = 1
        legacy["profiles"].pop("gateway", None)
        legacy["platform_profiles"] = {}
        legacy["profiles"]["researcher"]["disabled_tools"] = [
            "write_file", "append_file", "patch_file", "run_command",
            "store_memory", "review_memory_proposal",
        ]
        self.path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = ToolsetManager(self.path)

        self.assertEqual(migrated.profile_for_platform("telegram"), "gateway")
        self.assertNotIn("memory", migrated.resolve_profile("gateway")["enabled_toolsets"])
        self.assertIn("record_learning", migrated.resolve_profile("researcher")["disabled_tools"])
        self.assertIn("dismiss_learning_observation", migrated.resolve_profile("researcher")["disabled_tools"])
        self.assertNotIn("memory", migrated.resolve_profile("gateway")["enabled_toolsets"])

    def test_unknown_profiles_and_toolsets_are_rejected(self):
        with self.assertRaises(ToolsetConfigError):
            self.manager.resolve_profile("does-not-exist")
        with self.assertRaises(ToolsetConfigError):
            self.manager.set_toolset("default", "not-a-toolset", True)
        with self.assertRaises(ToolsetConfigError):
            self.manager.set_default_profile("missing-profile")

    def test_inheritance_cycles_are_rejected_during_load(self):
        self.path.write_text(json.dumps({
            "version": 1,
            "default_profile": "default",
            "profiles": {
                "default": {"extends": "child"},
                "child": {"extends": "default"},
            },
        }), encoding="utf-8")
        with self.assertRaisesRegex(ToolsetConfigError, "cycle"):
            ToolsetManager(self.path)

    def test_unknown_toolsets_are_rejected_during_load(self):
        self.path.write_text(json.dumps({
            "version": 1,
            "default_profile": "default",
            "profiles": {
                "default": {"enabled_toolsets": ["filesystem", "made_up"]},
            },
        }), encoding="utf-8")
        with self.assertRaisesRegex(ToolsetConfigError, "unknown toolsets"):
            ToolsetManager(self.path)


if __name__ == "__main__":
    unittest.main()
