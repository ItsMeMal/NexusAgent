import asyncio
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from .base import Tool
from ..config import config
from ..security import SecurityGuard, RiskLevel
from .processes import ProcessManager

_SLOW_CMD_RE = re.compile(
    r"\b(?:npm\s+(?:install|i|ci|update|rebuild)|pnpm\s+(?:install|i|add)|yarn\s+(?:install|add)|"
    r"bun\s+(?:install|add)|npx\s+create-|pip\s+install|uv\s+pip\s+install|cargo\s+(?:build|test)|"
    r"next\s+build|docker\s+build|playwright\s+install|prisma\s+generate)\b",
    re.IGNORECASE,
)


def compute_effective_timeout(command: str, requested_timeout: int) -> int:
    """Resolve safe command timeout, auto-extending slow package installs/builds when default is used."""
    base = max(5, min(int(requested_timeout or 120), 900))
    if base <= 120 and _SLOW_CMD_RE.search(command or ""):
        return 300
    return base


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Force-terminate the subprocess and all spawned child processes (fixes Windows npm/node file locks)."""
    pid = getattr(process, "pid", None)
    if pid is None:
        return
    try:
        if sys.platform == "win32":
            # taskkill /F /T /PID kills cmd.exe and any child npm/node/powershell processes
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=3.0)
    except Exception:
        pass


def build_sandboxed_command(command: str, root_dir: Path, backend: Optional[str] = None) -> tuple[str, Optional[str]]:
    """
    Wrap command for configured execution backend ('local' | 'docker' | 'ssh').
    Returns (effective_shell_command, error_msg_if_misconfigured).
    """
    chosen = (backend or getattr(config, "EXEC_BACKEND", "local") or "local").strip().lower()
    if chosen == "docker":
        image = getattr(config, "DOCKER_IMAGE", "python:3.12-slim") or "python:3.12-slim"
        host_dir = str(root_dir.resolve())
        wrapped = (
            f'docker run --rm -v "{host_dir}:/workspace" -w /workspace '
            f"{shlex.quote(image)} sh -c {shlex.quote(command)}"
        )
        return wrapped, None
    if chosen == "ssh":
        host = getattr(config, "SSH_HOST", "").strip()
        if not host:
            return command, "Error: NEXUS_EXEC_BACKEND is 'ssh' but NEXUS_SSH_HOST is not configured."
        user = getattr(config, "SSH_USER", "").strip()
        key_path = getattr(config, "SSH_KEY_PATH", "").strip()
        target = f"{user}@{host}" if user else host
        key_flag = f"-i {shlex.quote(key_path)} " if key_path else ""
        wrapped = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {key_flag}{shlex.quote(target)} {shlex.quote(command)}"
        return wrapped, None
    return command, None


def get_terminal_tools(root_dir: Path):
    process_manager = ProcessManager(config.NEXUS_HOME / "processes")

    async def run_command(
        command: str,
        timeout: int = 120,
        backend: str = "",
        background: bool = False,
    ) -> str:
        """Run a shell command asynchronously in local, docker, or ssh execution backend."""
        # Block shell-based attempts to bypass filesystem secret-file protections.
        if SecurityGuard.is_secret_file_access_command(command):
            return (
                "Security Guard: Explicit shell/script access to .env files is blocked. "
                "Do not read or edit dotenv files through the terminal. For explicitly requested "
                "key changes, use update_env with only the required variable names and values."
            )

        # Security Guardrail Check
        risk_level, reason = SecurityGuard.assess_command_risk(command)
        if risk_level == RiskLevel.DANGEROUS:
            return f"Blocked by Security Guard: Command '{command}' is classified as DANGEROUS ({reason}). Execution prevented for system safety."

        eff_cmd, cfg_err = build_sandboxed_command(command, root_dir, backend=backend or None)
        if cfg_err:
            return cfg_err

        if background:
            # Only process sessions created by this manager can be inspected or stopped.
            return process_manager.start(eff_cmd, root_dir)

        eff_timeout = compute_effective_timeout(command, timeout)
        popen_kwargs: Dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        else:
            popen_kwargs["start_new_session"] = True

        process = None
        try:
            # Run command using shell directly in root_dir
            process = await asyncio.create_subprocess_shell(
                eff_cmd,
                cwd=str(root_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **popen_kwargs,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=float(eff_timeout)
                )
            except asyncio.CancelledError:
                await _terminate_process_tree(process)
                raise
            except asyncio.TimeoutError:
                await _terminate_process_tree(process)
                return (
                    f"Error: Command timed out after {eff_timeout} seconds (process tree terminated cleanly). "
                    "Do NOT blindly retry the exact same command; for slow package installs pass timeout=360 with "
                    "non-interactive flags (e.g. '--no-audit --no-fund --prefer-offline') or inspect existing files/locks first."
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            exit_code = process.returncode

            result_lines = [f"Exit Code: {exit_code}"]
            if exit_code != 0:
                result_lines.insert(0, f"[COMMAND FAILED: exit code {exit_code}. Do not continue dependent work until this failure is diagnosed and resolved.]")
            if stdout:
                result_lines.append(f"STDOUT:\n{stdout}")
            if stderr:
                result_lines.append(f"STDERR:\n{stderr}")
            if not stdout and not stderr:
                result_lines.append("(Command produced no output)")

            # Preserve both the command's beginning and its final diagnostic lines.
            res = "\n".join(result_lines)
            if len(res) > 4000:
                res = res[:2400] + "\n...[middle output truncated]...\n" + res[-1450:]
            return res
        except Exception as e:
            return f"Error running command '{command}': {str(e)}"
        finally:
            try:
                if process is not None and getattr(process, "_transport", None) is not None:
                    process._transport.close()
            except Exception:
                pass

    async def manage_process(
        action: str,
        session_id: str = "",
        timeout: int = 30,
        data: str = "",
        limit: int = 24000,
    ):
        """Inspect or control a background process started by this terminal tool."""
        selected = (action or "").strip().lower()
        if selected == "list":
            return process_manager.list()
        if not session_id:
            return {"error": "session_id is required for this process action."}
        if selected == "poll":
            return process_manager.poll(session_id)
        if selected == "log":
            return process_manager.log(session_id, limit=limit)
        if selected == "wait":
            return await asyncio.to_thread(process_manager.wait, session_id, timeout)
        if selected == "kill":
            return await asyncio.to_thread(process_manager.kill, session_id)
        if selected == "write":
            return process_manager.write(session_id, data)
        return {"error": "Unknown action. Use list, poll, log, wait, kill, or write."}

    return [
        Tool(
            name="run_command",
            description=(
                f"Execute a shell command directly in workspace root ({root_dir}); do NOT prefix 'cd <workspace> &&'. "
                "Explicit shell/script reads or writes of .env files are blocked; use update_env for targeted configuration changes. "
                "Supports local, docker, or ssh backends; slow installs/builds auto-extend from 120s to 300s (max 900s). "
                "Set background=true for a long-running server/build/test and manage the returned session_id with process."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The exact shell command to execute (already in workspace root)"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120; auto-extended to 300 for installs/builds, max 900; ignored for background runs)", "default": 120},
                    "backend": {"type": "string", "enum": ["", "local", "docker", "ssh"], "description": "Optional backend override", "default": ""},
                    "background": {"type": "boolean", "description": "Start a tracked background process instead of waiting for completion", "default": False}
                },
                "required": ["command"]
            },
            handler=run_command
        ),
        Tool(
            name="process",
            description=(
                "Manage background commands started with run_command(background=true). "
                "Actions: list, poll, log, wait, kill, write. Use the returned session_id; "
                "arbitrary system PIDs cannot be managed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "poll", "log", "wait", "kill", "write"]},
                    "session_id": {"type": "string", "description": "ID returned by run_command(background=true)"},
                    "timeout": {"type": "integer", "description": "Maximum wait duration in seconds (1-300)", "default": 30},
                    "data": {"type": "string", "description": "Text sent to process stdin for action='write'"},
                    "limit": {"type": "integer", "description": "Maximum output bytes for action='log'", "default": 24000}
                },
                "required": ["action"]
            },
            handler=manage_process
        )
    ]
