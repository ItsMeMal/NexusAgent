import asyncio
import datetime
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


def _parse_cron_field(expr: str, min_val: int, max_val: int) -> Optional[set[int]]:
    """Parse one 5-field cron component (*, */n, a-b, a-b/n, comma lists)."""
    out: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            return None
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) <= 0:
                return None
            step = int(step_s)
        else:
            base = part

        if base == "*":
            lo, hi = min_val, max_val
        elif "-" in base:
            a_s, b_s = base.split("-", 1)
            if not (a_s.isdigit() and b_s.isdigit()):
                return None
            lo, hi = int(a_s), int(b_s)
        elif base.isdigit():
            val = int(base)
            if min_val <= val <= max_val:
                out.add(val)
                continue
            return None
        else:
            return None

        lo = max(min_val, lo)
        hi = min(max_val, hi)
        if lo > hi:
            return None
        out.update(range(lo, hi + 1, step))
    return out if out else None


def compute_next_run(schedule: str, from_ts: Optional[float] = None) -> Tuple[Optional[float], bool]:
    """
    Parse schedule string into (next_run_epoch, is_one_shot).
    Supports:
      - Intervals: 'every 30s', 'every 5m', 'every 2h', 'every 1d', 'hourly', 'daily', 'weekly'
      - Daily time: 'daily 09:00'
      - One-shot delay: 'in 10m', 'once 2026-11-28T09:00:00'
      - 5-field cron: '*/5 * * * *', '0 9 * * 1-5'
    """
    now = float(from_ts if from_ts is not None else time.time())
    s = (schedule or "").strip().lower()
    if not s:
        return now + 3600.0, False

    unit_mult = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
                 "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
                 "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
                 "d": 86400, "day": 86400, "days": 86400}

    # One-shot 'in 5m'
    m_in = re.match(r"^(?:in|once\s+in)\s+(\d+)\s*([a-z]+)$", s)
    if m_in and m_in.group(2) in unit_mult:
        return now + int(m_in.group(1)) * unit_mult[m_in.group(2)], True

    # Recurring 'every 5m' or bare '5m'
    m_ev = re.match(r"^(?:every\s+)?(\d+)\s*([a-z]+)$", s)
    if m_ev and m_ev.group(2) in unit_mult:
        return now + max(5, int(m_ev.group(1)) * unit_mult[m_ev.group(2)]), False

    if s == "hourly":
        return now + 3600.0, False
    if s == "daily":
        return now + 86400.0, False
    if s == "weekly":
        return now + 7 * 86400.0, False

    m_daily_at = re.match(r"^daily\s+(\d{1,2}):(\d{2})$", s)
    if m_daily_at:
        hh, mm = int(m_daily_at.group(1)), int(m_daily_at.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            dt = datetime.datetime.fromtimestamp(now)
            cand = dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if cand.timestamp() <= now:
                cand += datetime.timedelta(days=1)
            return cand.timestamp(), False

    # One-shot ISO datetime 'once YYYY-MM-DD HH:MM' or 'once YYYY-MM-DDTHH:MM:SS'
    if s.startswith("once "):
        iso_part = schedule.strip()[5:].strip()
        try:
            dt = datetime.datetime.fromisoformat(iso_part)
            return dt.timestamp(), True
        except Exception:
            pass

    # Standard 5-field cron: min hour dom month dow
    fields = s.split()
    if len(fields) == 5:
        mins = _parse_cron_field(fields[0], 0, 59)
        hrs = _parse_cron_field(fields[1], 0, 23)
        doms = _parse_cron_field(fields[2], 1, 31)
        months = _parse_cron_field(fields[3], 1, 12)
        dows = _parse_cron_field(fields[4], 0, 7)
        if mins and hrs and doms and months and dows:
            if 7 in dows:
                dows.add(0)
            # Scan forward minute-by-minute up to 8 days (11520 mins)
            start_min = int(now // 60) * 60 + 60
            for step_i in range(11520):
                ts = start_min + step_i * 60
                dt = datetime.datetime.fromtimestamp(ts)
                # Python weekday(): Mon=0..Sun=6 -> cron dow: Sun=0, Mon=1..Sat=6
                cron_dow = (dt.weekday() + 1) % 7
                if (
                    dt.minute in mins
                    and dt.hour in hrs
                    and dt.day in doms
                    and dt.month in months
                    and cron_dow in dows
                ):
                    return float(ts), False

    # Sensible default fallback: 1h recurring
    return now + 3600.0, False


CronExecutor = Callable[[Dict[str, Any]], Awaitable[str]]
CronNotifier = Callable[[Dict[str, Any], str], Any]


class CronScheduler:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()
        self._runner_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._running_ids: set[int] = set()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    schedule TEXT,
                    instruction TEXT,
                    status TEXT DEFAULT 'active',
                    last_run TIMESTAMP,
                    next_run REAL,
                    run_count INTEGER DEFAULT 0,
                    last_result TEXT,
                    mode TEXT DEFAULT 'agent',
                    target TEXT DEFAULT '',
                    one_shot INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("PRAGMA table_info(scheduled_tasks)")
            cols = {row[1] for row in cursor.fetchall()}
            migrations = [
                ("next_run", "ALTER TABLE scheduled_tasks ADD COLUMN next_run REAL"),
                ("run_count", "ALTER TABLE scheduled_tasks ADD COLUMN run_count INTEGER DEFAULT 0"),
                ("last_result", "ALTER TABLE scheduled_tasks ADD COLUMN last_result TEXT"),
                ("mode", "ALTER TABLE scheduled_tasks ADD COLUMN mode TEXT DEFAULT 'agent'"),
                ("target", "ALTER TABLE scheduled_tasks ADD COLUMN target TEXT DEFAULT ''"),
                ("one_shot", "ALTER TABLE scheduled_tasks ADD COLUMN one_shot INTEGER DEFAULT 0"),
            ]
            for col_name, sql in migrations:
                if col_name not in cols:
                    cursor.execute(sql)
            conn.commit()

    def add_task(
        self,
        name: str,
        schedule: str,
        instruction: str,
        mode: str = "agent",
        target: str = "",
        next_run_override: Optional[float] = None,
    ) -> int:
        clean_mode = (mode or "agent").strip().lower()
        if clean_mode not in ("agent", "shell"):
            clean_mode = "agent"
        next_ts, is_once = compute_next_run(schedule)
        if next_run_override is not None:
            next_ts = float(next_run_override)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scheduled_tasks (name, schedule, instruction, status, next_run, mode, target, one_shot)
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (name, schedule, instruction, next_ts, clean_mode, (target or "").strip().lower(), 1 if is_once else 0),
            )
            conn.commit()
            return cursor.lastrowid

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scheduled_tasks ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def cancel_task(self, task_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE scheduled_tasks SET status = 'cancelled', next_run = NULL WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def pause_task(self, task_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE scheduled_tasks SET status = 'paused' WHERE id = ? AND status = 'active'", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def resume_task(self, task_id: int) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        next_ts, _ = compute_next_run(task.get("schedule", ""))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE scheduled_tasks SET status = 'active', next_run = ? WHERE id = ?",
                (next_ts, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_due_tasks(self, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        now = float(now_ts if now_ts is not None else time.time())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Backfill legacy tasks that had NULL next_run
            cursor.execute("SELECT id, schedule FROM scheduled_tasks WHERE status = 'active' AND next_run IS NULL")
            for legacy_row in cursor.fetchall():
                nxt, once = compute_next_run(legacy_row["schedule"] or "", now)
                cursor.execute(
                    "UPDATE scheduled_tasks SET next_run = ?, one_shot = ? WHERE id = ?",
                    (nxt, 1 if once else 0, legacy_row["id"]),
                )
            conn.commit()

            cursor.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= ?
                ORDER BY next_run ASC
                """,
                (now,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def mark_executed(self, task_id: int, result_text: str, now_ts: Optional[float] = None) -> None:
        now = float(now_ts if now_ts is not None else time.time())
        task = self.get_task(task_id)
        if not task:
            return
        is_once = bool(task.get("one_shot"))
        next_ts, _ = (None, True) if is_once else compute_next_run(task.get("schedule", ""), now)
        new_status = "completed" if is_once else task.get("status", "active")
        now_iso = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE scheduled_tasks
                SET last_run = ?, next_run = ?, status = ?, run_count = COALESCE(run_count, 0) + 1, last_result = ?
                WHERE id = ?
                """,
                (now_iso, next_ts, new_status, (result_text or "")[:1500], task_id),
            )
            conn.commit()

    async def execute_job(
        self,
        job: Dict[str, Any],
        executor: CronExecutor,
        on_complete: Optional[CronNotifier] = None,
    ) -> str:
        tid = int(job["id"])
        if tid in self._running_ids:
            return ""
        self._running_ids.add(tid)
        try:
            try:
                res = await executor(job)
            except Exception as exc:
                res = f"Cron execution error: {exc}"
            self.mark_executed(tid, res)
            if on_complete:
                try:
                    cb_res = on_complete(job, res)
                    if asyncio.iscoroutine(cb_res):
                        await cb_res
                except Exception:
                    pass
            return res
        finally:
            self._running_ids.discard(tid)

    async def run_due_jobs(
        self,
        executor: CronExecutor,
        on_complete: Optional[CronNotifier] = None,
        now_ts: Optional[float] = None,
    ) -> int:
        due = self.get_due_tasks(now_ts=now_ts)
        if not due:
            return 0
        count = 0
        for job in due:
            if job["id"] in self._running_ids:
                continue
            await self.execute_job(job, executor, on_complete=on_complete)
            count += 1
        return count

    async def run_task_now(
        self,
        task_id: int,
        executor: CronExecutor,
        on_complete: Optional[CronNotifier] = None,
    ) -> Optional[str]:
        job = self.get_task(task_id)
        if not job:
            return None
        return await self.execute_job(job, executor, on_complete=on_complete)

    def start_runner(
        self,
        executor: CronExecutor,
        on_complete: Optional[CronNotifier] = None,
        poll_interval: float = 5.0,
    ) -> None:
        """Start background asyncio loop checking and executing due cron jobs."""
        if self._runner_task and not self._runner_task.done():
            return
        self._stop_event = asyncio.Event()

        async def _loop():
            assert self._stop_event is not None
            while not self._stop_event.is_set():
                try:
                    await self.run_due_jobs(executor, on_complete=on_complete)
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=poll_interval)
                    break
                except asyncio.TimeoutError:
                    continue

        self._runner_task = asyncio.create_task(_loop())

    async def stop_runner(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._runner_task and not self._runner_task.done():
            self._runner_task.cancel()
            try:
                await self._runner_task
            except (asyncio.CancelledError, Exception):
                pass
        self._runner_task = None
