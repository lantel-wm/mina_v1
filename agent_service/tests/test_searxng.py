from __future__ import annotations

import json
import urllib.request

from mina_agent.searxng import SearxngClient


def test_searxng_bypasses_proxy_for_loopback(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_build_opener(*handlers):  # noqa: ANN001, ANN202
        calls.append(handlers)
        return object()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    SearxngClient("http://127.0.0.1:8888")

    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert isinstance(calls[0][0], urllib.request.ProxyHandler)


def test_searxng_uses_default_proxy_config_for_remote_hosts(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_build_opener(*handlers):  # noqa: ANN001, ANN202
        calls.append(handlers)
        return object()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    SearxngClient("https://search.example.test")

    assert calls == [()]


def test_searxng_health_uses_short_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def read(self) -> bytes:
            return json.dumps({"results": [{"title": "Minecraft", "url": "https://example.com", "content": "ok"}]}).encode("utf-8")

    class FakeOpener:
        def open(self, request, timeout: float):  # noqa: ANN001, ANN201
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: FakeOpener())
    client = SearxngClient("http://127.0.0.1:8888", timeout_seconds=8.0, health_timeout_seconds=0.25)

    assert client.health()["ok"] is True
    assert captured["timeout"] == 0.25
    assert "format=json" in str(captured["url"])


def test_searxng_preserves_result_snippet_without_client_side_clipping(monkeypatch) -> None:
    long_content = "detail " * 180 + "MinaE2E-Search-Deep-Tail"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"results": [{"title": "Long", "url": "https://example.com/long", "content": long_content}]}
            ).encode("utf-8")

    class FakeOpener:
        def open(self, request, timeout: float):  # noqa: ANN001, ANN201, ARG002
            return FakeResponse()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: FakeOpener())
    client = SearxngClient("http://127.0.0.1:8888")

    results = client.search("long", max_results=1)

    assert results[0]["content"].endswith("MinaE2E-Search-Deep-Tail")
