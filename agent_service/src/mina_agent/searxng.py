from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

LOGGER = logging.getLogger("mina_agent.searxng")


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
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError:
            LOGGER.info("searxng timeout query=%s url=%s", query, url)
            return [{"ok": "false", "error": f"search timeout after {timeout_seconds}s"}]
        except OSError as exc:
            LOGGER.info("searxng connection error query=%s error=%s", query, exc)
            return [{"ok": "false", "error": f"search connection error: {exc}"}]
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            LOGGER.info("searxng invalid json query=%s error=%s", query, exc)
            return [{"ok": "false", "error": f"search returned invalid response: {exc}"}]
        seen: set[str] = set()
        results: list[dict[str, str]] = []
        for answer_index, answer in enumerate(_search_answers(payload), start=1):
            source_url = f"{self.base_url}/search?{urllib.parse.urlencode({'q': query})}"
            results.append(
                {
                    "title": f"SearXNG answer {answer_index}",
                    "url": source_url,
                    "content": answer,
                    "source_type": "answer",
                }
            )
            if len(results) >= max_results:
                return results
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
                    "source_type": "result",
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


def _search_answers(payload: dict[str, Any]) -> list[str]:
    answers = payload.get("answers")
    if not isinstance(answers, list):
        return []
    rendered: list[str] = []
    for answer in answers:
        if isinstance(answer, str):
            content = answer.strip()
        elif isinstance(answer, dict):
            content = str(answer.get("answer") or answer.get("content") or answer.get("text") or "").strip()
        else:
            content = ""
        if content:
            rendered.append(content)
    return rendered
