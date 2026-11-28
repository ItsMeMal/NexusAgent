from pathlib import Path
from typing import Any, Dict, List

from .base import Tool
from ..checkpoints import CheckpointError, CheckpointManager


def get_checkpoint_tools(root_dir: Path):
    manager = CheckpointManager(root_dir)

    def create_checkpoint(label: str = "") -> Dict[str, Any]:
        """Snapshot eligible workspace files before risky or broad code changes."""
        try:
            return manager.create_checkpoint(label=label)
        except (CheckpointError, OSError) as error:
            return {"error": str(error)}

    def list_checkpoints(limit: int = 20) -> List[Dict[str, Any]]:
        """List recent valid workspace checkpoints."""
        try:
            return manager.list_checkpoints(limit=limit)
        except (CheckpointError, OSError, ValueError) as error:
            return [{"error": str(error)}]

    def inspect_checkpoint(checkpoint_id: str) -> Dict[str, Any]:
        """Inspect metadata for one checkpoint without changing the workspace."""
        try:
            return manager.inspect_checkpoint(checkpoint_id)
        except (CheckpointError, OSError, ValueError) as error:
            return {"error": str(error)}

    def restore_checkpoint(
        checkpoint_id: str,
        mode: str = "overlay",
        confirm_exact: bool = False,
    ) -> Dict[str, Any]:
        """Restore a checkpoint. Exact mode deletes eligible post-checkpoint files and requires explicit confirmation."""
        try:
            return manager.restore_checkpoint(
                checkpoint_id=checkpoint_id,
                mode=mode,
                confirm_exact=confirm_exact,
            )
        except (CheckpointError, OSError, ValueError) as error:
            return {"error": str(error)}

    return [
        Tool(
            name="create_checkpoint",
            description=(
                "Create a bounded, secret-safe snapshot of the current workspace before risky edits. "
                "Snapshots are stored outside the project and exclude .git, dependencies, build outputs, "
                "environment files, private keys, and oversized files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Short reason for this checkpoint", "default": ""}
                },
            },
            handler=create_checkpoint,
        ),
        Tool(
            name="list_checkpoints",
            description="List recent valid restore points for this workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}
                },
            },
            handler=list_checkpoints,
        ),
        Tool(
            name="inspect_checkpoint",
            description="Inspect a checkpoint's ID, label, timestamp, file count, and size before restoring it.",
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint_id": {"type": "string"}
                },
                "required": ["checkpoint_id"],
            },
            handler=inspect_checkpoint,
        ),
        Tool(
            name="restore_checkpoint",
            description=(
                "Restore workspace files from a checkpoint. Default mode='overlay' restores files captured "
                "in the checkpoint but NEVER deletes files created afterwards. mode='exact' also deletes "
                "eligible files absent from the checkpoint and requires confirm_exact=true only after the "
                "user has explicitly confirmed destructive rollback. Every restore first creates a safety checkpoint."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint_id": {"type": "string"},
                    "mode": {"type": "string", "enum": ["overlay", "exact"], "default": "overlay"},
                    "confirm_exact": {
                        "type": "boolean",
                        "description": "Required true for exact rollback; only set after explicit user confirmation.",
                        "default": False,
                    },
                },
                "required": ["checkpoint_id"],
            },
            handler=restore_checkpoint,
        ),
    ]
