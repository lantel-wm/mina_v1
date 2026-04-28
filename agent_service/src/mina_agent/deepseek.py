from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Settings


class DeepSeekError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class DeepSeekResponse:
    message: dict[str, Any]
    finish_reason: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class DeepSeekClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._opener = _build_opener(settings.base_url)

    def configured(self) -> bool:
        return self.settings.deepseek_configured

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, str] | None = None,
        max_tokens: int = 2048,
    ) -> DeepSeekResponse:
        for attempt in range(3):
            try:
                return self._chat_once(messages, tools, response_format, max_tokens)
            except DeepSeekError as exc:
                if exc.status not in {429, 500, 503} or attempt == 2:
                    raise
                time.sleep(0.5 * (2 ** attempt))
        raise DeepSeekError(500, "unreachable DeepSeek retry state")

    def _chat_once(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, str] | None,
        max_tokens: int,
    ) -> DeepSeekResponse:
        if not self.configured():
            raise DeepSeekError(401, "MINA_API_KEY is not configured")

        body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "thinking": {"type": self.settings.thinking},
            "stream": False,
            "max_tokens": max_tokens,
        }
        if self.settings.thinking == "enabled":
            body["reasoning_effort"] = self.settings.reasoning_effort
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if response_format:
            body["response_format"] = response_format

        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "mina-agent/0.1",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.settings.request_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise DeepSeekError(exc.code, error_body) from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(503, str(exc)) from exc

        choices = payload.get("choices") or []
        if not choices:
            raise DeepSeekError(500, f"DeepSeek response had no choices: {payload!r}")
        choice = choices[0]
        return DeepSeekResponse(
            message=choice.get("message") or {},
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=payload.get("usage") or {},
            raw=payload,
        )


def _build_opener(base_url: str):
    if _is_loopback(base_url):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _is_loopback(base_url: str) -> bool:
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host == "localhost" or host == "::1" or host.startswith("127.")
