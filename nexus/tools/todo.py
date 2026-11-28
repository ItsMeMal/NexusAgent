"""Session-scoped task planning tools for long-running agent work."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


_VALID_STATUSES = {"pending", "in_progress", "blocked", "completed"}
_VALID_PRIORITIES = {"low", "normal", "high"}
_MAX_TASKS = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TodoStore:
    """Persist a bounded task list separately for each agent conversation."""

    def __init__(self, directory: Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            if os.name != "nt":
                os.chmod(self.directory, 0o700)
        except OSError:
            pass
        self._lock = threading.RLock()

    def _path_for(self, session_id: str) -> Path:
        normalized = str(session_id or "").strip()
        if not normalized or len(normalized) > 256:
            raise ValueError("A valid session identifier is required.")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.json"

    def _load(self, session_id: str) -> List[Dict[str, Any]]:
        path = self._path_for(session_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read the saved task list: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("session_id") != session_id:
            raise RuntimeError("Task list metadata is invalid; refusing to overwrite it.")
        tasks = payload.get("tasks")
        if not isinstance(tasks, list) or len(tasks) > _MAX_TASKS:
            raise RuntimeError("Task list format is invalid; refusing to overwrite it.")
        for task in tasks:
            if not isinstance(task, dict) or task.get("status") not in _VALID_STATUSES:
                raise RuntimeError("Task list contains an invalid entry; refusing to overwrite it.")
        return tasks

    def _save(self, session_id: str, tasks: List[Dict[str, Any]]) -> None:
        path = self._path_for(session_id)
        fd, temp_name = tempfile.mkstemp(prefix=".todo-", suffix=".tmp", dir=str(self.directory))
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {"version": 1, "session_id": session_id, "updated_at": _now(), "tasks": tasks},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _summary(tasks: List[Dict[str, Any]]) -> Dict[str, int]:
        return {
            status: sum(1 for task in tasks if task.get("status") == status)
            for status in sorted(_VALID_STATUSES)
        }

    def list(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            tasks = self._load(session_id)
            ordered = sorted(
                tasks,
                key=lambda item: (
                    item.get("status") == "completed",
                    {"high": 0, "normal": 1, "low": 2}.get(item.get("priority"), 1),
                    item.get("created_at", ""),
                ),
            )
            return {
                "session_id": session_id,
                "tasks": ordered,
                "summary": self._summary(tasks),
                "remaining": sum(1 for item in tasks if item.get("status") != "completed"),
            }

    def add(self, session_id: str, title: str, description: str = "", priority: str = "normal") -> Dict[str, Any]:
        clean_title = str(title or "").strip()
        clean_description = str(description or "").strip()
        clean_priority = str(priority or "normal").strip().lower()
        if not clean_title or len(clean_title) > 240:
            raise ValueError("Task title must contain 1-240 characters.")
        if len(clean_description) > 2000:
            raise ValueError("Task description cannot exceed 2000 characters.")
        if clean_priority not in _VALID_PRIORITIES:
            raise ValueError("Priority must be low, normal, or high.")
        with self._lock:
            tasks = self._load(session_id)
            if len(tasks) >= _MAX_TASKS:
                raise ValueError(f"Session task limit reached ({_MAX_TASKS}).")
            stamp = _now()
            task = {
                "id": "T-" + uuid.uuid4().hex[:8],
                "title": clean_title,
                "description": clean_description,
                "priority": clean_priority,
                "status": "pending",
                "created_at": stamp,
                "updated_at": stamp,
            }
            tasks.append(task)
            self._save(session_id, tasks)
            return {"session_id": session_id, "task": task, "remaining": sum(x["status"] != "completed" for x in tasks)}

    def update(
        self,
        session_id: str,
        task_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            tasks = self._load(session_id)
            task = next((item for item in tasks if item.get("id") == task_id), None)
            if task is None:
                raise KeyError(f"Task '{task_id}' was not found in this session.")
            if title is not None:
                clean = str(title).strip()
                if not clean or len(clean) > 240:
                    raise ValueError("Task title must contain 1-240 characters.")
                task["title"] = clean
            if description is not None:
                clean = str(description).strip()
                if len(clean) > 2000:
                    raise ValueError("Task description cannot exceed 2000 characters.")
                task["description"] = clean
            if priority is not None:
                clean = str(priority).strip().lower()
                if clean not in _VALID_PRIORITIES:
                    raise ValueError("Priority must be low, normal, or high.")
                task["priority"] = clean
            if status is not None:
                clean = str(status).strip().lower()
                if clean not in _VALID_STATUSES:
                    raise ValueError("Status must be pending, in_progress, blocked, or completed.")
                task["status"] = clean
            task["updated_at"] = _now()
            self._save(session_id, tasks)
            return {"session_id": session_id, "task": task, "summary": self._summary(tasks)}

    def remove(self, session_id: str, task_id: str) -> Dict[str, Any]:
        with self._lock:
            tasks = self._load(session_id)
            remaining = [item for item in tasks if item.get("id") != task_id]
            if len(remaining) == len(tasks):
                raise KeyError(f"Task '{task_id}' was not found in this session.")
            self._save(session_id, remaining)
            return {"session_id": session_id, "removed": task_id, "summary": self._summary(remaining)}


def get_todo_tools(
    current_session_getter: Callable[[], str],
    directory: Path,
):
    store = TodoStore(directory)

    def todo(
        action: str,
        title: str = "",
        task_id: str = "",
        description: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create, list, update, complete, or remove tasks in the current session plan."""
        session_id = str(current_session_getter() or "").strip()
        if not session_id:
            return {"error": "No active session is available for the task list."}
        selected = str(action or "").strip().lower()
        try:
            if selected == "list":
                return store.list(session_id)
            if selected == "add":
                return store.add(session_id, title, description or "", priority or "normal")
            if selected == "update":
                if not task_id:
                    return {"error": "task_id is required for update."}
                return store.update(
                    session_id,
                    task_id,
                    title=title if title else None,
                    description=description,
                    priority=priority,
                    status=status,
                )
            if selected == "complete":
                if not task_id:
                    return {"error": "task_id is required for complete."}
                return store.update(session_id, task_id, status="completed")
            if selected == "remove":
                if not task_id:
                    return {"error": "task_id is required for remove."}
                return store.remove(session_id, task_id)
            return {"error": "Unknown action. Use list, add, update, complete, or remove."}
        except (ValueError, KeyError, RuntimeError) as exc:
            return {"error": str(exc)}

    from .base import Tool

    return [
        Tool(
            name="todo",
            description=(
                "Maintain the current session's coding/work plan. Actions: list, add, update, complete, remove. "
                "Create concise tasks for multi-step work, mark one in_progress while working, mark blocked when "
                "a prerequisite fails, and complete only after verification. The list persists across CLI restarts "
                "for this session and is isolated from other sessions."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "add", "update", "complete", "remove"]},
                    "title": {"type": "string", "description": "Task title for add; optional replacement title for update"},
                    "task_id": {"type": "string", "description": "Task ID for update, complete, or remove"},
                    "description": {"type": "string", "description": "Optional task detail or replacement description"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "blocked", "completed"]}
                },
                "required": ["action"]
            },
            handler=todo,
        )
    ]
