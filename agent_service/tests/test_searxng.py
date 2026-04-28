from __future__ import annotations

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
