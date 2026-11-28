import os
import warnings
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Suppress noisy runtime and resource warnings from third-party libraries and async runtimes
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Codebase root where Nexus Agent engine is located
CODEBASE_DIR = Path(__file__).resolve().parent.parent

# Current working directory where user invoked the command
WORKSPACE_DIR = Path.cwd()

# Canonical user home for Nolthira settings, credentials, sessions, and memory.
# Legacy ~/.nexus is migrated without overwriting files already present in ~/.nolthira.
NOLTHIRA_HOME = Path.home() / ".nolthira"
LEGACY_NEXUS_HOME = Path.home() / ".nexus"
_PROTECTED_MERGE_DIRS = {"engine", "venv", ".git"}


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _merge_missing_home_entries(source: Path, destination: Path) -> int:
    """Move missing entries only; preserve collisions in the legacy directory."""
    moved = 0
    destination.mkdir(parents=True, exist_ok=True)
    for entry in list(source.iterdir()):
        target = destination / entry.name
        source_is_dir = entry.is_dir() and not entry.is_symlink()
        if _path_exists(target):
            target_is_dir = target.is_dir() and not target.is_symlink()
            if source_is_dir and target_is_dir and entry.name.casefold() not in _PROTECTED_MERGE_DIRS:
                moved += _merge_missing_home_entries(entry, target)
            continue
        try:
            shutil.move(str(entry), str(target))
            moved += 1
        except OSError:
            continue
    try:
        source.rmdir()
    except OSError:
        pass
    return moved


def migrate_legacy_home(legacy_home: Path, nolthira_home: Path) -> bool:
    """Migrate ~/.nexus to ~/.nolthira without overwriting destination data."""
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
            f"Some legacy files remain in {LEGACY_NEXUS_HOME}: conflicting files or existing "
            "engine/venv directories were kept as backups and were not overwritten.",
            UserWarning,
            stacklevel=2,
        )
except OSError as exc:
    warnings.warn(f"Could not fully migrate the legacy Nolthira home directory: {exc}", UserWarning)


# Backward-compatible alias; its resolved path is now ~/.nolthira.
NEXUS_HOME = NOLTHIRA_HOME

# Determine primary .env file with priority:
# 1. Local workspace .env (project-specific override)
# 2. Global ~/.nolthira/.env (persistent global user config)
# 3. Codebase .env (fallback)
if (WORKSPACE_DIR / ".env").exists():
    ENV_PATH = WORKSPACE_DIR / ".env"
elif (NOLTHIRA_HOME / ".env").exists():
    ENV_PATH = NOLTHIRA_HOME / ".env"
elif (CODEBASE_DIR / ".env").exists():
    ENV_PATH = CODEBASE_DIR / ".env"
else:
    ENV_PATH = NOLTHIRA_HOME / ".env"

load_dotenv(ENV_PATH, override=True)

class Config:
    CODEBASE_DIR: Path = CODEBASE_DIR
    WORKSPACE_DIR: Path = WORKSPACE_DIR
    ROOT_DIR: Path = WORKSPACE_DIR  # Primary working directory for tools
    NOLTHIRA_HOME: Path = NOLTHIRA_HOME
    NEXUS_HOME: Path = NOLTHIRA_HOME  # Backward-compatible attribute alias
    ENV_PATH: Path = ENV_PATH

    # Persona & Skills paths
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
        Path(os.getenv("NEXUS_SKILLS_DIR"))
        if os.getenv("NEXUS_SKILLS_DIR")
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

    # API and Model (Prioritize workspace/env configurations)
    API_KEY: str = (
        os.getenv("NEXUS_API_KEY")
        or os.getenv("MALLSS_NEXUS_API_KEY")
        or os.getenv("OPENAI_API_KEY", "")
    )
    API_BASE: str = (
        os.getenv("NEXUS_API_BASE")
        or os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    )
    MODEL: str = os.getenv("NEXUS_MODEL", "anthropic/claude-3.5-sonnet")
    AGENT_MODE: str = os.getenv("NEXUS_AGENT_MODE", "auto").strip().lower()
    TEMPERATURE: float = float(os.getenv("NEXUS_TEMPERATURE", "0.7"))
    MAX_STEPS: int = int(os.getenv("NEXUS_MAX_STEPS", "25"))

    # Storage (Global persistent memory in ~/.nolthira/nexus_memory.db by default)
    _default_db = (
        NOLTHIRA_HOME / "nexus_memory.db"
        if NOLTHIRA_HOME.exists()
        else CODEBASE_DIR / "nexus_memory.db"
    )
    MEMORY_DB_PATH: Path = Path(os.getenv("NEXUS_MEMORY_DB", str(_default_db)))
    SCREENSHOTS_DIR: Path = NOLTHIRA_HOME / "screenshots"
    AUTO_APPROVE: bool = os.getenv("NEXUS_AUTO_APPROVE", "false").lower() in ("true", "1", "yes")

    # Execution Sandbox Backend (local | docker | ssh)
    EXEC_BACKEND: str = os.getenv("NEXUS_EXEC_BACKEND", "local").strip().lower()
    DOCKER_IMAGE: str = os.getenv("NEXUS_DOCKER_IMAGE", "python:3.12-slim").strip()
    SSH_HOST: str = os.getenv("NEXUS_SSH_HOST", "").strip()
    SSH_USER: str = os.getenv("NEXUS_SSH_USER", "").strip()
    SSH_KEY_PATH: str = os.getenv("NEXUS_SSH_KEY_PATH", "").strip()

    # GitHub App integration
    GITHUB_APP_ID: str = os.getenv("GITHUB_APP_ID", "")
    GITHUB_INSTALLATION_ID: str = os.getenv("GITHUB_INSTALLATION_ID", "")
    GITHUB_APP_PRIVATE_KEY_PATH: str = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")
    GITHUB_APP_PRIVATE_KEY: str = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
    GITHUB_WEBHOOK_SECRET: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    GITHUB_WEBHOOK_PORT: int = int(os.getenv("GITHUB_WEBHOOK_PORT", "8765"))

    @property
    def github_app_configured(self) -> bool:
        """True if the minimum GitHub App env vars are present."""
        return bool(
            self.GITHUB_APP_ID
            and self.GITHUB_INSTALLATION_ID
            and (self.GITHUB_APP_PRIVATE_KEY_PATH or self.GITHUB_APP_PRIVATE_KEY)
        )

try:
    Config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

config = Config()
