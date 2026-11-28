import os
import sys
import json
import time
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
from .config import config

REPO_API_URL = "https://api.github.com/repos/ItsMeMal/NolthiraAgent/commits/main"
CACHE_FILE = config.NEXUS_HOME / ".update_cache.json"

def get_local_commit(engine_dir: Optional[Path] = None) -> Optional[str]:
    """Retrieve current local Git commit SHA."""
    target_dir = engine_dir or config.CODEBASE_DIR
    try:
        res = subprocess.run(
            ["git", "-C", str(target_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3.0
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None

async def check_for_update(force: bool = False) -> Optional[Dict[str, Any]]:
    """Check GitHub repository for newer commits with 1-hour caching."""
    local_sha = get_local_commit()
    if not local_sha:
        return None

    now = time.time()
    if not force and CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if now - cached.get("timestamp", 0) < 3600:  # 1 hour TTL
                if cached.get("update_available") and cached.get("remote_sha") != local_sha:
                    return cached
                elif not cached.get("update_available") and cached.get("remote_sha") == local_sha:
                    return None
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=3.5, headers={"User-Agent": "Nolthira-CLI"}) as client:
            resp = await client.get(REPO_API_URL)
            if resp.status_code != 200:
                return None
            data = resp.json()
            remote_sha = data.get("sha", "")
            commit_info = data.get("commit", {})
            message = commit_info.get("message", "").splitlines()[0] if commit_info.get("message") else "New update available"

            if not remote_sha or remote_sha == local_sha:
                try:
                    CACHE_FILE.write_text(json.dumps({
                        "timestamp": now,
                        "local_sha": local_sha,
                        "remote_sha": remote_sha,
                        "update_available": False
                    }), encoding="utf-8")
                except Exception:
                    pass
                return None

            update_info = {
                "timestamp": now,
                "local_sha": local_sha[:7],
                "remote_sha": remote_sha[:7],
                "full_remote_sha": remote_sha,
                "message": message,
                "update_available": True
            }

            try:
                CACHE_FILE.write_text(json.dumps(update_info), encoding="utf-8")
            except Exception:
                pass

            return update_info
    except Exception:
        return None

async def perform_update(console: Any) -> bool:
    """Execute live engine update via git pull, dependency refresh, and workspace pruning."""
    engine_dir = config.NEXUS_HOME / "engine"
    if not (engine_dir / ".git").exists():
        engine_dir = config.CODEBASE_DIR

    if not (engine_dir / ".git").exists():
        console.print("\n  [bold red]Error:[/bold red] Git repository metadata (.git) not found in engine directory.")
        console.print(f"  Expected location: {engine_dir}\n")
        return False

    console.print("\n  [bold #00ffd7]⚡ Updating Nolthira Agent Engine...[/bold #00ffd7]\n")

    # Step 1: Discard any local modifications in engine tracked files and pull
    console.print("  [dim]⠋ Fetching and merging latest changes from GitHub...[/dim]")
    try:
        subprocess.run(["git", "-C", str(engine_dir), "checkout", "--", "."], capture_output=True, timeout=5)
        res_pull = subprocess.run(["git", "-C", str(engine_dir), "pull", "origin", "main"], capture_output=True, text=True, timeout=30)
        if res_pull.returncode != 0:
            console.print(f"  [bold red]Git pull failed:[/bold red] {res_pull.stderr.strip()}")
            return False
        console.print("  [bold #22c55e]✔[/bold #22c55e] Git repository updated successfully.")
    except Exception as e:
        console.print(f"  [bold red]Error pulling updates:[/bold red] {str(e)}")
        return False

    # Step 2: Prune non-engine assets so ~/.nexus/engine stays clean (only in installed engine, not git repo)
    if engine_dir == config.NEXUS_HOME / "engine":
        prune_targets = ["website", "tests", "install.sh", "install.ps1", "wrangler.toml"]
        for t in prune_targets:
            p = engine_dir / t
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
        console.print("  [bold #22c55e]✔[/bold #22c55e] Engine runtime workspace cleaned and pruned.")

    # Step 3: Refresh Python dependencies
    console.print("  [dim]⠋ Synchronizing dependencies (requirements.txt)...[/dim]")
    req_file = engine_dir / "requirements.txt"
    if req_file.exists():
        venv_python = (
            config.NEXUS_HOME / "venv" / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else config.NEXUS_HOME / "venv" / "bin" / "python"
        )
        py_exec = str(venv_python) if venv_python.exists() else sys.executable
        try:
            subprocess.run([py_exec, "-m", "pip", "install", "-r", str(req_file), "--quiet"], capture_output=True, timeout=45)
            console.print("  [bold #22c55e]✔[/bold #22c55e] Dependencies successfully synchronized.")
        except Exception as e:
            console.print(f"  [dim yellow]Warning updating dependencies: {e}[/dim yellow]")

    # Step 4: Clear update cache
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    new_sha = get_local_commit(engine_dir) or "latest"
    console.print(f"\n  [bold #22c55e]✨ Nolthira Agent has been successfully updated to [{new_sha[:7]}]![/bold #22c55e]")
    console.print("  [dim]Please restart your Nexus session to load the updated engine.[/dim]\n")
    return True
