import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

# Suppress noisy runtime and resource warnings from third-party libraries and async runtimes
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Codebase root where Nexus Agent is installed
CODEBASE_DIR = Path(__file__).resolve().parent.parent

# Current working directory where user invoked the command
WORKSPACE_DIR = Path.cwd()

# Load .env: check current workspace first, then codebase directory
if (WORKSPACE_DIR / ".env").exists():
    load_dotenv(WORKSPACE_DIR / ".env")
else:
    load_dotenv(CODEBASE_DIR / ".env")

class Config:
    CODEBASE_DIR: Path = CODEBASE_DIR
    WORKSPACE_DIR: Path = WORKSPACE_DIR
    ROOT_DIR: Path = WORKSPACE_DIR  # Primary working directory for tools

    # Persona & Skills paths
    SOUL_PATH: Path = (
        WORKSPACE_DIR / "SOUL.md"
        if (WORKSPACE_DIR / "SOUL.md").exists()
        else CODEBASE_DIR / "SOUL.md"
    )
    SKILLS_DIR: Path = (
        WORKSPACE_DIR / ".skills"
        if (WORKSPACE_DIR / ".skills").exists()
        else CODEBASE_DIR / ".skills"
    )

    # API and Model
    API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    API_BASE: str = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    MODEL: str = os.getenv("NEXUS_MODEL", "anthropic/claude-3.5-sonnet")
    TEMPERATURE: float = float(os.getenv("NEXUS_TEMPERATURE", "0.7"))
    MAX_STEPS: int = int(os.getenv("NEXUS_MAX_STEPS", "25"))

    # Storage (store centrally in CODEBASE_DIR by default so memory persists globally)
    MEMORY_DB_PATH: Path = CODEBASE_DIR / os.getenv("NEXUS_MEMORY_DB", "nexus_memory.db")
    AUTO_APPROVE: bool = os.getenv("NEXUS_AUTO_APPROVE", "false").lower() in ("true", "1", "yes")

config = Config()
