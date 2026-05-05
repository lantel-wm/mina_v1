from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_FETCH_CHARS = 6000
MAX_FETCH_CHARS = 12000
MAX_READ_BYTES = 256_000
FETCH_TIMEOUT_SECONDS = 8.0


def fetch_url(url: str, *, max_chars: int = DEFAULT_FETCH_CHARS, timeout_seconds: float = FETCH_TIMEOUT_SECONDS) -> dict[str, Any]:
    normalized_url, error = _normalize_fetch_url(url)
    if error:
        return {"ok": False, "error": error}
    assert normalized_url is not None
    max_chars = max(1000, min(MAX_FETCH_CHARS, int(max_chars or DEFAULT_FETCH_CHARS)))
    request = urllib.request.Request(
        normalized_url,
        headers={
            "User-Agent": "mina-agent/0.1 (+https://github.com/mina-agent)",
            "Accept": "text/html, text/plain, application/json, application/xml;q=0.9, */*;q=0.1",
        },
    )
    opener = urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = str(getattr(response, "geturl", lambda: normalized_url)())
            content_type = _header_value(response, "Content-Type")
            if content_type and not _is_text_content_type(content_type):
                return {
                    "ok": False,
                    "url": normalized_url,
                    "final_url": final_url,
                    "content_type": content_type,
                    "error": "web_fetch only reads text, HTML, JSON, XML, or Markdown resources",
                }
            raw = response.read(MAX_READ_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": normalized_url, "error": f"HTTP {exc.code}"}
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return {"ok": False, "url": normalized_url, "error": f"web_fetch unavailable: {exc}"}

    charset = _charset_from_content_type(content_type) or "utf-8"
    text = raw[:MAX_READ_BYTES].decode(charset, errors="replace")
    text, title = _normalize_document_text(text, content_type)
    content, content_truncated = _excerpt_with_flag(text, max_chars)
    return {
        "ok": True,
        "url": normalized_url,
        "final_url": final_url,
        "content_type": content_type or "unknown",
        "title": title,
        "content": content,
        "content_truncated": content_truncated or len(raw) > MAX_READ_BYTES,
        "untrusted_content": True,
    }


def _normalize_fetch_url(value: str) -> tuple[str | None, str | None]:
    url = str(value or "").strip()
    if not url:
        return None, "web_fetch url is required"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None, "web_fetch only supports http and https URLs"
    if parsed.username or parsed.password:
        return None, "web_fetch does not allow credentials in URLs"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None, "web_fetch URL must include a hostname"
    if _blocked_fetch_host(host):
        return None, "web_fetch cannot access localhost, private, link-local, or reserved hosts"
    cleaned = parsed._replace(fragment="").geturl()
    return cleaned, None


def _blocked_fetch_host(host: str) -> bool:
    if host in {"localhost", "0", "0.0.0.0"} or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _header_value(response: Any, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        return str(getter(name, "") or "")
    return ""


def _charset_from_content_type(content_type: str) -> str:
    match = re.search(r"charset=([^;\s]+)", str(content_type or ""), flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else ""


def _is_text_content_type(content_type: str) -> bool:
    normalized = str(content_type or "").lower().split(";", 1)[0].strip()
    return (
        normalized.startswith("text/")
        or normalized
        in {
            "application/json",
            "application/ld+json",
            "application/xml",
            "application/xhtml+xml",
            "application/rss+xml",
            "application/atom+xml",
            "application/javascript",
        }
        or normalized.endswith("+json")
        or normalized.endswith("+xml")
    )


def _normalize_document_text(text: str, content_type: str) -> tuple[str, str]:
    if "html" not in str(content_type or "").lower() and _looks_like_html(text) is False:
        return _collapse_text(text), ""
    parser = _ReadableHtmlParser()
    parser.feed(text)
    return _collapse_text(parser.text()), _collapse_text(parser.title())


def _looks_like_html(text: str) -> bool:
    prefix = text[:500].lower()
    return "<html" in prefix or "<!doctype html" in prefix or "<body" in prefix


class _ReadableHtmlParser(HTMLParser):
    _BLOCK_TAGS = {"article", "aside", "blockquote", "br", "div", "h1", "h2", "h3", "li", "p", "section", "table", "td", "th", "tr"}
    _SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        normalized = tag.lower()
        if normalized in self._SKIP_TAGS:
            self._skip_depth += 1
        if normalized == "title":
            self._in_title = True
        if normalized in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if normalized == "title":
            self._in_title = False
        if normalized in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)

    def title(self) -> str:
        return "".join(self._title_parts)


def _collapse_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in str(value or "").splitlines()]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                collapsed.append("")
            previous_blank = True
            continue
        collapsed.append(line)
        previous_blank = False
    return "\n".join(collapsed).strip()


def _excerpt_with_flag(value: str, limit: int) -> tuple[str, bool]:
    if limit <= 0:
        return "", bool(value)
    if len(value) <= limit:
        return value, False
    marker = "\n...[omitted middle]...\n"
    remaining = max(0, limit - len(marker))
    head_len = max(100, remaining // 2)
    tail_len = max(100, remaining - head_len)
    if head_len + tail_len + len(marker) > limit:
        tail_len = max(0, limit - len(marker) - head_len)
    return value[:head_len].rstrip() + marker + value[-tail_len:].lstrip(), True
