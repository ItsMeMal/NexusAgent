import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Any
from dotenv import set_key
from .base import Tool
from ..security import SecurityGuard

def _resolve_workspace_path(root_dir: Path, raw_path: str) -> Path:
    """Resolve user/LLM path against root_dir without letting leading '/' escape to drive root."""
    p = (raw_path or "").strip()
    if p.startswith("/") and not p.startswith("//"):
        # On Windows /index.html drops subpath under root_dir; on POSIX only keep true abs paths that already exist under root or /tmp
        stripped = p.lstrip("/")
        if os.name == "nt" or not Path(p).exists():
            p = stripped or "."
    return (root_dir / p).resolve()


def _atomic_write_text(file_path: Path, content: str) -> None:
    """Write a complete file through a same-directory temporary file and atomic replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = None
    try:
        if file_path.exists():
            existing_mode = file_path.stat().st_mode & 0o777
    except OSError:
        existing_mode = None

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{file_path.name}.",
        suffix=".tmp",
        dir=str(file_path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, existing_mode if existing_mode is not None else 0o644)
        os.replace(temp_path, file_path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _safe_read_range(value: Any, default: int, maximum: int) -> int:
    """Coerce model-generated integer strings safely and clamp untrusted file ranges."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        try:
            parsed = int(value.strip())
        except ValueError:
            return default
    else:
        return default
    return max(1, min(parsed, maximum))


