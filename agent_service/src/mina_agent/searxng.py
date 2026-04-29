from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


class SearxngClient:
    def __init__(self, base_url: str, timeout_seconds: float = 8.0, health_timeout_seconds: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.health_timeout_seconds = health_timeout_seconds
        self._opener = _build_opener(self.base_url)

    def health(self) -> dict[str, Any]:
        try:
            self._search("minecraft", max_results=1, timeout_seconds=min(self.timeout_seconds, self.health_timeout_seconds))
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001 - health endpoint should report all failures.
            return {"ok": False, "error": str(exc)}

    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        return self._search(query, max_results=max_results, timeout_seconds=self.timeout_seconds)

    def _search(self, query: str, max_results: int, timeout_seconds: float) -> list[dict[str, str]]:
        params = urllib.parse.urlencode({"q": query, "format": "json"})
        url = f"{self.base_url}/search?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "mina-agent/0.1"})
        with self._opener.open(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        seen: set[str] = set()
        results: list[dict[str, str]] = []
        for item in payload.get("results", []):
            link = str(item.get("url") or "")
            if not link or link in seen:
                continue
            seen.add(link)
            results.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": link,
                    "content": str(item.get("content") or ""),
                }
            )
            if len(results) >= max_results:
                break
        return results


def _build_opener(base_url: str):
    if _is_loopback(base_url):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _is_loopback(base_url: str) -> bool:
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host == "localhost" or host == "::1" or host.startswith("127.")
