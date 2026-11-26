"""
nexus/team/board.py
Shared Task Board, Team Mailbox, Tool Execution Log, and Artifact Tracker.

Provides the shared state that turns multiple isolated agents into a real AI-Team:
  - TeamTask      : shared tasks with dependencies, assignee, status, and result
  - TeamMessage   : inter-agent / lead / user communication bus
  - TeamToolEvent : live tool invocations (write_file, read_file, run_command, ...)
  - TeamBoard     : async-safe workspace state + live event pub/sub
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional


EventCallback = Callable[[str, Dict[str, Any]], Any]


def _now_hms() -> str:
    return time.strftime("%H:%M:%S")


def normalize_task_id(raw: Any) -> str:
    """Normalize task ID references like 't1', '1', 'T1: Build UI' -> 'T1'."""
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.match(r"^[Tt]?(\d+)\b", s)
    if m:
        return f"T{m.group(1)}"
    return s


def normalize_depends_on(depends_on: Any) -> List[str]:
    """Safely normalize depends_on from list, JSON array string, or comma-separated string."""
    if not depends_on:
        return []
    items: List[Any]
    if isinstance(depends_on, str):
        s = depends_on.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                items = parsed if isinstance(parsed, list) else [s]
            except Exception:
                items = [x.strip() for x in s.strip("[]").split(",")]
        else:
            items = [x.strip() for x in s.split(",")]
    elif isinstance(depends_on, (list, tuple, set)):
        items = list(depends_on)
    else:
        items = [depends_on]

    out: List[str] = []
    for item in items:
        norm = normalize_task_id(item)
        if norm and norm not in out:
            out.append(norm)
    return out


@dataclass
class TeamTask:
    id: str
    title: str
    description: str
    assigned_to: str
    status: str = "pending"  # pending | in_progress | completed | failed | blocked
    depends_on: List[str] = field(default_factory=list)
    result: str = ""
    files: List[str] = field(default_factory=list)
    created_by: str = "lead"
    created_at: str = field(default_factory=_now_hms)
    updated_at: str = field(default_factory=_now_hms)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TeamMessage:
    id: str
    sender: str
    recipient: str  # "all" | "lead" | role_id | "user"
    content: str
    kind: str = "chat"  # directive | handoff | feedback | status | user | chat
    timestamp: str = field(default_factory=_now_hms)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TeamToolEvent:
    id: str
    agent_id: str
    role_name: str
    tool_name: str
    args_summary: str
    status: str = "running"  # running | done | error
    result_preview: str = ""
    elapsed: float = 0.0
    timestamp: str = field(default_factory=_now_hms)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TeamBoard:
    """Shared state and real-time event hub for one AI-Team mission."""

    def __init__(
        self,
        run_id: str,
        goal: str,
        preset: str,
        mode: str,
        roles: List[str],
        workspace_dir: str = "",
    ) -> None:
        self.id = run_id
        self.goal = goal
        self.preset = preset
        self.mode = mode  # "team" | "parallel" | "sequential"
        self.roles = list(roles)
        self.workspace_dir = workspace_dir
        self.status = "planning"  # planning | executing | reviewing | completed | cancelled | failed
        self.started_at = _now_hms()
        self._start_mono = time.monotonic()
        self.total_elapsed: float = 0.0
        self.done: bool = False
        self.summary: str = ""
        self.error: Optional[str] = None

        self._lock = asyncio.Lock()
        self._task_seq = 0
        self._subscribers: List[EventCallback] = []

        self.tasks: List[TeamTask] = []
        self.messages: List[TeamMessage] = []
        self.tool_events: List[TeamToolEvent] = []
        self.files_touched: List[Dict[str, str]] = []  # [{"path": ..., "action": ..., "by": ..., "timestamp": ...}]
        self.agents: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Event subscription
    # ------------------------------------------------------------------

    def subscribe(self, cb: EventCallback) -> None:
        if cb not in self._subscribers:
            self._subscribers.append(cb)

    def unsubscribe(self, cb: EventCallback) -> None:
        if cb in self._subscribers:
            self._subscribers.remove(cb)

    async def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.total_elapsed = round(time.monotonic() - self._start_mono, 1)
        for cb in list(self._subscribers):
            try:
                res = cb(event_type, payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Agent state tracking
    # ------------------------------------------------------------------

    def init_agent(self, role_id: str, name: str, description: str = "", is_lead: bool = False) -> None:
        self.agents[role_id] = {
            "id": role_id,
            "name": name,
            "description": description,
            "is_lead": is_lead,
            "state": "waiting",  # waiting | thinking | tool | done | error | cancelled
            "current_task": "",
            "current_tool": "",
            "tool_count": 0,
            "elapsed": 0.0,
            "output": "",
            "_started": 0.0,
        }

    async def set_agent_state(
        self,
        role_id: str,
        state: str,
        current_task: Optional[str] = None,
        current_tool: Optional[str] = None,
        output: Optional[str] = None,
        increment_tool: bool = False,
    ) -> None:
        async with self._lock:
            ag = self.agents.get(role_id)
            if not ag:
                return
            if state in ("thinking", "tool") and not ag.get("_started"):
                ag["_started"] = time.monotonic()
            if ag.get("_started"):
                ag["elapsed"] = round(time.monotonic() - ag["_started"], 1)
            ag["state"] = state
            if current_task is not None:
                ag["current_task"] = current_task
            if current_tool is not None:
                ag["current_tool"] = current_tool
            elif state != "tool":
                ag["current_tool"] = ""
            if increment_tool:
                ag["tool_count"] = int(ag.get("tool_count", 0)) + 1
            if output is not None:
                ag["output"] = output
            snapshot = {k: v for k, v in ag.items() if not k.startswith("_")}

        await self.emit("agent_update", {"run_id": self.id, "role_id": role_id, "agent": snapshot})

    # ------------------------------------------------------------------
    # Task Board operations
    # ------------------------------------------------------------------

    async def create_task(
        self,
        title: str,
        description: str,
        assigned_to: str,
        depends_on: Any = None,
        created_by: str = "lead",
    ) -> TeamTask:
        async with self._lock:
            self._task_seq += 1
            tid = f"T{self._task_seq}"
            deps = [d for d in normalize_depends_on(depends_on) if d != tid]
            task = TeamTask(
                id=tid,
                title=title.strip(),
                description=description.strip(),
                assigned_to=assigned_to.strip().lower(),
                depends_on=deps,
                created_by=created_by,
            )
            self.tasks.append(task)
        await self.emit("board_update", {"run_id": self.id, "tasks": [t.to_dict() for t in self.tasks]})
        return task

    async def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        result: Optional[str] = None,
        files: Optional[List[str]] = None,
    ) -> Optional[TeamTask]:
        norm_id = normalize_task_id(task_id)
        updated: Optional[TeamTask] = None
        async with self._lock:
            for t in self.tasks:
                if t.id == norm_id or t.id.lower() == str(task_id).strip().lower():
                    if status:
                        t.status = status
                    if result is not None:
                        t.result = result
                    if files:
                        for f in files:
                            if f not in t.files:
                                t.files.append(f)
                    t.updated_at = _now_hms()
                    updated = t
                    break
        if updated:
            await self.emit("board_update", {"run_id": self.id, "tasks": [t.to_dict() for t in self.tasks]})
        return updated

    def _resolve_deps(self, task: TeamTask) -> List[str]:
        """Resolve dependency entries to real task IDs on this board (ignoring phantom refs)."""
        all_ids = {t.id for t in self.tasks}
        resolved: List[str] = []
        for dep in task.depends_on:
            norm = normalize_task_id(dep)
            if norm in all_ids and norm != task.id:
                resolved.append(norm)
            else:
                # Try matching by role name if model passed e.g. 'planner'
                role_match = [t.id for t in self.tasks if t.assigned_to == dep.lower() and t.id != task.id]
                resolved.extend(role_match)
        return resolved

    def get_ready_tasks(self) -> List[TeamTask]:
        """Return pending tasks whose resolvable dependencies are all completed."""
        done_ids = {t.id for t in self.tasks if t.status == "completed"}
        failed_ids = {t.id for t in self.tasks if t.status in ("failed", "blocked")}
        ready: List[TeamTask] = []
        for t in self.tasks:
            if t.status != "pending":
                continue
            deps = self._resolve_deps(t)
            if any(dep in failed_ids for dep in deps):
                continue
            if all(dep in done_ids for dep in deps):
                ready.append(t)
        return ready

    async def unblock_stalled_tasks(self) -> bool:
        """If pending tasks are deadlocked on failed/circular deps, unblock the earliest pending task."""
        target: Optional[TeamTask] = None
        async with self._lock:
            for t in self.tasks:
                if t.status == "pending":
                    t.depends_on = []
                    target = t
                    break
        if target:
            await self.emit("board_update", {"run_id": self.id, "tasks": [t.to_dict() for t in self.tasks]})
            return True
        return False

    def has_open_tasks(self) -> bool:
        return any(t.status in ("pending", "in_progress") for t in self.tasks)

    # ------------------------------------------------------------------
    # Team Mailbox
    # ------------------------------------------------------------------

    async def post_message(
        self,
        sender: str,
        recipient: str,
        content: str,
        kind: str = "chat",
    ) -> TeamMessage:
        msg = TeamMessage(
            id=uuid.uuid4().hex[:8],
            sender=sender,
            recipient=recipient or "all",
            content=content.strip(),
            kind=kind,
        )
        async with self._lock:
            self.messages.append(msg)
            if len(self.messages) > 200:
                self.messages = self.messages[-200:]
        await self.emit("message", {"run_id": self.id, "message": msg.to_dict()})
        return msg

    def get_messages(self, for_agent: Optional[str] = None, limit: int = 30) -> List[TeamMessage]:
        if not for_agent:
            return self.messages[-limit:]
        filtered = [
            m for m in self.messages
            if m.recipient in ("all", for_agent) or m.sender == for_agent
        ]
        return filtered[-limit:]

    # ------------------------------------------------------------------
    # Tool Events & Files
    # ------------------------------------------------------------------

    async def record_tool_start(
        self,
        agent_id: str,
        role_name: str,
        tool_name: str,
        args_summary: str,
    ) -> str:
        ev = TeamToolEvent(
            id=uuid.uuid4().hex[:8],
            agent_id=agent_id,
            role_name=role_name,
            tool_name=tool_name,
            args_summary=args_summary[:180],
            status="running",
        )
        async with self._lock:
            self.tool_events.append(ev)
            if len(self.tool_events) > 250:
                self.tool_events = self.tool_events[-250:]
        await self.emit("tool_event", {"run_id": self.id, "event": ev.to_dict()})
        return ev.id

    async def record_tool_end(
        self,
        agent_id: str,
        tool_name: str,
        result_preview: str,
        elapsed: float,
        is_error: bool = False,
    ) -> None:
        target: Optional[TeamToolEvent] = None
        async with self._lock:
            for ev in reversed(self.tool_events):
                if ev.agent_id == agent_id and ev.tool_name == tool_name and ev.status == "running":
                    ev.status = "error" if is_error else "done"
                    ev.result_preview = (result_preview or "")[:300]
                    ev.elapsed = round(elapsed, 2)
                    target = ev
                    break
        if target:
            await self.emit("tool_event", {"run_id": self.id, "event": target.to_dict()})

    async def record_file(self, path: str, action: str, agent_id: str) -> None:
        clean_path = str(path).strip()
        if not clean_path:
            return
        entry = {
            "path": clean_path,
            "action": action,
            "by": agent_id,
            "timestamp": _now_hms(),
        }
        async with self._lock:
            # Update existing entry for same path or append
            existing = next((f for f in self.files_touched if f["path"] == clean_path), None)
            if existing:
                existing["action"] = action
                existing["by"] = agent_id
                existing["timestamp"] = entry["timestamp"]
            else:
                self.files_touched.append(entry)
        await self.emit("file_touched", {"run_id": self.id, "files": list(self.files_touched), "latest": entry})

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task": self.goal,
            "goal": self.goal,
            "preset": self.preset,
            "mode": self.mode,
            "status": self.status,
            "roles": list(self.roles),
            "workspace_dir": self.workspace_dir,
            "started_at": self.started_at,
            "total_elapsed": round(time.monotonic() - self._start_mono, 1) if not self.done else self.total_elapsed,
            "done": self.done,
            "summary": self.summary,
            "error": self.error,
            "agents": {
                k: {ak: av for ak, av in v.items() if not ak.startswith("_")}
                for k, v in self.agents.items()
            },
            "tasks": [t.to_dict() for t in self.tasks],
            "messages": [m.to_dict() for m in self.messages],
            "tool_events": [e.to_dict() for e in self.tool_events],
            "files_touched": list(self.files_touched),
        }
