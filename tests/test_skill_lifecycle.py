import tempfile
import unittest
from pathlib import Path

from nexus.skills import SkillManager
from nexus.tools.skill_tools import get_skill_tools


class SkillLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.primary = root / "writable-skills"
        self.external = root / "shared-skills"
        self.manager = SkillManager(self.primary, extra_dirs=[self.external])

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_refuses_silent_overwrite_and_update_is_versioned_by_file_replacement(self):
        path = self.manager.save_skill(
            "api-debugging",
            "Debug API failures systematically.",
            "Inspect the response, identify the failing layer, reproduce the problem, and verify the targeted fix.",
        )
        self.assertTrue(path.is_file())
        with self.assertRaises(FileExistsError):
            self.manager.save_skill("api-debugging", "Overwrite", "Different content.")

        updated = self.manager.update_skill(
            "api-debugging",
            "Debug API failures with evidence.",
            "Capture the request and response, inspect transport and application errors, isolate the root cause, apply a targeted fix, and run regression tests.",
        )
        self.assertEqual(updated, path)
        skill = self.manager.get_skill("api-debugging")
        self.assertIn("Capture the request", skill.content)
        self.assertTrue(skill.writable)
        self.assertTrue(self.manager.validate_skill("api-debugging")["valid"])

    def test_delete_only_removes_skill_from_the_primary_writable_directory(self):
        self.manager.save_skill(
            "owned-skill",
            "A locally owned skill.",
            "Read the relevant source, apply the documented procedure, and verify the result.",
        )
        self.assertTrue(self.manager.delete_skill("owned-skill"))
        self.assertFalse(self.manager.delete_skill("owned-skill"))

    def test_external_skill_is_readable_but_cannot_be_updated_or_deleted(self):
        self.external.mkdir(parents=True)
        external_file = self.external / "shared-debug.md"
        external_file.write_text(
            "# Skill: shared-debug\nDescription: Shared debugging guide.\n\n"
            "Inspect logs, reproduce the issue, isolate the failure, and verify the final correction.\n",
            encoding="utf-8",
        )
        skill = self.manager.get_skill("shared-debug")
        self.assertIsNotNone(skill)
        self.assertFalse(skill.writable)
        self.assertEqual(skill.source, str(self.external.resolve()))
        # Read-only is an authorization property, not a content validation failure.
        self.assertTrue(self.manager.validate_skill("shared-debug")["valid"])

        with self.assertRaises(PermissionError):
            self.manager.update_skill(
                "shared-debug",
                "Changed shared skill.",
                "These instructions must not be written to a read-only source.",
            )
        with self.assertRaises(PermissionError):
            self.manager.delete_skill("shared-debug")
        self.assertTrue(external_file.exists())

    def test_skill_lookup_rejects_path_traversal(self):
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text(
            "# Skill: outside\\nDescription: Outside file.\\n\\n"
            "This content must not be reachable through a skill identifier lookup.\\n",
            encoding="utf-8",
        )
        self.assertIsNone(self.manager.get_skill("../outside"))
        self.assertIsNone(self.manager.get_skill(r"..\\outside"))

    def test_primary_source_wins_on_normalized_name_collision(self):
        self.primary.mkdir(parents=True, exist_ok=True)
        self.external.mkdir(parents=True, exist_ok=True)
        (self.primary / "api-debug.md").write_text(
            "# Skill: api-debug\nDescription: Local version.\n\nLocal instructions with enough detail to validate.",
            encoding="utf-8",
        )
        (self.external / "API_Debug.md").write_text(
            "# Skill: API_Debug\nDescription: External version.\n\nExternal instructions with enough detail to validate.",
            encoding="utf-8",
        )
        skills = self.manager.load_all_skills()
        matches = [skill for skill in skills if skill.name.lower().replace("-", "").replace("_", "") == "apidebug"]
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].writable)
        self.assertIn("Local version", matches[0].description)

    def test_skill_names_cannot_escape_the_skill_directory(self):
        with self.assertRaises(ValueError):
            self.manager.save_skill(
                "../outside",
                "Invalid path.",
                "This should never be written outside the primary skills directory.",
            )
        with self.assertRaises(ValueError):
            self.manager.save_skill(
                r"..\outside",
                "Invalid path.",
                "This should never be written outside the primary skills directory.",
            )


    def test_create_refuses_to_shadow_an_external_read_only_skill(self):
        self.external.mkdir(parents=True)
        external_file = self.external / "shared-skill.md"
        external_file.write_text(
            "# Skill: shared-skill\nDescription: A shared external skill.\n\n"
            "Inspect the existing files, follow the task constraints, apply the procedure, and verify all results.\n",
            encoding="utf-8",
        )
        with self.assertRaises(PermissionError):
            self.manager.save_skill(
                "shared-skill",
                "Local shadow copy.",
                "This would shadow a shared skill and must be rejected by the manager.",
            )
        self.assertFalse((self.primary / "shared-skill.md").exists())
        self.assertTrue(external_file.exists())

    def test_tool_registry_exposes_the_full_local_skill_lifecycle(self):
        tools = {tool.name for tool in get_skill_tools(self.manager)}
        self.assertEqual(
            tools,
            {"list_skills", "read_skill", "create_skill", "update_skill", "delete_skill", "validate_skill"},
        )


if __name__ == "__main__":
    unittest.main()
