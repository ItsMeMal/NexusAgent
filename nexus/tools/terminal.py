import asyncio
from pathlib import Path
from typing import Dict, Any
from .base import Tool
from ..security import SecurityGuard, RiskLevel

def get_terminal_tools(root_dir: Path):
    async def run_command(command: str, timeout: int = 120) -> str:
        """Run a shell command asynchronously in the project directory."""
        # Security Guardrail Check
        risk_level, reason = SecurityGuard.assess_command_risk(command)
        if risk_level == RiskLevel.DANGEROUS:
            return f"Blocked by Security Guard: Command '{command}' is classified as DANGEROUS ({reason}). Execution prevented for system safety."

        try:
            # Run command using shell
            process = await asyncio.create_subprocess_shell(
                command,
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

    return [
        Tool(
            name="run_command",
            description="Execute a bash/powershell command in the project root directory.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The exact shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)", "default": 120}
                },
                "required": ["command"]
            },
            handler=run_command
        )
    ]
