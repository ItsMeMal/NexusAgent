import os
from pathlib import Path
from typing import Dict, Any
from .base import Tool
from ..security import SecurityGuard

def get_filesystem_tools(root_dir: Path):
    def read_file(path: str, start_line: int = 1, line_count: int = 200) -> str:
        """Read content of a file with line numbers."""
        file_path = (root_dir / path).resolve()
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
            start_idx = max(0, start_line - 1)
            end_idx = min(total_lines, start_idx + line_count)
            
            output = [f"File: {path} (Lines {start_idx + 1}-{end_idx} of {total_lines})"]
            for i in range(start_idx, end_idx):
                output.append(f"{i + 1:4d} | {lines[i].rstrip()}")
            return "\n".join(output)
        except Exception as e:
            return f"Error reading file '{path}': {str(e)}"

    def write_file(path: str, content: str) -> str:
        """Create or completely overwrite a file."""
        file_path = (root_dir / path).resolve()
        if not SecurityGuard.is_path_safe(file_path, root_dir):
            return f"Security Guard: Writing to path '{path}' is blocked (system directory restriction)."
        if SecurityGuard.is_secret_path(file_path):
            return f"Security Guard: Overwriting secret or credential file '{path}' is prohibited."

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to '{path}'."
        except Exception as e:
            return f"Error writing file '{path}': {str(e)}"

    def patch_file(path: str, target: str, replacement: str) -> str:
        """Replace an exact string target in a file with replacement."""
        file_path = (root_dir / path).resolve()
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
            new_content = content.replace(target, replacement)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"Successfully patched '{path}' ({occurrences} occurrence(s) replaced)."
        except Exception as e:
            return f"Error patching file '{path}': {str(e)}"

    def list_dir(path: str = ".") -> str:
        """List files and folders in a directory."""
        dir_path = (root_dir / path).resolve()
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
        dir_path = (root_dir / path).resolve()
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
            description="Create or overwrite a file with full content.",
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
            name="patch_file",
            description="Perform a surgical replacement of exact target text with replacement text in a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "target": {"type": "string", "description": "Exact text to be replaced"},
                    "replacement": {"type": "string", "description": "Replacement text"}
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
