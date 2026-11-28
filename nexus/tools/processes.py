"""Tracked background processes for long-running coding and development commands.

Process handles are scoped to one live ProcessManager (normally one Nolthira CLI
runtime). They are intentionally not reconstructed from arbitrary PIDs after a
restart: only processes started by this manager can be inspected or terminated.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class ProcessManager:
    """Own and supervise background subprocesses started by Nolthira."""

    def __init__(
        self,
        logs_dir: Path,
        *,
        max_sessions: int = 24,
        max_log_bytes: int = 4 * 1024 * 1024,
    ):
        self.logs_dir = Path(logs_dir).expanduser().resolve()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        try:
            if os.name != "nt":
                os.chmod(self.logs_dir, 0o700)
        except OSError:
            pass
        self.max_sessions = max(1, min(int(max_sessions), 64))
        self.max_log_bytes = max(64 * 1024, min(int(max_log_bytes), 16 * 1024 * 1024))
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _status(self, session: Dict[str, Any]) -> str:
        code = session["process"].poll()
        if code is None:
            return "running"
        return "completed" if code == 0 else ("killed" if session.get("killed") else "failed")

    def _refresh(self, session: Dict[str, Any]) -> None:
        if session["process"].poll() is not None:
            thread = session.get("capture_thread")
            if thread and thread.is_alive():
                thread.join(timeout=1.0)
            if not thread or not thread.is_alive():
                for stream_name in ("stdin", "stdout", "stderr"):
                    stream = getattr(session["process"], stream_name, None)
                    if stream is not None and not getattr(stream, "closed", True):
                        try:
                            stream.close()
                        except OSError:
                            pass
            if session.get("finished_at") is None:
                session["finished_at"] = time.time()

    def _capture_output(self, session: Dict[str, Any]) -> None:
        process = session["process"]
        pipe = process.stdout
        if pipe is None:
            return
        marker = b"\n...[earlier process output trimmed]...\n"
        try:
            with open(session["log_path"], "w+b") as log_file:
                while True:
                    chunk = pipe.read(8192)
                    if not chunk:
                        break
                    with session["lock"]:
                        log_file.seek(0, os.SEEK_END)
                        log_file.write(chunk)
                        log_file.flush()
                        if log_file.tell() > self.max_log_bytes:
                            keep_bytes = self.max_log_bytes // 2
                            log_file.seek(-keep_bytes, os.SEEK_END)
                            tail = log_file.read()
                            log_file.seek(0)
                            log_file.write(marker)
                            log_file.write(tail)
                            log_file.truncate()
                            log_file.flush()
                            session["output_generation"] += 1
        except (OSError, ValueError):
            session["capture_error"] = "Process output capture failed; the process may still have completed."
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    def _prune(self) -> None:
        now = time.time()
        with self._lock:
            for sid, session in list(self._sessions.items()):
                self._refresh(session)
                finished = session.get("finished_at")
                if finished and now - finished > 3600:
                    try:
                        Path(session["log_path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
                    self._sessions.pop(sid, None)

            if len(self._sessions) < self.max_sessions:
                return
            completed = sorted(
                (
                    (item.get("finished_at") or item["started_at"], sid, item)
                    for sid, item in self._sessions.items()
                    if item["process"].poll() is not None
                ),
                key=lambda row: row[0],
            )
            while len(self._sessions) >= self.max_sessions and completed:
                _, sid, item = completed.pop(0)
                try:
                    Path(item["log_path"]).unlink(missing_ok=True)
                except OSError:
                    pass
                self._sessions.pop(sid, None)

    def start(self, command: str, cwd: Path, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Start a command and return a handle without waiting for completion."""
        command = str(command or "").strip()
        if not command:
            return {"error": "A non-empty command is required."}
        self._prune()
        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                return {
                    "error": f"Background process limit reached ({self.max_sessions}). "
                    "Stop or allow completed sessions to expire before starting another."
                }

        session_id = "proc_" + uuid.uuid4().hex[:12]
        log_path = self.logs_dir / f"{session_id}.log"
        popen_kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        else:
            popen_kwargs["start_new_session"] = True

        try:
            log_path.touch(mode=0o600, exist_ok=False)
            process = subprocess.Popen(
                command,
                cwd=str(Path(cwd).resolve()),
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                env=env,
                **popen_kwargs,
            )
        except Exception as exc:
            try:
                log_path.unlink(missing_ok=True)
            except OSError:
                pass
            return {"error": f"Could not start background command: {type(exc).__name__}: {exc}"}

        session: Dict[str, Any] = {
            "session_id": session_id,
            "command": command[:1000],
            "cwd": str(Path(cwd).resolve()),
            "pid": process.pid,
            "process": process,
            "log_path": str(log_path),
            "started_at": time.time(),
            "finished_at": None,
            "killed": False,
            "cursor": 0,
            "output_generation": 0,
            "cursor_generation": 0,
            "capture_error": "",
            "lock": threading.RLock(),
        }
        thread = threading.Thread(
            target=self._capture_output,
            args=(session,),
            name=f"nolthira-{session_id}",
            daemon=True,
        )
        session["capture_thread"] = thread
        with self._lock:
            self._sessions[session_id] = session
        thread.start()
        return {
            "status": "running",
            "session_id": session_id,
            "pid": process.pid,
            "command": session["command"],
            "cwd": session["cwd"],
            "message": "Process started in background. Use process(action='poll'|'log'|'wait'|'kill') with this session_id; do not start the same command again.",
        }

    def _get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._sessions.get(str(session_id or "").strip())

    def _read_new_output(self, session: Dict[str, Any], limit: int = 24000) -> str:
        marker = ""
        with session["lock"]:
            if session["cursor_generation"] != session["output_generation"]:
                marker = "[Earlier output was trimmed to enforce the process log size limit.]\n"
                session["cursor"] = 0
                session["cursor_generation"] = session["output_generation"]
            try:
                with open(session["log_path"], "rb") as log_file:
                    log_file.seek(0, os.SEEK_END)
                    size = log_file.tell()
                    if session["cursor"] > size:
                        session["cursor"] = 0
                        marker = "[Process log was rotated; reading retained output.]\n"
                    log_file.seek(session["cursor"])
                    data = log_file.read(max(1024, min(int(limit), 64000)))
                    session["cursor"] = log_file.tell()
                return marker + data.decode("utf-8", errors="replace")
            except OSError as exc:
                return marker + f"[Could not read process output: {exc}]"

    def poll(self, session_id: str) -> Dict[str, Any]:
        session = self._get(session_id)
        if not session:
            return {"error": "Unknown process session. Only sessions started by this Nolthira runtime can be managed."}
        self._refresh(session)
        code = session["process"].poll()
        result = {
            "session_id": session["session_id"],
            "status": self._status(session),
            "pid": session["pid"],
            "exit_code": code,
            "runtime_seconds": round((session.get("finished_at") or time.time()) - session["started_at"], 2),
            "new_output": self._read_new_output(session),
        }
        if session.get("capture_error"):
            result["warning"] = session["capture_error"]
        return result

    def log(self, session_id: str, limit: int = 24000) -> Dict[str, Any]:
        session = self._get(session_id)
        if not session:
            return {"error": "Unknown process session. Only sessions started by this Nolthira runtime can be managed."}
        self._refresh(session)
        safe_limit = max(1024, min(int(limit or 24000), 64000))
        with session["lock"]:
            try:
                with open(session["log_path"], "rb") as log_file:
                    log_file.seek(0, os.SEEK_END)
                    size = log_file.tell()
                    log_file.seek(max(0, size - safe_limit))
                    data = log_file.read(safe_limit)
            except OSError as exc:
                return {"error": f"Could not read process log: {exc}"}
        return {
            "session_id": session["session_id"],
            "status": self._status(session),
            "exit_code": session["process"].poll(),
            "output": data.decode("utf-8", errors="replace"),
            "truncated": size > safe_limit,
        }

    def wait(self, session_id: str, timeout: int = 30) -> Dict[str, Any]:
        session = self._get(session_id)
        if not session:
            return {"error": "Unknown process session. Only sessions started by this Nolthira runtime can be managed."}
        safe_timeout = max(1, min(int(timeout or 30), 300))
        try:
            session["process"].wait(timeout=safe_timeout)
        except subprocess.TimeoutExpired:
            return {
                "session_id": session["session_id"],
                "status": "running",
                "message": f"Still running after {safe_timeout} seconds.",
            }
        self._refresh(session)
        return self.log(session_id)

    def write(self, session_id: str, data: str) -> Dict[str, Any]:
        session = self._get(session_id)
        if not session:
            return {"error": "Unknown process session. Only sessions started by this Nolthira runtime can be managed."}
        if session["process"].poll() is not None:
            return {"error": "Process has already exited; stdin is no longer available."}
        pipe = session["process"].stdin
        if pipe is None:
            return {"error": "Process stdin is unavailable."}
        try:
            pipe.write(str(data or "").encode("utf-8"))
            pipe.flush()
            return {"session_id": session["session_id"], "written_bytes": len(str(data or "").encode("utf-8"))}
        except (BrokenPipeError, OSError, ValueError) as exc:
            return {"error": f"Could not write to process stdin: {exc}"}

    def kill(self, session_id: str) -> Dict[str, Any]:
        session = self._get(session_id)
        if not session:
            return {"error": "Unknown process session. Only sessions started by this Nolthira runtime can be managed."}
        process = session["process"]
        if process.poll() is not None:
            self._refresh(session)
            return {"session_id": session["session_id"], "status": self._status(session), "exit_code": process.returncode}
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"error": f"Could not terminate process tree: {exc}"}
        session["killed"] = True
        self._refresh(session)
        return {"session_id": session["session_id"], "status": "killed", "exit_code": process.returncode}

    def list(self) -> List[Dict[str, Any]]:
        self._prune()
        with self._lock:
            sessions = list(self._sessions.values())
        rows = []
        for session in sorted(sessions, key=lambda item: item["started_at"], reverse=True):
            self._refresh(session)
            rows.append({
                "session_id": session["session_id"],
                "status": self._status(session),
                "pid": session["pid"],
                "command": session["command"],
                "cwd": session["cwd"],
                "exit_code": session["process"].poll(),
                "runtime_seconds": round((session.get("finished_at") or time.time()) - session["started_at"], 2),
            })
        return rows
