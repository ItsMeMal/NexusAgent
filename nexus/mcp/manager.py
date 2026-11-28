"""
nexus/mcp/manager.py

Full MCP (Model Context Protocol) transport implementation supporting:
  1. Local stdio subprocesses (command + args + env)
  2. Remote Streamable HTTP & Legacy HTTP+SSE servers (url + headers)

Config file locations (searched in order):
  .mcp.json               — workspace root (Claude Code compatible)
  mcp.json                — workspace root
  mcp_servers.json        — workspace root
  ~/.nolthira/mcp.json   — global Nolthira config
  ~/.nolthira/mcp_servers.json
  ~/.agents/mcp.json      — shared agents convention
  ~/.config/nexus/mcp.json
  <codebase>/.mcp.json
  <codebase>/mcp_servers.json
"""

import json
import asyncio
import os
import re
import sys
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from ..tools.base import Tool, ToolRegistry
from ..config import config

logger = logging.getLogger("nexus.mcp")

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env_str(val: str) -> str:
    """Expand ${ENV_VAR} placeholders using os.environ when present."""
    if not isinstance(val, str) or "${" not in val:
        return val
    return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), val)


def _format_mcp_tool_result(result: Optional[Dict[str, Any]]) -> str:
    """Convert MCP tools/call response payload into text for the LLM."""
    is_error = bool((result or {}).get("isError", False))
    content_blocks = (result or {}).get("content", [])
    if not content_blocks:
        return "(MCP error: empty response)" if is_error else "(no output)"

    parts = []
    for block in content_blocks:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        btype = block.get("type", "text")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "image":
            parts.append(f"[image: {block.get('mimeType', '?')}]")
        elif btype == "resource":
            res = block.get("resource", {})
            uri = res.get("uri", "?")
            text = res.get("text")
            parts.append(f"[resource: {uri}]\n{text}" if text else f"[resource: {uri}]")
        else:
            parts.append(str(block))
    output = "\n".join(parts)
    return f"❌ MCP Tool Error:\n{output}" if is_error else output


@dataclass
class MCPServerConfig:
    name: str
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"  # "stdio" | "http" | "sse"
    active: bool = True
    source_path: Optional[Path] = None

    @property
    def is_remote(self) -> bool:
        return bool(self.url) or self.transport in ("http", "sse")


