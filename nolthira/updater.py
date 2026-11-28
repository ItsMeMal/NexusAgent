import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .config import config

REPO_API_URL = "https://api.github.com/repos/ItsMeMal/NolthiraAgent/commits/main"
CACHE_FILE = config.NOLTHIRA_HOME / ".update_cache.json"
CACHE_SCHEMA = 2
CACHE_TTL_SECONDS = 300
GITHUB_TIMEOUT_SECONDS = 8.0


def get_local_commit(engine_dir: Optional[Path] = None) -> Optional[str]:
    """Return the full Git commit SHA for the active engine checkout."""
    target_dir = engine_dir or config.CODEBASE_DIR
    try:
        result = subprocess.run(
            ["git", "-C", str(target_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            return sha if len(sha) >= 40 else None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _update_payload(local_sha: str, remote_sha: str, message: str) -> Dict[str, Any]:
    """Build the UI payload while retaining full hashes for comparisons/cache."""
    return {
        "local_sha": local_sha[:7],
        "remote_sha": remote_sha[:7],
        "full_local_sha": local_sha,
        "full_remote_sha": remote_sha,
        "message": message,
        "update_available": remote_sha != local_sha,
    }


def _read_update_cache(local_sha: str, now: float) -> tuple[bool, Optional[Dict[str, Any]]]:
    """Return (cache_hit, update_payload); invalid/old cache entries are ignored."""
    if not CACHE_FILE.is_file():
        return False, None
    try:
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if cached.get("schema") != CACHE_SCHEMA:
            return False, None
        if cached.get("local_sha") != local_sha:
            return False, None
        if now - float(cached.get("timestamp", 0)) >= CACHE_TTL_SECONDS:
            return False, None
        remote_sha = cached.get("remote_sha")
        if not isinstance(remote_sha, str) or len(remote_sha) < 40:
            return False, None
        if remote_sha == local_sha:
            return True, None
        if not cached.get("update_available"):
            return False, None
        message = str(cached.get("message") or "New update available")
        return True, _update_payload(local_sha, remote_sha, message)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False, None


def _write_update_cache(local_sha: str, remote_sha: str, message: str, now: float) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps({
                "schema": CACHE_SCHEMA,
                "timestamp": now,
                "local_sha": local_sha,
                "remote_sha": remote_sha,
                "message": message,
                "update_available": remote_sha != local_sha,
            }),
            encoding="utf-8",
        )
    except OSError:
        # Update checks should never prevent the CLI from starting.
        pass


async def check_for_update(force: bool = False) -> Optional[Dict[str, Any]]:
    """Compare the local engine commit with GitHub main using full SHAs."""
    local_sha = get_local_commit()
    if not local_sha:
        return {
            "update_available": False,
            "check_error": f"Git metadata was not found in {config.CODEBASE_DIR}.",
        }

    now = time.time()
    if not force:
        cache_hit, cached_payload = _read_update_cache(local_sha, now)
        if cache_hit:
            return cached_payload

    try:
        async with httpx.AsyncClient(
            timeout=GITHUB_TIMEOUT_SECONDS,
            headers={
                "User-Agent": "Nolthira-Agent",
                "Accept": "application/vnd.github+json",
            },
        ) as client:
            response = await client.get(REPO_API_URL)
        if response.status_code != 200:
            return {
                "update_available": False,
                "check_error": f"GitHub returned HTTP {response.status_code}.",
            }

        data = response.json()
        remote_sha = str(data.get("sha") or "")
        if len(remote_sha) < 40:
            return {
                "update_available": False,
                "check_error": "GitHub response did not contain a valid commit SHA.",
            }

        commit = data.get("commit") or {}
        raw_message = str(commit.get("message") or "New update available")
        message = raw_message.splitlines()[0]
        _write_update_cache(local_sha, remote_sha, message, now)

        if remote_sha == local_sha:
            return None
        return _update_payload(local_sha, remote_sha, message)

    except (httpx.HTTPError, ValueError, OSError) as exc:
        return {
            "update_available": False,
            "check_error": f"Could not reach GitHub: {exc.__class__.__name__}.",
        }


async def perform_update(console: Any) -> bool:
    """Fast-forward the engine checkout and refresh its Python dependencies."""
    engine_dir = config.NOLTHIRA_HOME / "engine"
    if not (engine_dir / ".git").exists():
        engine_dir = config.CODEBASE_DIR

    if not (engine_dir / ".git").exists():
        console.print(
            "\n  [bold red]Update failed:[/bold red] Git repository metadata was not found."
        )
        console.print(f"  Expected location: {engine_dir}\n")
        return False

    console.print("\n  [bold #00ffd7]⚡ Updating Nolthira Agent Engine...[/bold #00ffd7]\n")
    try:
        status = subprocess.run(
            ["git", "-C", str(engine_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if status.returncode != 0:
            console.print(f"  [bold red]Git status failed:[/bold red] {status.stderr.strip()}")
            return False
        if status.stdout.strip():
            console.print(
                "  [yellow]Update stopped: local engine changes were detected. "
                "Commit or stash them before updating; nothing was discarded.[/yellow]\n"
            )
            return False

        console.print("  [dim]⠋ Fetching latest changes from GitHub...[/dim]")
        fetch = subprocess.run(
            ["git", "-C", str(engine_dir), "fetch", "origin", "main", "--quiet"],
            capture_output=True,
            text=True,
            timeout=45.0,
            check=False,
        )
        if fetch.returncode != 0:
            console.print(f"  [bold red]Git fetch failed:[/bold red] {fetch.stderr.strip()}")
            return False

        pull = subprocess.run(
            ["git", "-C", str(engine_dir), "merge", "--ff-only", "FETCH_HEAD"],
            capture_output=True,
            text=True,
            timeout=45.0,
            check=False,
        )
        if pull.returncode != 0:
            console.print(f"  [bold red]Fast-forward update failed:[/bold red] {pull.stderr.strip()}")
            return False
        console.print("  [bold #22c55e]✔[/bold #22c55e] Git repository updated successfully.")

    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"  [bold red]Update failed:[/bold red] {exc}")
        return False

    if engine_dir == config.NOLTHIRA_HOME / "engine":
        for target in ("website", "tests", "install.sh", "install.ps1", "wrangler.toml"):
            path = engine_dir / target
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        console.print("  [bold #22c55e]✔[/bold #22c55e] Engine runtime workspace cleaned.")

    requirements = engine_dir / "requirements.txt"
    if requirements.is_file():
        venv_python = (
            config.NOLTHIRA_HOME / "venv" / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else config.NOLTHIRA_HOME / "venv" / "bin" / "python"
        )
        python_executable = str(venv_python) if venv_python.exists() else sys.executable
        try:
            sync = subprocess.run(
                [python_executable, "-m", "pip", "install", "-r", str(requirements), "--quiet"],
                capture_output=True,
                text=True,
                timeout=90.0,
                check=False,
            )
            if sync.returncode == 0:
                console.print("  [bold #22c55e]✔[/bold #22c55e] Dependencies synchronized.")
            else:
                console.print(
                    f"  [yellow]Dependency refresh warning:[/yellow] {sync.stderr.strip()[-600:]}"
                )
        except (OSError, subprocess.SubprocessError) as exc:
            console.print(f"  [yellow]Dependency refresh warning:[/yellow] {exc}")

    try:
        CACHE_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    new_sha = get_local_commit(engine_dir) or "latest"
    console.print(
        f"\n  [bold #22c55e]✨ Nolthira Agent updated to [{new_sha[:7]}].[/bold #22c55e]"
    )
    console.print("  [dim]Restart Nolthira to load the updated engine.[/dim]\n")
    return True
