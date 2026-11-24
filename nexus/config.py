import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

# Suppress noisy runtime and resource warnings from third-party libraries and async runtimes
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Codebase root where Nexus Agent engine is located
CODEBASE_DIR = Path(__file__).resolve().parent.parent

# Current working directory where user invoked the command
WORKSPACE_DIR = Path.cwd()

# User home directory for global Nexus agent configuration, state, and memory:
# Windows: C:\Users\<user>\.nexus
# Linux: /home/<user>/.nexus (or /root/.nexus)
# macOS: /Users/<user>/.nexus
NEXUS_HOME = Path.home() / ".nexus"
try:
    NEXUS_HOME.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# Determine primary .env file with priority:
# 1. Local workspace .env (project-specific override)
# 2. Global ~/.nexus/.env (persistent global user config)
# 3. Codebase .env (fallback)
if (WORKSPACE_DIR / ".env").exists():
    ENV_PATH = WORKSPACE_DIR / ".env"
elif (NEXUS_HOME / ".env").exists():
    ENV_PATH = NEXUS_HOME / ".env"
elif (CODEBASE_DIR / ".env").exists():
    ENV_PATH = CODEBASE_DIR / ".env"
else:
    ENV_PATH = NEXUS_HOME / ".env"

load_dotenv(ENV_PATH)

class Config:
    CODEBASE_DIR: Path = CODEBASE_DIR
    WORKSPACE_DIR: Path = WORKSPACE_DIR
    ROOT_DIR: Path = WORKSPACE_DIR  # Primary working directory for tools
    NEXUS_HOME: Path = NEXUS_HOME
    ENV_PATH: Path = ENV_PATH

    # Persona & Skills paths
    SOUL_PATH: Path = (
        WORKSPACE_DIR / "SOUL.md"
        if (WORKSPACE_DIR / "SOUL.md").exists()
        else (
            NEXUS_HOME / "SOUL.md"
            if (NEXUS_HOME / "SOUL.md").exists()
            else CODEBASE_DIR / "SOUL.md"
        )
    )
    SKILLS_DIR: Path = (
        WORKSPACE_DIR / ".skills"
        if (WORKSPACE_DIR / ".skills").exists()
        else (
            NEXUS_HOME / "skills"
            if (NEXUS_HOME / "skills").exists()
            else CODEBASE_DIR / ".skills"
        )
    )

    # API and Model
    API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    API_BASE: str = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    MODEL: str = os.getenv("NEXUS_MODEL", "anthropic/claude-3.5-sonnet")
    TEMPERATURE: float = float(os.getenv("NEXUS_TEMPERATURE", "0.7"))
    MAX_STEPS: int = int(os.getenv("NEXUS_MAX_STEPS", "25"))

    # Storage (Global persistent memory in ~/.nexus/nexus_memory.db by default)
    _default_db = (
        NEXUS_HOME / "nexus_memory.db"
        if NEXUS_HOME.exists()
        else CODEBASE_DIR / "nexus_memory.db"
    )
    MEMORY_DB_PATH: Path = Path(os.getenv("NEXUS_MEMORY_DB", str(_default_db)))
    AUTO_APPROVE: bool = os.getenv("NEXUS_AUTO_APPROVE", "false").lower() in ("true", "1", "yes")

config = Config()
