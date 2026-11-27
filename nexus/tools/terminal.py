import asyncio
import shlex
from pathlib import Path
from typing import Dict, Any, Optional
from .base import Tool
from ..config import config
from ..security import SecurityGuard, RiskLevel


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
    async def run_command(command: str, timeout: int = 120, backend: str = "") -> str:
        """Run a shell command asynchronously in local, docker, or ssh execution backend."""
        # Security Guardrail Check
        risk_level, reason = SecurityGuard.assess_command_risk(command)
        if risk_level == RiskLevel.DANGEROUS:
            return f"Blocked by Security Guard: Command '{command}' is classified as DANGEROUS ({reason}). Execution prevented for system safety."

        eff_cmd, cfg_err = build_sandboxed_command(command, root_dir, backend=backend or None)
        if cfg_err:
            return cfg_err

        try:
            # Run command using shell
            process = await asyncio.create_subprocess_shell(
                eff_cmd,
                cwd=str(root_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=float(timeout)
                )
            except asyncio.CancelledError:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
                raise
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                return f"Error: Command timed out after {timeout} seconds."

            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            exit_code = process.returncode

            result_lines = [f"Exit Code: {exit_code}"]
            if stdout:
                result_lines.append(f"STDOUT:\n{stdout}")
            if stderr:
                result_lines.append(f"STDERR:\n{stderr}")
            if not stdout and not stderr:
                result_lines.append("(Command produced no output)")

            # Limit total output length to avoid context overflow
            res = "\n".join(result_lines)
            if len(res) > 4000:
                res = res[:4000] + "\n...[Output truncated]"
            return res
        except Exception as e:
            return f"Error running command '{command}': {str(e)}"
        finally:
            try:
                if "process" in locals() and getattr(process, "_transport", None) is not None:
                    process._transport.close()
            except Exception:
                pass

    return [
        Tool(
            name="run_command",
            description="Execute a shell command in the project workspace (supports local, docker, or ssh sandbox backends).",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The exact shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)", "default": 120},
                    "backend": {"type": "string", "enum": ["", "local", "docker", "ssh"], "description": "Optional backend override", "default": ""}
                },
                "required": ["command"]
            },
            handler=run_command
        )
    ]
