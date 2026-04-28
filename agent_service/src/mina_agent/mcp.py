from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MCP_PROTOCOL_VERSION = "2025-06-18"


class McpRegistry:
    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or Path(os.getenv("MINA_MCP_CONFIG_PATH", "agent_service/config/mcp.json"))
        self.load_error = ""
        self.servers = self._load()

    def health(self) -> dict[str, Any]:
        return {
            "configured": bool(self.servers),
            "servers": sorted(self.servers),
            "error": self.load_error or None,
        }

    def list_tools(self, server: str) -> dict[str, Any]:
        return self._request(server, "tools/list", {})

    def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        return self._request(server, "resources/read", {"uri": uri})

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request(server, "tools/call", {"name": tool, "arguments": arguments})

    def _request(self, server: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if server not in self.servers:
            return {"ok": False, "error": f"MCP server is not configured: {server}"}
        config = self.servers[server]
        transport = str(config.get("transport") or ("http" if config.get("url") else "stdio"))
        try:
            if transport == "stdio":
                return self._stdio_request(config, method, params)
            if transport in {"http", "streamable_http"}:
                return self._http_request(config, method, params)
            return {"ok": False, "error": f"Unsupported MCP transport: {transport}"}
        except (OSError, TimeoutError, ValueError, subprocess.SubprocessError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}

    def _stdio_request(self, config: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
        command = config.get("command")
        args = config.get("args") or []
        if not isinstance(command, str) or not command:
            return {"ok": False, "error": "MCP stdio server requires command"}
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            return {"ok": False, "error": "MCP stdio args must be a string array"}
        env = config.get("env")
        if env is not None and not isinstance(env, dict):
            return {"ok": False, "error": "MCP stdio env must be an object"}
        timeout_seconds = _timeout_seconds(config)
        proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=None if env is None else {**os.environ, **{str(key): str(value) for key, value in env.items()}},
        )
        try:
            self._write_jsonrpc(proc, 1, "initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mina-agent", "version": "0.1.0"},
            })
            init = self._read_jsonrpc(proc, timeout_seconds)
            if "error" in init:
                return {"ok": False, "error": init["error"]}
            self._write_notification(proc, "notifications/initialized", {})
            self._write_jsonrpc(proc, 2, method, params)
            response = self._read_jsonrpc(proc, timeout_seconds)
            return _normalize_response(response)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _http_request(self, config: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = str(config.get("url") or "").rstrip("/")
        if not url:
            return {"ok": False, "error": "MCP HTTP server requires url"}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = config.get("bearer_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(_jsonrpc(1, method, params), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=_timeout_seconds(config)) as response:
            return _normalize_response(json.loads(response.read().decode("utf-8")))

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.config_path.exists():
            return {}
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.load_error = str(exc)
            return {}
        servers = payload.get("servers") or payload.get("mcpServers") or {}
        if not isinstance(servers, dict):
            self.load_error = "MCP config must contain an object at servers or mcpServers"
            return {}
        return {str(name): value for name, value in servers.items() if isinstance(value, dict)}

    @staticmethod
    def _write_jsonrpc(proc: subprocess.Popen[str], request_id: int, method: str, params: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(_jsonrpc(request_id, method, params), ensure_ascii=False) + "\n")
        proc.stdin.flush()

    @staticmethod
    def _write_notification(proc: subprocess.Popen[str], method: str, params: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    @staticmethod
    def _read_jsonrpc(proc: subprocess.Popen[str], timeout_seconds: float) -> dict[str, Any]:
        assert proc.stdout is not None
        lines: queue.Queue[str] = queue.Queue(maxsize=1)

        def read_line() -> None:
            lines.put(proc.stdout.readline())

        threading.Thread(target=read_line, daemon=True).start()
        try:
            line = lines.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError(f"MCP server did not respond within {timeout_seconds:.1f}s") from exc
        if not line:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise OSError(f"MCP server closed stdout: {stderr}")
        payload = json.loads(line)
        return payload if isinstance(payload, dict) else {"error": "MCP response was not an object"}


def _jsonrpc(request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def _normalize_response(response: dict[str, Any]) -> dict[str, Any]:
    if "error" in response:
        return {"ok": False, "error": response["error"]}
    result = response.get("result")
    if isinstance(result, dict):
        normalized = {"ok": not bool(result.get("isError"))}
        normalized.update(result)
        return normalized
    return {"ok": True, "result": result}


def _timeout_seconds(config: dict[str, Any]) -> float:
    try:
        timeout_seconds = float(config.get("timeout_seconds") or 15)
    except (TypeError, ValueError) as exc:
        raise ValueError("MCP timeout_seconds must be numeric") from exc
    if timeout_seconds <= 0:
        raise ValueError("MCP timeout_seconds must be positive")
    return timeout_seconds
