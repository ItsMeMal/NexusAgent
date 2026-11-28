import json
import os
from pathlib import Path
from typing import List

from .base import Tool


_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", ".next", ".nuxt", "dist",
    "build", "out", "coverage", ".gradle", "target", "vendor",
}
_SECRET_NAMES = {".env", ".env.local", ".env.production", ".env.development"}


def _read_text(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, UnicodeError):
        return ""


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _project_tree(root: Path, max_files: int = 120, max_depth: int = 3) -> List[str]:
    entries: List[str] = []
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        dirs[:] = sorted(
            d for d in dirs
            if d not in _IGNORED_DIRS and not d.startswith(".cache")
        )
        if depth >= max_depth:
            dirs[:] = []
        for name in sorted(files):
            if name in _SECRET_NAMES or name.startswith(".env."):
                continue
            path = current_path / name
            entries.append(_safe_relative(path, root))
            if len(entries) >= max_files:
                entries.append("... (file listing capped)")
                return entries
    return entries


def inspect_project(root_dir: Path) -> str:
    """Build a bounded, secret-safe overview of the current project before edits."""
    root = Path(root_dir).resolve()
    if not root.exists() or not root.is_dir():
        return f"Project root is not a directory: {root}"

    lines = [
        f"Project root: {root}",
        f"Project state: {'non-empty' if any(root.iterdir()) else 'empty'}",
    ]

    tree = _project_tree(root)
    lines.append("\n## Workspace file tree (depth <= 3)")
    lines.extend(f"- {item}" for item in tree) if tree else lines.append("- (empty)")

    instruction_files = sorted(
        p for p in root.rglob("AGENTS.md")
        if len(p.relative_to(root).parts) <= 4
        and not any(part in _IGNORED_DIRS for part in p.parts)
    )
    lines.append("\n## Repository instructions")
    if instruction_files:
        for path in instruction_files[:8]:
            snippet = _read_text(path, 3500).strip()
            lines.append(f"### {_safe_relative(path, root)}")
            lines.append(snippet or "(file is empty or unreadable)")
    else:
        lines.append("- No AGENTS.md files found.")

    package_json = root / "package.json"
    if package_json.is_file():
        lines.append("\n## package.json")
        try:
            package = json.loads(_read_text(package_json, 120000))
            lines.append(f"- name: {package.get('name', '(unnamed)')}")
            lines.append(f"- package manager: {package.get('packageManager', '(not declared)')}")
            scripts = package.get("scripts") or {}
            if scripts:
                lines.append("- scripts:")
                lines.extend(f"  - {name}: {command}" for name, command in list(scripts.items())[:30])
            else:
                lines.append("- scripts: (none)")
            for group in ("dependencies", "devDependencies"):
                deps = package.get(group) or {}
                if deps:
                    names = ", ".join(list(deps.keys())[:35])
                    lines.append(f"- {group}: {names}")
        except (ValueError, AttributeError) as exc:
            lines.append(f"- Could not parse package.json: {exc}")

    manifest_names = (
        "pyproject.toml", "requirements.txt", "Pipfile", "uv.lock", "poetry.lock",
        "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
        "settings.gradle", "settings.gradle.kts", "Gemfile", "composer.json",
        "schema.prisma", "next.config.js", "next.config.ts", "vite.config.ts",
    )
    lines.append("\n## Other project manifests and configs")
    found = False
    for name in manifest_names:
        path = root / name
        if not path.is_file():
            continue
        found = True
        lines.append(f"### {name}")
        if name.endswith(".lock") or name in {"uv.lock", "poetry.lock"}:
            lines.append("(lockfile present; contents intentionally omitted)")
        else:
            snippet = _read_text(path, 2200).strip()
            lines.append(snippet or "(empty or unreadable)")
    if not found:
        lines.append("- No common project manifests found.")

    readme = root / "README.md"
    if readme.is_file():
        lines.append("\n## README.md (opening context)")
        lines.append(_read_text(readme, 2600).strip())

    commands: List[str] = []
    if package_json.is_file():
        try:
            scripts = json.loads(_read_text(package_json, 120000)).get("scripts") or {}
            for key in ("lint", "typecheck", "check", "test", "build"):
                if key in scripts:
                    commands.append(f"npm run {key}")
        except (ValueError, AttributeError):
            pass
        if (root / "pnpm-lock.yaml").exists():
            commands = [c.replace("npm run ", "pnpm ") for c in commands]
        elif (root / "yarn.lock").exists():
            commands = [c.replace("npm run ", "yarn ") for c in commands]
        elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            commands = [c.replace("npm run ", "bun run ") for c in commands]
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        commands.extend(["python -m compileall -q .", "python -m unittest discover -s tests"])
    if (root / "Cargo.toml").exists():
        commands.extend(["cargo check", "cargo test", "cargo clippy --all-targets --all-features"])
    if (root / "go.mod").exists():
        commands.extend(["go test ./...", "go vet ./..."])
    if commands:
        lines.append("\n## Candidate verification commands (confirm availability before running)")
        lines.extend(f"- {command}" for command in dict.fromkeys(commands))

    report = "\n".join(lines)
    if len(report) > 14000:
        report = report[:13500] + "\n... (project inspection output capped)"
    return report


def get_project_tools(root_dir: Path):
    def _inspect_project() -> str:
        return inspect_project(root_dir)

    return [
        Tool(
            name="inspect_project",
            description=(
                "Inspect the current workspace before coding. Returns a bounded file tree, AGENTS.md instructions, "
                "project manifests, package scripts, and candidate verification commands. Secret files such as .env "
                "are excluded. Call this before creating or modifying project files."
            ),
            parameters={"type": "object", "properties": {}},
            handler=_inspect_project,
        )
    ]
