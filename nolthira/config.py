import os
import re
import shutil
import warnings
from pathlib import Path

from dotenv import load_dotenv

# Keep third-party async/runtime warnings quiet in normal CLI usage.
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# The package directory is the engine root (nolthira/ is one level below it).
CODEBASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = Path.cwd()

NOLTHIRA_HOME = Path.home() / ".nolthira"
LEGACY_NEXUS_HOME = Path.home() / ".nexus"
_PROTECTED_MERGE_DIRS = {"engine", "venv", ".git"}


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _merge_missing_home_entries(source: Path, destination: Path) -> int:
    """Move missing entries only; preserve conflicts in the old directory."""
    moved = 0
    destination.mkdir(parents=True, exist_ok=True)
    for entry in list(source.iterdir()):
        target = destination / entry.name
        is_dir = entry.is_dir() and not entry.is_symlink()
        if _path_exists(target):
            target_is_dir = target.is_dir() and not target.is_symlink()
            if is_dir and target_is_dir and entry.name.casefold() not in _PROTECTED_MERGE_DIRS:
                moved += _merge_missing_home_entries(entry, target)
            continue
        try:
            shutil.move(str(entry), str(target))
            moved += 1
        except OSError:
            # Leave anything unmovable in the old home; never overwrite.
            continue
    try:
        source.rmdir()
    except OSError:
        pass
    return moved


def migrate_legacy_home(legacy_home: Path, nolthira_home: Path) -> bool:
    """Move legacy ~/.nexus data into ~/.nolthira without overwriting new data."""
    legacy_home = Path(legacy_home).expanduser()
    nolthira_home = Path(nolthira_home).expanduser()

    if legacy_home.is_symlink() or not legacy_home.is_dir():
        return False
    if nolthira_home.is_symlink():
        raise OSError(f"Refusing to migrate into a symlinked home path: {nolthira_home}")

    if _path_exists(nolthira_home):
        if not nolthira_home.is_dir():
            raise NotADirectoryError(f"Nolthira home path is not a directory: {nolthira_home}")
        _merge_missing_home_entries(legacy_home, nolthira_home)
        return True

    try:
        legacy_home.replace(nolthira_home)
        return True
    except OSError:
        nolthira_home.mkdir(parents=True, exist_ok=True)
        _merge_missing_home_entries(legacy_home, nolthira_home)
        return True


try:
    migrate_legacy_home(LEGACY_NEXUS_HOME, NOLTHIRA_HOME)
    NOLTHIRA_HOME.mkdir(parents=True, exist_ok=True)
    if LEGACY_NEXUS_HOME.exists():
        warnings.warn(
            f"Some legacy files remain in {LEGACY_NEXUS_HOME}: conflicting files or "
            "existing engine/venv directories were kept as backups and were not overwritten.",
            UserWarning,
            stacklevel=2,
        )
except OSError as exc:
    warnings.warn(f"Could not fully migrate the legacy Nolthira home directory: {exc}", UserWarning)


# Prefer workspace .env, then global Nolthira .env, then engine fallback.
if (WORKSPACE_DIR / ".env").is_file():
    ENV_PATH = WORKSPACE_DIR / ".env"
elif (NOLTHIRA_HOME / ".env").is_file():
    ENV_PATH = NOLTHIRA_HOME / ".env"
elif (CODEBASE_DIR / ".env").is_file():
    ENV_PATH = CODEBASE_DIR / ".env"
else:
    ENV_PATH = NOLTHIRA_HOME / ".env"


def migrate_legacy_env_file(env_path: Path) -> bool:
    """Rename NEXUS_* keys in an existing dotenv file to NOLTHIRA_* safely."""
    env_path = Path(env_path)
    if not env_path.is_file():
        return False

    lines = env_path.read_text(encoding="utf-8").splitlines()
    key_pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    old_pattern = re.compile(r"^(\s*(?:export\s+)?)(NEXUS_[A-Z0-9_]+)(\s*=.*)$")
    current_keys = {
        match.group(1)
        for line in lines
        if (match := key_pattern.match(line))
    }

    migrated_lines = []
    changed = False
    for line in lines:
        match = old_pattern.match(line)
        if not match:
            migrated_lines.append(line)
            continue

        old_key = match.group(2)
        new_key = "NOLTHIRA_" + old_key[len("NEXUS_"):]
        if new_key not in current_keys:
            value_line = match.group(1) + new_key + match.group(3)
            if old_key == "NEXUS_MEMORY_DB":
                value_line = value_line.replace("=nexus_memory.db", "=nolthira_memory.db")
            migrated_lines.append(value_line)
            current_keys.add(new_key)
        changed = True

    if changed:
        env_path.write_text("\n".join(migrated_lines) + "\n", encoding="utf-8")
    return changed


def migrate_legacy_process_env() -> None:
    """Copy old process variables to new names; explicitly set new names win."""
    for key, value in list(os.environ.items()):
        if key.startswith("NEXUS_"):
            os.environ.setdefault("NOLTHIRA_" + key[len("NEXUS_"):], value)


