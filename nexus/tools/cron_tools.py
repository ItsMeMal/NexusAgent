from typing import Dict, Any
from .base import Tool
from ..cron import CronScheduler

def get_cron_tools(scheduler: CronScheduler):
    def schedule_task(name: str, schedule: str, instruction: str) -> str:
        """Schedule a background recurring job or reminder."""
        task_id = scheduler.add_task(name=name, schedule=schedule, instruction=instruction)
        return f"Successfully scheduled task #{task_id}: '{name}' with interval/schedule '{schedule}'."

    def list_scheduled_tasks() -> str:
        """List all active or registered background cron tasks."""
        tasks = scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks registered."
        lines = ["Scheduled Cron Tasks:"]
        for t in tasks:
            lines.append(f"- [#{t['id']}] {t['name']} ({t['schedule']}): {t['instruction']} [Status: {t['status']}]")
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
            description="Schedule a recurring or delayed task (cron/background automation).",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short name for the task"},
                    "schedule": {"type": "string", "description": "Cron expression or interval e.g. 'every 1h', 'daily', '0 9 * * *'"},
                    "instruction": {"type": "string", "description": "The exact prompt/instruction for the agent to execute"}
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