class MCPSession:
    """
    Manages a single MCP server subprocess over stdio (JSON-RPC 2.0).
    Lifecycle: spawn -> initialize -> tools/list -> [tools/call ...] -> terminate
    """

    def __init__(self, cfg: MCPServerConfig):
        self.cfg = cfg
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0
        self._tools: List[Dict[str, Any]] = []
        self._ready = False
        self._lock = asyncio.Lock()

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _send(self, method: str, params: Any = None) -> int:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError(f"MCP server '{self.cfg.name}' stdin is not available")
        req_id = self._next_id()
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        raw = (json.dumps(msg) + "\n").encode("utf-8")
        self._proc.stdin.write(raw)
        await self._proc.stdin.drain()
        return req_id

    async def _read_stderr_snippet(self) -> str:
        if not self._proc or not self._proc.stderr:
            return ""
        try:
            data = await asyncio.wait_for(self._proc.stderr.read(1024), timeout=0.5)
            return data.decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    async def _recv(self, timeout: float = 15.0) -> Dict[str, Any]:
        """Read one newline-delimited JSON-RPC message from stdout."""
        if not self._proc or not self._proc.stdout:
            raise RuntimeError(f"MCP server '{self.cfg.name}' stdout is not available")
        while True:
            try:
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"MCP server '{self.cfg.name}' did not respond in {timeout}s")
            if not line:
                err_hint = await self._read_stderr_snippet()
                detail = f" ({err_hint})" if err_hint else ""
                raise EOFError(f"MCP server '{self.cfg.name}' closed stdout unexpectedly{detail}")
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                logger.debug(f"[MCP:{self.cfg.name}] non-JSON stdout skipped: {text[:120]}")
                continue

    async def _rpc(self, method: str, params: Any = None, timeout: float = 15.0) -> Any:
        """Send a JSON-RPC request and return the result (raises on error)."""
        async with self._lock:
            req_id = await self._send(method, params)
            for _ in range(50):
                resp = await self._recv(timeout=timeout)
                if resp.get("id") == req_id:
                    if "error" in resp and resp["error"] is not None:
                        err = resp["error"]
                        raise RuntimeError(
                            f"MCP error ({err.get('code')}): {err.get('message')}"
                        )
                    return resp.get("result")
            raise TimeoutError(f"MCP server '{self.cfg.name}' never replied to request {req_id}")

    async def start(self) -> List[Dict[str, Any]]:
        """Spawn subprocess, run initialize handshake, fetch tools/list."""
        expanded_env = {k: _expand_env_str(v) for k, v in self.cfg.env.items()}
        env = {**os.environ, **expanded_env}

        cmd = self.cfg.command
        if sys.platform == "win32" and not Path(cmd).is_absolute():
            for ext in ("", ".cmd", ".exe", ".bat"):
                found = shutil.which(cmd + ext)
                if found:
                    cmd = found
                    break

        self._proc = await asyncio.create_subprocess_exec(
            cmd, *self.cfg.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=10 * 1024 * 1024,
        )

        try:
            await self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "nexus-agent", "version": "1.0.0"},
            }, timeout=20.0)

            init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self._proc.stdin.write((json.dumps(init_notif) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()

            result = await self._rpc("tools/list", {}, timeout=15.0)
            self._tools = (result or {}).get("tools", [])
            self._ready = True
            return self._tools
        except Exception:
            await self.stop()
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool via tools/call and return string result."""
        result = await self._rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        }, timeout=60.0)
        return _format_mcp_tool_result(result)

    async def stop(self):
        """Terminate the subprocess cleanly."""
        self._ready = False
        if self._proc and self._proc.returncode is None:
            try:
                if self._proc.stdin and not self._proc.stdin.is_closing():
                    self._proc.stdin.close()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except Exception:
                try:
                    self._proc.kill()
                    await self._proc.wait()
                except Exception:
                    pass
        self._proc = None

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return self._tools

    @property
    def is_ready(self) -> bool:
        return self._ready and self._proc is not None and self._proc.returncode is None


class MCPRemoteSession:
    """
    Manages a remote MCP server over Streamable HTTP (2025-03-26) or Legacy HTTP+SSE (2024-11-05).
    Automatically negotiates Streamable HTTP first and falls back to Legacy SSE if needed.
    """

    def __init__(self, cfg: MCPServerConfig):
        self.cfg = cfg
        self._client: Optional[httpx.AsyncClient] = None
        self._req_id = 0
        self._tools: List[Dict[str, Any]] = []
        self._ready = False
        self._lock = asyncio.Lock()

        # Streamable HTTP session ID
        self._mcp_session_id: Optional[str] = None

        # Legacy SSE state
        self._sse_mode: bool = (cfg.transport == "sse")
        self._post_url: str = cfg.url
        self._sse_task: Optional[asyncio.Task] = None
        self._endpoint_event: Optional[asyncio.Event] = None
        self._pending: Dict[Any, asyncio.Future] = {}

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        for k, v in (self.cfg.headers or {}).items():
            headers[k] = _expand_env_str(v)
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        return headers

    @staticmethod
    def _parse_sse_json_events(raw_text: str) -> List[Dict[str, Any]]:
        """Extract JSON-RPC objects from an SSE response body."""
        events: List[Dict[str, Any]] = []
        data_lines: List[str] = []
        for line in raw_text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line.strip() == "" and data_lines:
                payload = "\n".join(data_lines).strip()
                data_lines.clear()
                if payload and payload != "[DONE]":
                    try:
                        events.append(json.loads(payload))
                    except json.JSONDecodeError:
                        pass
        if data_lines:
            payload = "\n".join(data_lines).strip()
            if payload and payload != "[DONE]":
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
        return events

    async def _sse_listener(self):
        """Background listener for Legacy HTTP+SSE transport."""
        sse_headers = {k: v for k, v in self._build_headers().items() if k.lower() != "content-type"}
        sse_headers["Accept"] = "text/event-stream"
        try:
            async with self._client.stream("GET", self.cfg.url, headers=sse_headers, timeout=None) as resp:
                resp.raise_for_status()
                event_type = "message"
                data_buf: List[str] = []
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buf.append(line[5:].lstrip())
                    elif line.strip() == "" and data_buf:
                        payload = "\n".join(data_buf).strip()
                        data_buf.clear()
                        if event_type == "endpoint":
                            self._post_url = urljoin(self.cfg.url, payload)
                            if self._endpoint_event:
                                self._endpoint_event.set()
                        else:
                            try:
                                msg = json.loads(payload)
                                msg_id = msg.get("id")
                                if msg_id is not None and msg_id in self._pending:
                                    fut = self._pending.pop(msg_id)
                                    if not fut.done():
                                        fut.set_result(msg)
                            except json.JSONDecodeError:
                                pass
                        event_type = "message"
        except asyncio.CancelledError:
            pass
        except Exception as e:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError(f"SSE stream error: {e}"))
            self._pending.clear()
            if self._endpoint_event and not self._endpoint_event.is_set():
                self._endpoint_event.set()

    async def _start_legacy_sse(self):
        """Open GET SSE stream and wait for POST endpoint URL."""
        self._sse_mode = True
        self._endpoint_event = asyncio.Event()
        self._sse_task = asyncio.create_task(self._sse_listener())
        try:
            await asyncio.wait_for(self._endpoint_event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Remote SSE server '{self.cfg.name}' did not send endpoint event")
        if self._post_url == self.cfg.url and self._sse_task.done():
            exc = self._sse_task.exception() if not self._sse_task.cancelled() else None
            raise RuntimeError(f"Remote SSE connection failed: {exc or 'closed'}")

    async def _post_rpc(self, payload: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Send JSON-RPC POST and return matching response object (None for notifications)."""
        req_id = payload.get("id")
        fut: Optional[asyncio.Future] = None
        if self._sse_mode and req_id is not None:
            fut = asyncio.get_running_loop().create_future()
            self._pending[req_id] = fut

        try:
            resp = await self._client.post(
                self._post_url,
                headers=self._build_headers(),
                json=payload,
                timeout=timeout,
            )
        except Exception:
            if req_id is not None:
                self._pending.pop(req_id, None)
            raise

        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self._mcp_session_id = sid

        if resp.status_code in (202, 204):
            if fut is not None:
                return await asyncio.wait_for(fut, timeout=timeout)
            return None

        if resp.status_code >= 400:
            if req_id is not None:
                self._pending.pop(req_id, None)
            body_preview = resp.text[:250].strip()
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code} from MCP server '{self.cfg.name}': {body_preview}",
                request=resp.request,
                response=resp,
            )

        ctype = resp.headers.get("content-type", "").lower()
        if "text/event-stream" in ctype:
            if req_id is not None:
                self._pending.pop(req_id, None)
            events = self._parse_sse_json_events(resp.text)
            for ev in events:
                if ev.get("id") == req_id:
                    return ev
            return events[-1] if events else None

        if resp.text.strip():
            if req_id is not None:
                self._pending.pop(req_id, None)
            return resp.json()

        if fut is not None:
            return await asyncio.wait_for(fut, timeout=timeout)
        return None

    async def _rpc(self, method: str, params: Any = None, timeout: float = 30.0) -> Any:
        async with self._lock:
            req_id = self._next_id()
            payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params
            resp = await self._post_rpc(payload, timeout=timeout)
            if resp and "error" in resp and resp["error"] is not None:
                err = resp["error"]
                raise RuntimeError(f"MCP error ({err.get('code')}): {err.get('message')}")
            return (resp or {}).get("result")

    async def start(self) -> List[Dict[str, Any]]:
        """Connect to remote MCP server, run initialize handshake, fetch tools/list."""
        self._client = httpx.AsyncClient(follow_redirects=True, timeout=30.0)
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "nexus-agent", "version": "1.0.0"},
        }
        try:
            if self._sse_mode:
                await self._start_legacy_sse()
                await self._rpc("initialize", init_params, timeout=20.0)
            else:
                try:
                    await self._rpc("initialize", init_params, timeout=20.0)
                except httpx.HTTPStatusError as e:
                    # Fallback to Legacy SSE when endpoint rejects POST with 404/405
                    if e.response is not None and e.response.status_code in (404, 405):
                        await self._start_legacy_sse()
                        await self._rpc("initialize", init_params, timeout=20.0)
                    else:
                        raise

            # Best-effort initialized notification
            try:
                await self._post_rpc(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    timeout=10.0,
                )
            except Exception:
                pass

            result = await self._rpc("tools/list", {}, timeout=20.0)
            self._tools = (result or {}).get("tools", [])
            self._ready = True
            return self._tools
        except Exception:
            await self.stop()
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool via remote tools/call."""
        result = await self._rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        }, timeout=60.0)
        return _format_mcp_tool_result(result)

    async def stop(self):
        """Close HTTP client and any SSE listener task."""
        self._ready = False
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except (asyncio.CancelledError, Exception):
                pass
        self._sse_task = None
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return self._tools

    @property
    def is_ready(self) -> bool:
        return self._ready and self._client is not None


class MCPManager:
    """Manages all MCP server configs, live stdio/HTTP/SSE sessions, and tool registration."""

    def __init__(
        self,
        workspace_dir: Path = config.WORKSPACE_DIR,
        codebase_dir: Path = config.CODEBASE_DIR,
    ):
        self.workspace_dir = workspace_dir
        self.codebase_dir = codebase_dir
        self.servers: Dict[str, MCPServerConfig] = {}
        self._sessions: Dict[str, Any] = {}
        self._errors: Dict[str, str] = {}
        self._registered_tools: List[Tool] = []
        self._load_configs()

    def _get_config_files(self) -> List[Path]:
        home = Path.home()
        candidates = [
            self.workspace_dir / ".mcp.json",
            self.workspace_dir / "mcp.json",
            self.workspace_dir / "mcp_servers.json",
            config.NOLTHIRA_HOME / "mcp.json",
            config.NOLTHIRA_HOME / "mcp_servers.json",
            home / ".agents" / "mcp.json",
            home / ".config" / "nexus" / "mcp.json",
            self.codebase_dir / ".mcp.json",
            self.codebase_dir / "mcp_servers.json",
        ]
        seen = set()
        result: List[Path] = []
        for p in candidates:
            try:
                rp = p.resolve()
            except Exception:
                rp = p
            if rp not in seen and p.exists():
                seen.add(rp)
                result.append(p)
        return result

    def _load_configs(self):
        for cfg_path in self._get_config_files():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                servers_dict = data.get("mcpServers", data.get("servers", {}))
                if not isinstance(servers_dict, dict):
                    continue
                for s_name, s_info in servers_dict.items():
                    if isinstance(s_info, dict) and s_name not in self.servers:
                        active = (not s_info.get("disabled", False)) and bool(s_info.get("active", True))
                        url = str(s_info.get("url", "") or "").strip()
                        raw_type = str(s_info.get("type") or s_info.get("transport") or "").lower().strip()
                        if url:
                            transport = "sse" if raw_type == "sse" else "http"
                        else:
                            transport = "stdio"
                        self.servers[s_name] = MCPServerConfig(
                            name=s_name,
                            command=str(s_info.get("command", "") or ""),
                            args=list(s_info.get("args", []) or []),
                            env=dict(s_info.get("env", {}) or {}),
                            url=url,
                            headers=dict(s_info.get("headers", {}) or {}),
                            transport=transport,
                            active=active,
                            source_path=cfg_path,
                        )
            except Exception as e:
                logger.warning(f"Failed to load MCP config {cfg_path}: {e}")

    def list_servers(self) -> List[MCPServerConfig]:
        return list(self.servers.values())

    def _create_session(self, cfg: MCPServerConfig):
        if cfg.is_remote:
            return MCPRemoteSession(cfg)
        return MCPSession(cfg)

    def add_server_to_config(
        self,
        cfg: MCPServerConfig,
        scope: str = "global",
    ) -> Path:
        """Persist an MCP server entry to ~/.nolthira/mcp.json (global) or .mcp.json (workspace)."""
        if scope == "workspace":
            target_path = self.workspace_dir / ".mcp.json"
        else:
            target_path = config.NOLTHIRA_HOME / "mcp.json"

        target_path.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {"mcpServers": {}}
        if target_path.exists():
            try:
                loaded = json.loads(target_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                pass

        key = "mcpServers" if "mcpServers" in data or "servers" not in data else "servers"
        if not isinstance(data.get(key), dict):
            data[key] = {}

        entry: Dict[str, Any] = {}
        if cfg.is_remote:
            entry["type"] = cfg.transport if cfg.transport in ("http", "sse") else "http"
            entry["url"] = cfg.url
            if cfg.headers:
                entry["headers"] = cfg.headers
        else:
            entry["command"] = cfg.command
            if cfg.args:
                entry["args"] = cfg.args
            if cfg.env:
                entry["env"] = cfg.env

        data[key][cfg.name] = entry
        target_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        cfg.source_path = target_path
        self.servers[cfg.name] = cfg
        return target_path

    async def remove_server(self, name: str, registry: Optional[ToolRegistry] = None) -> bool:
        """Stop an MCP server session and remove it from all config files and registry."""
        existed = name in self.servers
        session = self._sessions.pop(name, None)
        if session:
            await session.stop()

        self.servers.pop(name, None)
        self._errors.pop(name, None)

        prefix = f"mcp_{name}_"
        self._registered_tools = [t for t in self._registered_tools if not t.name.startswith(prefix)]
        if registry and hasattr(registry, "_tools"):
            for key in [key for key in list(registry._tools.keys()) if key.startswith(prefix)]:
                registry._tools.pop(key, None)
                getattr(registry, "_toolsets", {}).pop(key, None)

        removed_from_disk = False
        for cfg_path in self._get_config_files():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                changed = False
                for key in ("mcpServers", "servers"):
                    if isinstance(data.get(key), dict) and name in data[key]:
                        del data[key][name]
                        changed = True
                if changed:
                    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    removed_from_disk = True
            except Exception:
                pass

        return existed or removed_from_disk

    async def start_all(self) -> Dict[str, List[str]]:
        """Spawn/connect all configured active MCP servers and fetch tools/list."""
        results: Dict[str, List[str]] = {}
        self._errors.clear()
        for name, cfg in self.servers.items():
            if not cfg.active:
                continue
            if not cfg.command and not cfg.url:
                self._errors[name] = "Missing 'command' or 'url' in MCP server config"
                continue
            try:
                session = self._create_session(cfg)
                tools = await session.start()
                self._sessions[name] = session
                results[name] = [t.get("name", "?") for t in tools]
                logger.info(f"[MCP] {name}: started ({cfg.transport}), {len(tools)} tool(s)")
            except Exception as e:
                self._errors[name] = str(e)
                logger.warning(f"[MCP] {name}: failed to start — {e}")
        return results

    async def stop_all(self):
        """Terminate all running MCP sessions."""
        for session in list(self._sessions.values()):
            await session.stop()
        self._sessions.clear()

    async def reload(self, registry: ToolRegistry) -> Dict[str, List[str]]:
        """Reload configs from disk, restart MCP servers, and re-register tools."""
        await self.stop_all()
        if hasattr(registry, "_tools"):
            for key in [key for key in list(registry._tools.keys()) if key.startswith("mcp_")]:
                registry._tools.pop(key, None)
                getattr(registry, "_toolsets", {}).pop(key, None)
        self.servers.clear()
        self._errors.clear()
        self._registered_tools.clear()
        self._load_configs()
        started = await self.start_all()
        self.register_mcp_tools(registry)
        return started

    def register_mcp_tools(self, registry: ToolRegistry):
        """Register tools from running MCP sessions (or stub mode fallback) into ToolRegistry."""
        self._registered_tools.clear()
        if self._sessions:
            self._register_live(registry)
        elif self.servers:
            self._register_stubs(registry)

    def _register_live(self, registry: ToolRegistry):
        for server_name, session in self._sessions.items():
            if not session.is_ready:
                continue
            for tool_def in session.tools:
                tool = self._make_tool(server_name, tool_def, session)
                registry.register(tool, toolset="mcp")
                self._registered_tools.append(tool)

    def _register_stubs(self, registry: ToolRegistry):
        for server_name, cfg in self.servers.items():
            if not cfg.active or (not cfg.command and not cfg.url):
                continue
            try:
                tool_defs = _probe_tools_sync(cfg)
                for tool_def in tool_defs:
                    tool = self._make_stub_tool(server_name, cfg, tool_def)
                    registry.register(tool, toolset="mcp")
                    self._registered_tools.append(tool)
            except Exception as e:
                self._errors[server_name] = str(e)
                logger.warning(f"[MCP] {server_name}: probe failed — {e}")

    def _make_tool(self, server_name: str, tool_def: Dict[str, Any], session: Any) -> Tool:
        tname = tool_def.get("name", "unknown")
        tdesc = tool_def.get("description") or f"MCP tool '{tname}' from {server_name}"
        tschema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}

        async def handler(**kwargs):
            try:
                if not session.is_ready:
                    await session.start()
                return await session.call_tool(tname, kwargs)
            except Exception as e:
                return f"❌ MCP tool error ({server_name}/{tname}): {e}"

        return Tool(
            name=f"mcp_{server_name}_{tname}",
            description=f"[MCP:{server_name}] {tdesc}",
            parameters=tschema,
            handler=handler,
        )

    def _make_stub_tool(self, server_name: str, cfg: MCPServerConfig, tool_def: Dict[str, Any]) -> Tool:
        tname = tool_def.get("name", "unknown")
        tdesc = tool_def.get("description") or f"MCP tool '{tname}' from {server_name}"
        tschema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}

        async def handler(**kwargs):
            session = self._create_session(cfg)
            try:
                await session.start()
                return await session.call_tool(tname, kwargs)
            except Exception as e:
                return f"❌ MCP tool error ({server_name}/{tname}): {e}"
            finally:
                await session.stop()

        return Tool(
            name=f"mcp_{server_name}_{tname}",
            description=f"[MCP:{server_name}] {tdesc}",
            parameters=tschema,
            handler=handler,
        )

    @property
    def registered_tools(self) -> List[Tool]:
        return self._registered_tools

    def get_status(self) -> List[Dict[str, Any]]:
        """Return live status info for /mcp CLI and gateway commands."""
        rows: List[Dict[str, Any]] = []
        for name, cfg in self.servers.items():
            session = self._sessions.get(name)
            err = self._errors.get(name, "")
            if not cfg.active:
                status = "disabled"
                tool_names: List[str] = []
            elif session and session.is_ready:
                status = "running"
                tool_names = [t.get("name", "?") for t in session.tools]
            elif err:
                status = "error"
                tool_names = []
            else:
                status = "configured"
                tool_names = [
                    t.name[len(f"mcp_{name}_"):]
                    for t in self._registered_tools
                    if t.name.startswith(f"mcp_{name}_")
                ]
            target_desc = cfg.url if cfg.is_remote else f"{cfg.command} {' '.join(cfg.args)}".strip()
            rows.append({
                "name": name,
                "transport": cfg.transport,
                "command": target_desc,
                "status": status,
                "tools": len(tool_names),
                "tool_names": tool_names,
                "error": err,
                "active": cfg.active,
            })
        return rows


def _probe_tools_sync(cfg: MCPServerConfig) -> List[Dict[str, Any]]:
    async def _run():
        session = MCPRemoteSession(cfg) if cfg.is_remote else MCPSession(cfg)
        try:
            return await asyncio.wait_for(session.start(), timeout=20.0)
        finally:
            await session.stop()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    except Exception as e:
        logger.debug(f"[MCP] probe failed for {cfg.name}: {e}")
        return []
    finally:
        try:
            loop.close()
        except Exception:
            pass
