from __future__ import annotations

import json
import sys

from mina_agent.mcp import McpRegistry


def test_stdio_mcp_call_lists_tools_and_reads_resources(tmp_path) -> None:
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion"), "capabilities": {"tools": {}, "resources": {}}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo text"}]}
    elif method == "resources/read":
        result = {"contents": [{"uri": params.get("uri"), "mimeType": "text/plain", "text": "resource text"}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "echo:" + str((params.get("arguments") or {}).get("text", ""))}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"message": "unknown method"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""",
        encoding="utf-8",
    )
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"servers": {"fake": {"command": sys.executable, "args": [str(script)], "timeout_seconds": 2}}}),
        encoding="utf-8",
    )
    registry = McpRegistry(config)

    tools = registry.list_tools("fake")
    called = registry.call("fake", "echo", {"text": "hello"})
    resource = registry.read_resource("fake", "file:///note.txt")

    assert tools["ok"] is True
    assert tools["tools"][0]["name"] == "echo"
    assert called["ok"] is True
    assert called["content"][0]["text"] == "echo:hello"
    assert resource["ok"] is True
    assert resource["contents"][0]["text"] == "resource text"


def test_http_mcp_call_supports_mcpservers_config_shape(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def read(self) -> bytes:
            payload = captured["payload"]
            assert isinstance(payload, dict)
            response = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"content": [{"type": "text", "text": payload["method"]}]},
            }
            return json.dumps(response).encode("utf-8")

    class FakeOpener:
        def open(self, request, timeout: float):  # noqa: ANN001, ANN201
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

    def fake_build_opener(*args):  # noqa: ANN001, ANN202
        captured["opener_args"] = args
        return FakeOpener()

    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "httpfake": {
                        "transport": "http",
                        "url": "http://127.0.0.1:12345",
                        "timeout_seconds": 2,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    registry = McpRegistry(config)

    result = registry.call("httpfake", "echo", {"text": "hello"})

    assert result["ok"] is True
    assert result["content"][0]["text"] == "tools/call"
    assert captured["url"] == "http://127.0.0.1:12345"
    assert captured["timeout"] == 2
    assert captured["payload"] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"text": "hello"}},
    }
    assert captured["opener_args"]


def test_stdio_mcp_timeout_returns_model_visible_error(tmp_path) -> None:
    script = tmp_path / "silent_mcp_server.py"
    script.write_text("import time; time.sleep(5)\n", encoding="utf-8")
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"servers": {"silent": {"command": sys.executable, "args": [str(script)], "timeout_seconds": 0.1}}}),
        encoding="utf-8",
    )
    registry = McpRegistry(config)

    result = registry.call("silent", "echo", {})

    assert result["ok"] is False
    assert "did not respond" in result["error"]


def test_mcp_invalid_timeout_returns_model_visible_error(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"servers": {"bad": {"transport": "http", "url": "http://127.0.0.1:1", "timeout_seconds": "soon"}}}),
        encoding="utf-8",
    )
    registry = McpRegistry(config)

    result = registry.call("bad", "echo", {})

    assert result["ok"] is False
    assert "timeout_seconds must be numeric" in result["error"]


def test_mcp_malformed_config_does_not_crash_registry(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text("{bad", encoding="utf-8")

    registry = McpRegistry(config)

    assert registry.servers == {}
    assert registry.health()["configured"] is False
    assert registry.health()["error"]
