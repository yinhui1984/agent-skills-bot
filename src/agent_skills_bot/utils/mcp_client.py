"""Minimal MCP stdio client and manager."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


DEFAULT_PROTOCOL_VERSION = os.environ.get("AGENT_SKILLS_MCP_PROTOCOL", "2025-11-25")
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.agent-skills-bot/mcp.json")


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: List[str]
    env: Dict[str, str]
    type: str = "stdio"


def load_mcp_config() -> Dict[str, MCPServerConfig]:
    path = os.environ.get("AGENT_SKILLS_MCP_CONFIG", DEFAULT_CONFIG_PATH)
    config_path = pathlib.Path(path)
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    results: Dict[str, MCPServerConfig] = {}
    for name, cfg in servers.items():
        command = cfg.get("command")
        args = cfg.get("args", [])
        if not command:
            continue
        env = cfg.get("env", {})
        server_type = cfg.get("type", "stdio")
        results[name] = MCPServerConfig(
            name=name,
            command=command,
            args=list(args),
            env=dict(env),
            type=server_type,
        )
    return results


class MCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        if config.type != "stdio":
            raise RuntimeError(f"Unsupported MCP transport type: {config.type}")
        env = os.environ.copy()
        env.update(config.env)
        self._process = subprocess.Popen(
            [config.command, *config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._next_id = 1
        self._initialized = False
        self._config = config
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._notifications: List[Dict[str, Any]] = []
        self._stderr_lines: List[str] = []
        self._cv = threading.Condition()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._err_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._err_reader.start()
        self._last_activity = time.time()

    def _send(self, payload: Dict[str, Any]) -> None:
        if not self._process.stdin:
            raise RuntimeError("MCP stdin unavailable")
        line = json.dumps(payload, separators=(",", ":"))
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

    def _read_stdout(self) -> None:
        if not self._process.stdout:
            return
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._last_activity = time.time()
            msg_id = msg.get("id")
            if msg_id is not None:
                with self._cv:
                    self._responses[int(msg_id)] = msg
                    self._cv.notify_all()
                continue
            if msg.get("method"):
                with self._cv:
                    self._notifications.append(msg)
                    self._cv.notify_all()

    def _read_stderr(self) -> None:
        if not self._process.stderr:
            return
        for line in self._process.stderr:
            line = line.rstrip("\n")
            if line:
                self._stderr_lines.append(line)

    def _recv(self, request_id: int, timeout: float = 30.0) -> Dict[str, Any]:
        deadline = time.time() + timeout
        with self._cv:
            while time.time() < deadline:
                if request_id in self._responses:
                    return self._responses.pop(request_id)
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._cv.wait(timeout=remaining)
        raise RuntimeError("MCP response timeout")

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params
            self._send(payload)
            return self._recv(req_id)

    def initialize(self) -> None:
        if self._initialized:
            return
        params = {
            "protocolVersion": DEFAULT_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": True}},
            "clientInfo": {"name": "agent-skills-bot", "version": "0.1.0"},
        }
        try:
            response = self._request("initialize", params=params)
            if "error" in response:
                raise RuntimeError(response["error"])
        except Exception:
            # Some servers don't implement initialize; continue for compatibility.
            pass
        self._initialized = True

    def list_tools(self) -> List[Dict[str, Any]]:
        self.initialize()
        response = self._request("tools/list", params={})
        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.initialize()
        response = self._request("tools/call", params={"name": name, "arguments": arguments})
        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result", {})

    def notifications(self) -> List[Dict[str, Any]]:
        with self._cv:
            notes = list(self._notifications)
            self._notifications.clear()
        return notes

    def is_alive(self) -> bool:
        return self._process.poll() is None

    def health_check(self) -> bool:
        if not self.is_alive():
            return False
        try:
            self.list_tools()
            return True
        except Exception:
            return False

    def shutdown(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except Exception:
            if self._process.poll() is None:
                self._process.kill()


class MCPManager:
    def __init__(self) -> None:
        self._configs = load_mcp_config()
        self._clients: Dict[str, MCPClient] = {}

    def servers(self) -> List[str]:
        return sorted(self._configs.keys())

    def get_client(self, name: str) -> MCPClient:
        if name not in self._configs:
            raise RuntimeError(f"MCP server not configured: {name}")
        if name not in self._clients:
            self._clients[name] = MCPClient(self._configs[name])
        elif not self._clients[name].health_check():
            self._clients[name].shutdown()
            self._clients[name] = MCPClient(self._configs[name])
        return self._clients[name]

    def list_tools_all(self) -> Dict[str, List[Dict[str, Any]]]:
        results: Dict[str, List[Dict[str, Any]]] = {}
        for name in self.servers():
            client = self.get_client(name)
            results[name] = client.list_tools()
        return results

    def drain_notifications_all(self) -> Dict[str, List[Dict[str, Any]]]:
        notifications: Dict[str, List[Dict[str, Any]]] = {}
        for server in self.servers():
            try:
                client = self.get_client(server)
                notes = client.notifications()
                if notes:
                    notifications[server] = notes
            except Exception:
                continue
        return notifications


_manager = MCPManager()


def list_mcp_servers() -> List[str]:
    return _manager.servers()


def list_mcp_tools_summary() -> Dict[str, List[str]]:
    tools = _manager.list_tools_all()
    summary: Dict[str, List[str]] = {}
    for server, items in tools.items():
        summary[server] = [tool.get("name", "") for tool in items if tool.get("name")]
    return summary


def list_mcp_tools() -> Dict[str, List[Dict[str, Any]]]:
    return _manager.list_tools_all()


def call_mcp_tool(server: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    client = _manager.get_client(server)
    return client.call_tool(tool, arguments)


def drain_mcp_notifications() -> Dict[str, List[Dict[str, Any]]]:
    return _manager.drain_notifications_all()