try:
    migrate_legacy_env_file(ENV_PATH)
except OSError as exc:
    warnings.warn(f"Could not migrate legacy Nolthira environment names: {exc}", UserWarning)

migrate_legacy_process_env()
load_dotenv(ENV_PATH, override=True)

# Preserve the existing SQLite database contents while renaming its default file.
_LEGACY_MEMORY_DB = NOLTHIRA_HOME / "nexus_memory.db"
_CANONICAL_MEMORY_DB = NOLTHIRA_HOME / "nolthira_memory.db"
if _LEGACY_MEMORY_DB.is_file() and not _CANONICAL_MEMORY_DB.exists():
    try:
        _LEGACY_MEMORY_DB.replace(_CANONICAL_MEMORY_DB)
    except OSError as exc:
        warnings.warn(f"Could not rename the legacy memory database: {exc}", UserWarning)


class Config:
    CODEBASE_DIR: Path = CODEBASE_DIR
    WORKSPACE_DIR: Path = WORKSPACE_DIR
    ROOT_DIR: Path = WORKSPACE_DIR
    NOLTHIRA_HOME: Path = NOLTHIRA_HOME
    ENV_PATH: Path = ENV_PATH

    SOUL_PATH: Path = (
        WORKSPACE_DIR / "SOUL.md"
        if (WORKSPACE_DIR / "SOUL.md").exists()
        else (
            NOLTHIRA_HOME / "SOUL.md"
            if (NOLTHIRA_HOME / "SOUL.md").exists()
            else CODEBASE_DIR / "SOUL.md"
        )
    )
    SKILLS_DIR: Path = (
        Path(os.getenv("NOLTHIRA_SKILLS_DIR"))
        if os.getenv("NOLTHIRA_SKILLS_DIR")
        else (
            WORKSPACE_DIR / ".skills"
            if (WORKSPACE_DIR / ".skills").exists()
            else (
                NOLTHIRA_HOME / "skills"
                if (NOLTHIRA_HOME / "skills").exists()
                else (
                    Path.home() / ".agents" / "skills"
                    if (Path.home() / ".agents" / "skills").exists()
                    else CODEBASE_DIR / ".skills"
                )
            )
        )
    )

    API_KEY: str = (
        os.getenv("NOLTHIRA_API_KEY")
        or os.getenv("MALLSS_NEXUS_API_KEY")
        or os.getenv("OPENAI_API_KEY", "")
    )
    API_BASE: str = (
        os.getenv("NOLTHIRA_API_BASE")
        or os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    )
    MODEL: str = os.getenv("NOLTHIRA_MODEL", "anthropic/claude-3.5-sonnet")
    AGENT_MODE: str = os.getenv("NOLTHIRA_AGENT_MODE", "auto").strip().lower()
    TEMPERATURE: float = float(os.getenv("NOLTHIRA_TEMPERATURE", "0.7"))
    MAX_STEPS: int = int(os.getenv("NOLTHIRA_MAX_STEPS", "25"))

    _default_db = (
        _CANONICAL_MEMORY_DB
        if NOLTHIRA_HOME.exists()
        else CODEBASE_DIR / "nolthira_memory.db"
    )
    MEMORY_DB_PATH: Path = Path(os.getenv("NOLTHIRA_MEMORY_DB", str(_default_db)))
    SCREENSHOTS_DIR: Path = NOLTHIRA_HOME / "screenshots"
    AUTO_APPROVE: bool = os.getenv("NOLTHIRA_AUTO_APPROVE", "false").lower() in ("true", "1", "yes")

    EXEC_BACKEND: str = os.getenv("NOLTHIRA_EXEC_BACKEND", "local").strip().lower()
    DOCKER_IMAGE: str = os.getenv("NOLTHIRA_DOCKER_IMAGE", "python:3.12-slim").strip()
    SSH_HOST: str = os.getenv("NOLTHIRA_SSH_HOST", "").strip()
    SSH_USER: str = os.getenv("NOLTHIRA_SSH_USER", "").strip()
    SSH_KEY_PATH: str = os.getenv("NOLTHIRA_SSH_KEY_PATH", "").strip()

    GITHUB_APP_ID: str = os.getenv("GITHUB_APP_ID", "")
    GITHUB_INSTALLATION_ID: str = os.getenv("GITHUB_INSTALLATION_ID", "")
    GITHUB_APP_PRIVATE_KEY_PATH: str = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")
    GITHUB_APP_PRIVATE_KEY: str = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
    GITHUB_WEBHOOK_SECRET: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    GITHUB_WEBHOOK_PORT: int = int(os.getenv("GITHUB_WEBHOOK_PORT", "8765"))

    @property
    def github_app_configured(self) -> bool:
        """True if the minimum GitHub App environment variables are present."""
        return bool(
            self.GITHUB_APP_ID
            and self.GITHUB_INSTALLATION_ID
            and (self.GITHUB_APP_PRIVATE_KEY_PATH or self.GITHUB_APP_PRIVATE_KEY)
        )


try:
    Config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

config = Config()
