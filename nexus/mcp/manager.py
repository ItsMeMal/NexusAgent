"""
nexus/mcp/manager.py

Full MCP (Model Context Protocol) stdio transport implementation.
Supports spawning MCP servers as subprocesses, JSON-RPC 2.0 handshake,
tool discovery via tools/list, and tool execution via tools/call.

Config file locations (searched in order):
  .mcp.json               — workspace root (Claude Code compatible)
  mcp.json                — workspace root
  mcp_servers.json        — workspace root
  ~/.nexus/mcp.json       — global Nexus config
  ~/.nexus/mcp_servers.json
  ~/.agents/mcp.json      — shared agents convention
  ~/.config/nexus/mcp.json
  <codebase>/.mcp.json
  <codebase>/mcp_servers.json

Format (.mcp.json):
  {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": { "OPTIONAL_VAR": "value" }
      }
    }
  }
"""

import json
import asyncio
import os
import sys
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..tools.base import Tool, ToolRegistry
from ..config import config

logger = logging.getLogger("nexus.mcp")


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    active: bool = True


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
                # Skip non-JSON log lines emitted to stdout by noisy servers
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
                # Ignore server notifications / unrelated messages
            raise TimeoutError(f"MCP server '{self.cfg.name}' never replied to request {req_id}")

    async def start(self) -> List[Dict[str, Any]]:
        """
        Spawn subprocess, run initialize handshake, fetch tools/list.
        Returns the list of tool descriptors [{name, description, inputSchema}].
        """
        env = {**os.environ, **self.cfg.env}

        # Resolve command on Windows (npx.cmd, uvx.cmd, etc.)
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
            limit=10 * 1024 * 1024,  # 10 MB line buffer for large MCP tool responses
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


class MCPManager:
    """Manages all MCP server configs, live stdio sessions, and tool registration."""

    def __init__(
        self,
        workspace_dir: Path = config.WORKSPACE_DIR,
        codebase_dir: Path = config.CODEBASE_DIR,
    ):
        self.workspace_dir = workspace_dir
        self.codebase_dir = codebase_dir
        self.servers: Dict[str, MCPServerConfig] = {}
        self._sessions: Dict[str, MCPSession] = {}
        self._errors: Dict[str, str] = {}
        self._registered_tools: List[Tool] = []
        self._load_configs()

    def _get_config_files(self) -> List[Path]:
        home = Path.home()
        candidates = [
            self.workspace_dir / ".mcp.json",
            self.workspace_dir / "mcp.json",
            self.workspace_dir / "mcp_servers.json",
            home / ".nexus" / "mcp.json",
            home / ".nexus" / "mcp_servers.json",
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
                        self.servers[s_name] = MCPServerConfig(
                            name=s_name,
                            command=s_info.get("command", ""),
                            args=list(s_info.get("args", []) or []),
                            env=dict(s_info.get("env", {}) or {}),
                            active=active,
                        )
            except Exception as e:
                logger.warning(f"Failed to load MCP config {cfg_path}: {e}")

    def list_servers(self) -> List[MCPServerConfig]:
        return list(self.servers.values())

    async def start_all(self) -> Dict[str, List[str]]:
        """
        Spawn all configured active MCP servers, run initialize + tools/list.
        Returns {server_name: [tool_name, ...]} for each server started.
        """
        results: Dict[str, List[str]] = {}
        self._errors.clear()
        for name, cfg in self.servers.items():
            if not cfg.active:
                continue
            if not cfg.command:
                self._errors[name] = "Missing 'command' (only stdio MCP servers are supported)"
                continue
            try:
                session = MCPSession(cfg)
                tools = await session.start()
                self._sessions[name] = session
                results[name] = [t.get("name", "?") for t in tools]
                logger.info(f"[MCP] {name}: started, {len(tools)} tool(s)")
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
        self.servers.clear()
        self._errors.clear()
        self._registered_tools.clear()
        self._load_configs()
        started = await self.start_all()
        self.register_mcp_tools(registry)
        return started

    def register_mcp_tools(self, registry: ToolRegistry):
        """
        Register tools from all running MCP sessions into the agent's ToolRegistry.
        If sessions aren't started yet and no event loop is running, probes via stub mode.
        """
        self._registered_tools.clear()
        if self._sessions:
            self._register_live(registry)
        elif self.servers:
            self._register_stubs(registry)

    def _register_live(self, registry: ToolRegistry):
        """Register tools backed by already-running sessions."""
        for server_name, session in self._sessions.items():
            if not session.is_ready:
                continue
            for tool_def in session.tools:
                tool = self._make_tool(server_name, tool_def, session)
                registry.register(tool)
                self._registered_tools.append(tool)

    def _register_stubs(self, registry: ToolRegistry):
        """
        Register tools that spawn the MCP server on-demand per call.
        Used when start_all() hasn't been called.
        """
        for server_name, cfg in self.servers.items():
            if not cfg.active or not cfg.command:
                continue
            try:
                tool_defs = _probe_tools_sync(cfg)
                for tool_def in tool_defs:
                    tool = self._make_stub_tool(server_name, cfg, tool_def)
                    registry.register(tool)
                    self._registered_tools.append(tool)
            except Exception as e:
                self._errors[server_name] = str(e)
                logger.warning(f"[MCP] {server_name}: probe failed — {e}")

    def _make_tool(self, server_name: str, tool_def: Dict[str, Any], session: MCPSession) -> Tool:
        """Create a Tool backed by a live MCPSession (with auto-restart if crashed)."""
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
        """Create a Tool that spawns the MCP server on-demand per call."""
        tname = tool_def.get("name", "unknown")
        tdesc = tool_def.get("description") or f"MCP tool '{tname}' from {server_name}"
        tschema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}

        async def handler(**kwargs):
            session = MCPSession(cfg)
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
            rows.append({
                "name": name,
                "command": f"{cfg.command} {' '.join(cfg.args)}".strip(),
                "status": status,
                "tools": len(tool_names),
                "tool_names": tool_names,
                "error": err,
                "active": cfg.active,
            })
        return rows


def _probe_tools_sync(cfg: MCPServerConfig) -> List[Dict[str, Any]]:
    """
    Synchronously probe an MCP server for its tool list.
    Runs a fresh event loop so it's safe to call from non-async context.
    """
    async def _run():
        session = MCPSession(cfg)
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