def get_filesystem_tools(root_dir: Path):
    def read_file(path: str, start_line: int = 1, line_count: int = 200) -> str:
        """Read file content with type-safe, bounded line ranges."""
        start_line = _safe_read_range(start_line, default=1, maximum=10_000_000)
        line_count = _safe_read_range(line_count, default=200, maximum=2000)
        file_path = _resolve_workspace_path(root_dir, path)
        if not SecurityGuard.is_path_safe(file_path, root_dir):
            return f"Security Guard: Access to path '{path}' is blocked (system directory restriction)."
        if SecurityGuard.is_secret_path(file_path):
            return f"Security Guard: Access to '{path}' is blocked. Direct reading of secret credentials, private keys, or .env files is prohibited for security."

        if not file_path.exists():
            return f"Error: File '{path}' does not exist."
        if file_path.is_dir():
            return f"Error: '{path}' is a directory."
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            
            total_lines = len(lines)
            start_idx = min(total_lines, max(0, start_line - 1))
            end_idx = min(total_lines, start_idx + line_count)
            if start_idx >= total_lines:
                return f"File: {path} (Lines {total_lines + 1}-{total_lines} of {total_lines})\n(No lines in requested range)"

            output = [f"File: {path} (Lines {start_idx + 1}-{end_idx} of {total_lines})"]
            for i in range(start_idx, end_idx):
                output.append(f"{i + 1:4d} | {lines[i].rstrip()}")
            return "\n".join(output)
        except Exception as e:
            return f"Error reading file '{path}': {str(e)}"

    def write_file(path: str, content: str) -> str:
        """Create or completely overwrite a file."""
        file_path = _resolve_workspace_path(root_dir, path)
        if not SecurityGuard.is_path_safe(file_path, root_dir):
            return f"Security Guard: Writing to path '{path}' is blocked (system directory restriction)."
        if SecurityGuard.is_secret_path(file_path):
            return f"Security Guard: Overwriting secret or credential file '{path}' is prohibited."

        try:
            _atomic_write_text(file_path, content)
            return f"Successfully wrote {len(content)} characters atomically to '{path}'."
        except Exception as e:
            return f"Error writing file '{path}': {str(e)}"

    def update_env(path: str = ".env", updates: Dict[str, str] = None) -> str:
        """Safely update selected root-level dotenv keys without exposing existing secret values."""
        values = updates or {}
        if not isinstance(values, dict) or not values:
            return "Error: 'updates' must be a non-empty object of environment variable names and string values."

        file_path = _resolve_workspace_path(root_dir, path)
        workspace_root = root_dir.resolve()
        if not SecurityGuard.is_path_safe(file_path, root_dir):
            return f"Security Guard: Updating environment path '{path}' is blocked."
        if file_path.parent != workspace_root:
            return "Security Guard: Environment updates are restricted to dotenv files at the workspace root."
        if file_path.name == ".env.example" or not re.fullmatch(r"\.env(?:\.[A-Za-z0-9_-]+)*", file_path.name):
            return "Security Guard: update_env only supports root-level .env files (not .env.example)."

        invalid_keys = [
            str(key) for key in values
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        ]
        if invalid_keys:
            return "Error: Invalid environment variable name(s): " + ", ".join(invalid_keys[:8])

        invalid_values = [
            key for key, value in values.items()
            if not isinstance(value, str) or "\x00" in value or "\r" in value or "\n" in value
        ]
        if invalid_values:
            return "Error: Environment values must be single-line strings without NUL characters. Rejected keys: " + ", ".join(invalid_values[:8])

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            updated_keys = []
            for key, value in values.items():
                success, _, _ = set_key(
                    str(file_path),
                    key,
                    value,
                    quote_mode="always",
                    export=False,
                )
                if not success:
                    return f"Error: Could not safely update environment key '{key}'."
                # Child processes launched by Nolthira inherit the updated value immediately.
                os.environ[key] = value
                updated_keys.append(key)
            return (
                f"Successfully updated {len(updated_keys)} environment variable(s) in '{path}': "
                + ", ".join(sorted(updated_keys))
                + ". Existing values were not read or returned."
            )
        except Exception as e:
            return f"Error updating environment file '{path}': {type(e).__name__}: {e}"

    def append_file(path: str, content: str) -> str:
        """Append content to an existing file (or create if missing) for chunked writing of large files."""
        file_path = _resolve_workspace_path(root_dir, path)
        if not SecurityGuard.is_path_safe(file_path, root_dir):
            return f"Security Guard: Appending to path '{path}' is blocked (system directory restriction)."
        if SecurityGuard.is_secret_path(file_path):
            return f"Security Guard: Modifying secret credential file '{path}' is prohibited."

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully appended {len(content)} characters to '{path}'."
        except Exception as e:
            return f"Error appending to file '{path}': {str(e)}"

    def patch_file(path: str, target: str, replacement: str, replace_all: bool = False) -> str:
        """Replace an exact string target in a file with replacement."""
        file_path = _resolve_workspace_path(root_dir, path)
        if not SecurityGuard.is_path_safe(file_path, root_dir):
            return f"Security Guard: Patching path '{path}' is blocked (system directory restriction)."
        if SecurityGuard.is_secret_path(file_path):
            return f"Security Guard: Modifying secret credential file '{path}' is prohibited."

        if not file_path.exists():
            return f"Error: File '{path}' does not exist."
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            if target not in content:
                return f"Error: Target text not found in '{path}'. Make sure whitespace and characters match exactly."
            
            occurrences = content.count(target)
            if occurrences != 1 and not replace_all:
                return (
                    f"Error: Patch target in '{path}' matched {occurrences} times; no changes made. "
                    "Make the target more specific or pass replace_all=true when every match should change."
                )
            new_content = content.replace(target, replacement) if replace_all else content.replace(target, replacement, 1)
            _atomic_write_text(file_path, new_content)
            return f"Successfully patched '{path}' ({occurrences if replace_all else 1} occurrence(s) replaced)."
        except Exception as e:
            return f"Error patching file '{path}': {str(e)}"

    def list_dir(path: str = ".") -> str:
        """List files and folders in a directory."""
        dir_path = _resolve_workspace_path(root_dir, path)
        if not dir_path.exists():
            return f"Error: Directory '{path}' does not exist."
        if not dir_path.is_dir():
            return f"Error: '{path}' is not a directory."
        try:
            items = []
            for item in sorted(dir_path.iterdir()):
                rel = item.relative_to(root_dir)
                prefix = "[DIR] " if item.is_dir() else "[FILE]"
                items.append(f"{prefix} {rel.as_posix()}")
            if not items:
                return f"Directory '{path}' is empty."
            return "\n".join(items[:150])
        except Exception as e:
            return f"Error listing directory '{path}': {str(e)}"

    def search_files(query: str, path: str = ".", max_results: int = 40) -> str:
        """Search for a text string or pattern across all files in workspace."""
        dir_path = _resolve_workspace_path(root_dir, path)
        if not dir_path.exists():
            return f"Error: Path '{path}' does not exist."
        matches = []
        q_lower = query.lower()
        ignore_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}

        for p in dir_path.rglob("*"):
            if p.is_file():
                if any(ignored in p.parts for ignored in ignore_dirs):
                    continue
                try:
                    rel_p = p.relative_to(root_dir)
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if q_lower in line.lower():
                                matches.append(f"{rel_p.as_posix()}:{line_num}: {line.strip()[:100]}")
                                if len(matches) >= max_results:
                                    break
                except Exception:
                    pass
            if len(matches) >= max_results:
                break

        if not matches:
            return f"No matches found for '{query}' in '{path}'."
        return "\n".join(matches)

    return [
        Tool(
            name="read_file",
            description="Read the contents of a file with line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "start_line": {"type": "integer", "description": "Line number to start reading from (1-based)", "default": 1},
                    "line_count": {"type": "integer", "description": "Number of lines to read", "default": 200}
                },
                "required": ["path"]
            },
            handler=read_file
        ),
        Tool(
            name="write_file",
            description="Create or atomically replace a non-secret file with its complete content. Direct writes to .env and credential files are blocked; use update_env for explicitly requested environment-variable changes. Do not split files into append chunks.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "content": {"type": "string", "description": "Full text content to write into the file"}
                },
                "required": ["path", "content"]
            },
            handler=write_file
        ),
        Tool(
            name="update_env",
            description=(
                "Safely set only explicitly provided environment variables in a root-level .env file. "
                "Use this when project setup requires changing DATABASE_URL, API endpoints, or other env keys. "
                "It preserves unrelated entries, never reads or returns existing secret values, and updates the "
                "current Nolthira process environment for subsequent child commands. Never bypass .env protections "
                "with PowerShell, Node, Python, shell redirection, or other terminal file-write tricks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Root-level dotenv file such as .env, .env.local, or .env.development",
                        "default": ".env",
                    },
                    "updates": {
                        "type": "object",
                        "description": "Map of environment variable names to single-line string values. Values are never echoed back.",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["updates"],
            },
            handler=update_env,
        ),
        Tool(
            name="append_file",
            description="Append text only when the requested operation is genuinely append-only (for example, a log or append-only data file). Do not use to assemble source files, schemas, manifests, or configuration.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "content": {"type": "string", "description": "Text chunk to append to the file"}
                },
                "required": ["path", "content"]
            },
            handler=append_file
        ),
        Tool(
            name="patch_file",
            description="Perform a surgical replacement of exact target text with replacement text in a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "target": {"type": "string", "description": "Exact text to be replaced"},
                    "replacement": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Set true only when intentionally replacing every exact match", "default": False}
                },
                "required": ["path", "target", "replacement"]
            },
            handler=patch_file
        ),
        Tool(
            name="list_dir",
            description="List files and directories in a given path.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list", "default": "."}
                }
            },
            handler=list_dir
        ),
        Tool(
            name="search_files",
            description="Search for exact text or keyword across files in the workspace (grep/code search).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text pattern or keyword to search for"},
                    "path": {"type": "string", "description": "Subdirectory to search in (default is workspace root '.')", "default": "."},
                    "max_results": {"type": "integer", "description": "Maximum matching lines to return", "default": 40}
                },
                "required": ["query"]
            },
            handler=search_files
        )
    ]
