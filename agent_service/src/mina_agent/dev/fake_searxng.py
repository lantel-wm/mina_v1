from __future__ import annotations

from typing import Any

from fastapi import FastAPI

app = FastAPI(title="Mina Fake SearXNG", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "mina-fake-searxng"}


@app.get("/search")
def search(q: str = "", format: str = "json") -> dict[str, Any]:  # noqa: A002 - mirrors SearXNG query parameter.
    return {
        "query": q,
        "format": format,
        "results": [
            {
                "title": "Minecraft Wiki",
                "url": "https://minecraft.wiki/",
                "content": f"联网知识查询链路可用: {q}",
            }
        ],
    }
