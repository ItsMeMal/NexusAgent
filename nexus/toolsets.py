"""Configurable, validated toolset profiles for Nexus Agent.

Configuration lives at ~/.nexus/toolsets.json. Profiles are applied to a ToolRegistry
at runtime, so a tool being installed does not imply that every agent or gateway can
use it.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


BUILTIN_TOOLSETS: Dict[str, str] = {
    "filesystem": "Workspace file inspection and editing",
    "terminal": "Local, Docker, and SSH command execution",
    "project": "Project structure and instruction-file inspection",
    "checkpoints": "Workspace snapshots and rollback",
    "memory": "Persistent memory and cross-session recall",
    "skills": "Discover, read, and manage reusable skills",
    "web": "Web search and URL extraction",
    "browser": "Browser navigation and interaction",
    "cron": "Scheduled and recurring tasks",
    "orchestration": "Subagent delegation",
    "vision": "Image and screenshot analysis",
    "media": "Image and audio generation/transcription",
    "computer": "Desktop GUI automation",
    "gateway": "Messaging gateway operations",
    "mcp": "Model Context Protocol extensions",
    "plugins": "Third-party and local plugins",
    "custom": "Other registered extension tools",
}

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


def _default_config() -> Dict[str, Any]:
    all_toolsets = sorted(BUILTIN_TOOLSETS)
    return {
        "version": 1,
        "default_profile": "default",
        "profiles": {
            "default": {
                "enabled_toolsets": all_toolsets,
                "disabled_toolsets": [],
                "disabled_tools": [],
            },
            "researcher": {
                "extends": "default",
                "disabled_toolsets": [
                    "terminal", "computer", "checkpoints", "media", "gateway",
                    "browser", "cron", "mcp", "plugins", "custom",
                ],
                "disabled_tools": [
                    "write_file", "append_file", "patch_file", "run_command",
                    "create_skill", "update_skill", "delete_skill",
                    "schedule_task", "cancel_scheduled_task", "restore_checkpoint",
                    "store_memory", "review_memory_proposal", "archive_memory",
                    "delete_memory", "restore_memory",
                ],
            },
            "analyst": {
                "extends": "researcher",
                "enabled_toolsets": ["web", "browser", "vision"],
            },
            "coder": {
                "extends": "default",
                "disabled_toolsets": ["gateway", "media"],
                "disabled_tools": [
                    "review_memory_proposal", "archive_memory", "restore_memory",
                    "delete_memory", "delete_skill",
                ],
            },
        },
        "platform_profiles": {
            "telegram": "researcher",
            "discord": "researcher",
            "whatsapp": "researcher",
            "slack": "researcher",
            "email": "researcher",
        },
        "role_profiles": {
            "leaf": "researcher",
            "researcher": "researcher",
            "analyst": "analyst",
            "coder": "coder",
            "debugger": "coder",
            "refactorer": "coder",
        },
        "limits": {
            "max_concurrent_subagents": 3,
            "subagent_timeout_seconds": 600,
            "subagent_max_steps": 20,
        },
    }


class ToolsetConfigError(ValueError):
    """Raised when toolset configuration is invalid or unsafe."""


class ToolsetManager:
    """Load and manage named toolset profiles with inheritance and safe persistence."""

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path).expanduser()
        self._lock = threading.RLock()
        self._config = self._load()

    @property
    def default_profile(self) -> str:
        return str(self._config["default_profile"])

    @property
    def limits(self) -> Dict[str, int]:
        return dict(self._config["limits"])

    def _load(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return _default_config()
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolsetConfigError(f"Cannot read toolset config {self.config_path}: {exc}") from exc
        return self._validate(raw)

    @staticmethod
    def _valid_name(value: Any, field: str) -> str:
        if not isinstance(value, str) or not _NAME_RE.fullmatch(value.strip()):
            raise ToolsetConfigError(f"{field} must be a valid non-empty identifier.")
        return value.strip()

    def _validate(self, raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ToolsetConfigError("Toolset config must be a JSON object with version=1.")
        profiles = raw.get("profiles")
        if not isinstance(profiles, dict) or not profiles:
            raise ToolsetConfigError("Toolset config must define at least one profile.")

        normalized: Dict[str, Any] = {
            "version": 1,
            "default_profile": self._valid_name(raw.get("default_profile", "default"), "default_profile"),
            "profiles": {},
            "platform_profiles": {},
            "role_profiles": {},
            "limits": {},
        }

        for profile_name, value in profiles.items():
            name = self._valid_name(profile_name, "profile name")
            if not isinstance(value, dict):
                raise ToolsetConfigError(f"Profile '{name}' must be an object.")
            profile: Dict[str, Any] = {}
            if value.get("extends") is not None:
                profile["extends"] = self._valid_name(value["extends"], f"{name}.extends")
            for field in ("enabled_toolsets", "disabled_toolsets", "disabled_tools"):
                entries = value.get(field, [])
                if not isinstance(entries, list) or any(not isinstance(item, str) for item in entries):
                    raise ToolsetConfigError(f"Profile '{name}.{field}' must be a list of strings.")
                clean = [item.strip() for item in entries if item.strip()]
                if field in ("enabled_toolsets", "disabled_toolsets"):
                    unknown = sorted(set(clean) - set(BUILTIN_TOOLSETS))
                    if unknown:
                        raise ToolsetConfigError(f"Profile '{name}' references unknown toolsets: {', '.join(unknown)}")
                profile[field] = sorted(set(clean))
            normalized["profiles"][name] = profile

        if normalized["default_profile"] not in normalized["profiles"]:
            raise ToolsetConfigError("default_profile does not exist.")

        for section in ("platform_profiles", "role_profiles"):
            values = raw.get(section, {})
            if not isinstance(values, dict):
                raise ToolsetConfigError(f"{section} must be an object.")
            for key, profile_name in values.items():
                clean_key = self._valid_name(key, f"{section} key")
                clean_profile = self._valid_name(profile_name, f"{section}.{clean_key}")
                if clean_profile not in normalized["profiles"]:
                    raise ToolsetConfigError(f"{section}.{clean_key} references unknown profile '{clean_profile}'.")
                normalized[section][clean_key] = clean_profile

        limits = raw.get("limits", {})
        if not isinstance(limits, dict):
            raise ToolsetConfigError("limits must be an object.")
        defaults = _default_config()["limits"]
        for key, default in defaults.items():
            value = limits.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ToolsetConfigError(f"limits.{key} must be an integer.")
            minimum = 1
            maximum = 50 if key == "subagent_max_steps" else (3600 if key == "subagent_timeout_seconds" else 16)
            if not minimum <= value <= maximum:
                raise ToolsetConfigError(f"limits.{key} must be between {minimum} and {maximum}.")
            normalized["limits"][key] = value

        # Validate inheritance up front so bad profiles never partially apply.
        for name in normalized["profiles"]:
            self._resolve_profile_from(normalized, name)
        return normalized

    @staticmethod
    def _resolve_profile_from(config_data: Dict[str, Any], name: str, stack: Optional[Set[str]] = None):
        stack = set(stack or ())
        if name in stack:
            raise ToolsetConfigError(f"Profile inheritance cycle detected at '{name}'.")
        profile = config_data["profiles"].get(name)
        if profile is None:
            raise ToolsetConfigError(f"Unknown toolset profile '{name}'.")
        stack.add(name)
        parent = profile.get("extends")
        if parent:
            base = ToolsetManager._resolve_profile_from(config_data, parent, stack)
            enabled = set(base["enabled_toolsets"])
            disabled_tools = set(base["disabled_tools"])
        else:
            enabled = set()
            disabled_tools = set()

        enabled.update(profile.get("enabled_toolsets", []))
        enabled.difference_update(profile.get("disabled_toolsets", []))
        disabled_tools.update(profile.get("disabled_tools", []))
        return {
            "name": name,
            "enabled_toolsets": sorted(enabled),
            "disabled_tools": sorted(disabled_tools),
        }

    def resolve_profile(self, profile: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            selected = profile or self.default_profile
            return copy.deepcopy(self._resolve_profile_from(self._config, selected))

    def profile_for_platform(self, platform: str) -> str:
        with self._lock:
            return self._config["platform_profiles"].get(platform.strip().lower(), self.default_profile)

    def profile_for_role(self, role: str) -> str:
        with self._lock:
            roles = self._config["role_profiles"]
            return roles.get(role.strip().lower(), roles.get("leaf", "researcher"))

    def apply(self, registry: Any, profile: Optional[str] = None) -> Dict[str, Any]:
        resolved = self.resolve_profile(profile)
        registry.set_toolset_policy(
            enabled_toolsets=resolved["enabled_toolsets"],
            disabled_tools=resolved["disabled_tools"],
        )
        return resolved

    def list_profiles(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                self.resolve_profile(name)
                for name in sorted(self._config["profiles"])
            ]

    def set_default_profile(self, profile: str) -> None:
        with self._lock:
            self.resolve_profile(profile)
            self._config["default_profile"] = profile
            self._save()

    def set_toolset(self, profile: str, toolset: str, enabled: bool) -> Dict[str, Any]:
        profile = self._valid_name(profile, "profile")
        toolset = self._valid_name(toolset, "toolset")
        if toolset not in BUILTIN_TOOLSETS:
            raise ToolsetConfigError(f"Unknown toolset '{toolset}'.")
        with self._lock:
            if profile not in self._config["profiles"]:
                raise ToolsetConfigError(f"Unknown profile '{profile}'.")
            target = self._config["profiles"][profile]
            enabled_set = set(target.get("enabled_toolsets", []))
            disabled_set = set(target.get("disabled_toolsets", []))
            if enabled:
                enabled_set.add(toolset)
                disabled_set.discard(toolset)
            else:
                enabled_set.discard(toolset)
                disabled_set.add(toolset)
            target["enabled_toolsets"] = sorted(enabled_set)
            target["disabled_toolsets"] = sorted(disabled_set)
            resolved = self.resolve_profile(profile)
            self._save()
            return resolved

    def set_platform_profile(self, platform: str, profile: str) -> None:
        platform = self._valid_name(platform.lower(), "platform")
        self.resolve_profile(profile)
        with self._lock:
            self._config["platform_profiles"][platform] = profile
            self._save()

    def set_role_profile(self, role: str, profile: str) -> None:
        role = self._valid_name(role.lower(), "role")
        self.resolve_profile(profile)
        with self._lock:
            self._config["role_profiles"][role] = profile
            self._save()

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self._config, indent=2, ensure_ascii=False) + "\n"
        fd, name = tempfile.mkstemp(prefix=".toolsets.", suffix=".tmp", dir=str(self.config_path.parent))
        temp_path = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.config_path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
