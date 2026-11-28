import tempfile
import unittest
from pathlib import Path

from nolthira.config import (
    NOLTHIRA_HOME,
    migrate_legacy_env_file,
    migrate_legacy_home,
)


class LegacyHomeMigrationTests(unittest.TestCase):
    def test_legacy_home_is_renamed_when_new_home_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / ".nexus", root / ".nolthira"
            (old / "oauth").mkdir(parents=True)
            (old / ".env").write_text("API_KEY=keep-me\n", encoding="utf-8")
            (old / "oauth" / "tokens.json").write_text(
                '{"refresh_token":"keep-me"}', encoding="utf-8"
            )
            (old / "engine" / ".git").mkdir(parents=True)
            (old / "engine" / ".git" / "HEAD").write_text(
                "ref: refs/heads/main\n", encoding="utf-8"
            )

            self.assertTrue(migrate_legacy_home(old, new))
            self.assertFalse(old.exists())
            self.assertEqual((new / ".env").read_text(encoding="utf-8"), "API_KEY=keep-me\n")
            self.assertTrue((new / "oauth" / "tokens.json").exists())
            self.assertTrue((new / "engine" / ".git" / "HEAD").exists())

    def test_existing_new_home_wins_conflicts_but_receives_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / ".nexus", root / ".nolthira"
            old.mkdir()
            new.mkdir()
            (old / ".env").write_text("API_KEY=legacy\n", encoding="utf-8")
            (new / ".env").write_text("API_KEY=current\n", encoding="utf-8")
            (old / "oauth").mkdir()
            (new / "oauth").mkdir()
            (old / "oauth" / "missing.json").write_text("old-token", encoding="utf-8")
            (old / "oauth" / "shared.json").write_text("old", encoding="utf-8")
            (new / "oauth" / "shared.json").write_text("new", encoding="utf-8")

            self.assertTrue(migrate_legacy_home(old, new))
            self.assertEqual((new / ".env").read_text(encoding="utf-8"), "API_KEY=current\n")
            self.assertEqual((new / "oauth" / "missing.json").read_text(encoding="utf-8"), "old-token")
            self.assertEqual((new / "oauth" / "shared.json").read_text(encoding="utf-8"), "new")
            self.assertEqual((old / ".env").read_text(encoding="utf-8"), "API_KEY=legacy\n")
            self.assertEqual((old / "oauth" / "shared.json").read_text(encoding="utf-8"), "old")

    def test_existing_engine_and_venv_are_kept_separate_on_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / ".nexus", root / ".nolthira"
            (old / "engine" / ".git").mkdir(parents=True)
            (new / "engine" / ".git").mkdir(parents=True)
            (old / "engine" / ".git" / "HEAD").write_text("old", encoding="utf-8")
            (new / "engine" / ".git" / "HEAD").write_text("new", encoding="utf-8")
            (old / "venv" / "bin").mkdir(parents=True)
            (new / "venv" / "bin").mkdir(parents=True)
            (old / "venv" / "bin" / "python").write_text("old", encoding="utf-8")
            (new / "venv" / "bin" / "python").write_text("new", encoding="utf-8")

            migrate_legacy_home(old, new)
            self.assertEqual((new / "engine" / ".git" / "HEAD").read_text(encoding="utf-8"), "new")
            self.assertEqual((old / "engine" / ".git" / "HEAD").read_text(encoding="utf-8"), "old")
            self.assertEqual((new / "venv" / "bin" / "python").read_text(encoding="utf-8"), "new")
            self.assertEqual((old / "venv" / "bin" / "python").read_text(encoding="utf-8"), "old")

    def test_canonical_home_is_nolthira(self):
        self.assertEqual(NOLTHIRA_HOME.name, ".nolthira")

    def test_legacy_env_keys_are_renamed_without_overwriting_new_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "NEXUS_MODEL=legacy-model\n"
                "NOLTHIRA_MODEL=current-model\n"
                "NEXUS_TEMPERATURE=0.3\n"
                "NEXUS_MEMORY_DB=nexus_memory.db\n"
                "MALLSS_NEXUS_API_KEY=gateway-key\n",
                encoding="utf-8",
            )

            self.assertTrue(migrate_legacy_env_file(env_file))
            updated = env_file.read_text(encoding="utf-8")
            self.assertIn("NOLTHIRA_MODEL=current-model", updated)
            self.assertIn("NOLTHIRA_TEMPERATURE=0.3", updated)
            self.assertIn("NOLTHIRA_MEMORY_DB=nolthira_memory.db", updated)
            self.assertNotIn("NEXUS_MODEL=", updated)
            self.assertNotIn("NEXUS_TEMPERATURE=", updated)
            self.assertIn("MALLSS_NEXUS_API_KEY=gateway-key", updated)


class WindowsInstallerRegressionTests(unittest.TestCase):
    def test_install_script_has_no_bom_for_irm_pipe_iex(self):
        installer = Path(__file__).resolve().parents[1] / "install.ps1"
        raw = installer.read_bytes()
        self.assertFalse(raw.startswith(bytes.fromhex("efbbbf")))

    def test_windows_launchers_add_engine_root_to_pythonpath(self):
        installer = (Path(__file__).resolve().parents[1] / "install.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('set "PYTHONPATH=$engineDir;%PYTHONPATH%"', installer)
        self.assertIn("`$env:PYTHONPATH = if", installer)

    def test_installer_checks_cli_import_before_success(self):
        installer = (Path(__file__).resolve().parents[1] / "install.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('& $venvPython -c "import nolthira.cli"', installer)
        self.assertIn("Nolthira CLI import check failed", installer)


if __name__ == "__main__":
    unittest.main()
