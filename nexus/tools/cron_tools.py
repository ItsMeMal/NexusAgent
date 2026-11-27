from typing import Dict, Any
from .base import Tool
from ..cron import CronScheduler

def get_cron_tools(scheduler: CronScheduler):
    def schedule_task(name: str, schedule: str, instruction: str, mode: str = "agent", target: str = "") -> str:
        """Schedule a background recurring or one-shot job executed automatically by the Cron Runner."""
        task_id = scheduler.add_task(name=name, schedule=schedule, instruction=instruction, mode=mode, target=target)
        return (
            f"Successfully scheduled task #{task_id}: '{name}' "
            f"(schedule='{schedule}', mode='{mode}'{f', target={target}' if target else ''}). "
            "It will execute automatically when due."
        )

    def list_scheduled_tasks() -> str:
        """List all active, paused, or completed background cron tasks."""
        tasks = scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks registered."
        lines = ["Scheduled Cron Tasks:"]
        for t in tasks:
            runs = t.get("run_count", 0) or 0
            mode = t.get("mode", "agent")
            lines.append(
                f"- [#{t['id']}] {t['name']} ({t['schedule']} · {mode} · runs={runs}): "
                f"{t['instruction']} [Status: {t['status']}]"
            )
            if t.get("last_result"):
                lines.append(f"    Last output: {str(t['last_result'])[:140]}")
        return "\n".join(lines)

    def cancel_scheduled_task(task_id: int) -> str:
        """Cancel a scheduled cron task by ID."""
        success = scheduler.cancel_task(task_id=task_id)
        if success:
            return f"Task #{task_id} cancelled."
        return f"Could not find or cancel task #{task_id}."

    return [
        Tool(
            name="schedule_task",
            description="Schedule a recurring or one-shot background task executed automatically by the Cron Runner (agent or zero-LLM shell mode).",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short name for the task"},
                    "schedule": {"type": "string", "description": "Interval/cron e.g. 'every 5m', 'every 1h', 'daily 09:00', 'in 10m', '*/5 * * * *'"},
                    "instruction": {"type": "string", "description": "Agent prompt (when mode='agent') OR exact shell command (when mode='shell')"},
                    "mode": {"type": "string", "enum": ["agent", "shell"], "description": "'agent' runs NexusAgent, 'shell' runs command directly with zero LLM cost", "default": "agent"},
                    "target": {"type": "string", "description": "Optional delivery surface ('', 'cli', 'telegram', 'discord', 'whatsapp')", "default": ""}
                },
                "required": ["name", "schedule", "instruction"]
            },
            handler=schedule_task
        ),
        Tool(
            name="list_scheduled_tasks",
            description="List all scheduled cron jobs.",
            parameters={"type": "object", "properties": {}},
            handler=list_scheduled_tasks
        ),
        Tool(
            name="cancel_scheduled_task",
            description="Cancel a scheduled job by its task ID.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "ID of the task to cancel"}
                },
                "required": ["task_id"]
            },
            handler=cancel_scheduled_task
        )
    ]
