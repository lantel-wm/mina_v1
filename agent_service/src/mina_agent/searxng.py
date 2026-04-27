from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


class SearxngClient:
    def __init__(self, base_url: str, timeout_seconds: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        try:
            self.search("minecraft", max_results=1)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001 - health endpoint should report all failures.
            return {"ok": False, "error": str(exc)}

    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        params = urllib.parse.urlencode({"q": query, "format": "json"})
        url = f"{self.base_url}/search?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "mina-agent/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
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
                    "content": str(item.get("content") or "")[:800],
                }
            )
            if len(results) >= max_results:
                break
        return results

