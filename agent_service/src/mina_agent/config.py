from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    thinking: str = "disabled"
    reasoning_effort: str = "high"
    searxng_url: str = "http://127.0.0.1:8888"
    db_path: Path = Path("agent_service/data/mina.sqlite3")
    host: str = "127.0.0.1"
    port: int = 18911
    request_timeout_seconds: float = 90.0
    max_tool_turns: int = 8
    companion_cooldown_seconds: int = 300
    emergency_cooldown_seconds: int = 30
    debug_tool_calls: bool = True
    log_path: Path = Path("agent_service/logs/mina_agent.log")
    log_level: str = "INFO"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5

    @property
    def deepseek_configured(self) -> bool:
        return bool(self.api_key)


def load_settings() -> Settings:
    load_dotenv_defaults()
    return Settings(
        base_url=os.getenv("MINA_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        api_key=os.getenv("MINA_API_KEY", ""),
        model=os.getenv("MINA_MODEL", "deepseek-v4-flash"),
        thinking=os.getenv("MINA_THINKING", "disabled"),
        reasoning_effort=os.getenv("MINA_REASONING_EFFORT", "high"),
        searxng_url=os.getenv("MINA_SEARXNG_URL", "http://127.0.0.1:8888").rstrip("/"),
        db_path=Path(os.getenv("MINA_DB_PATH", "agent_service/data/mina.sqlite3")),
        host=os.getenv("MINA_HOST", "127.0.0.1"),
        port=int(os.getenv("MINA_PORT", "18911")),
        request_timeout_seconds=float(os.getenv("MINA_REQUEST_TIMEOUT_SECONDS", "90")),
        max_tool_turns=int(os.getenv("MINA_MAX_TOOL_TURNS", "8")),
        companion_cooldown_seconds=int(os.getenv("MINA_COMPANION_COOLDOWN_SECONDS", "300")),
        emergency_cooldown_seconds=int(os.getenv("MINA_EMERGENCY_COOLDOWN_SECONDS", "30")),
        debug_tool_calls=os.getenv("MINA_DEBUG_TOOL_CALLS", "true").lower() in {"1", "true", "yes", "on"},
        log_path=Path(os.getenv("MINA_LOG_PATH", "agent_service/logs/mina_agent.log")),
        log_level=os.getenv("MINA_LOG_LEVEL", "INFO").upper(),
        log_max_bytes=int(os.getenv("MINA_LOG_MAX_BYTES", str(10 * 1024 * 1024))),
        log_backup_count=int(os.getenv("MINA_LOG_BACKUP_COUNT", "5")),
    )


def load_dotenv_defaults() -> None:
    for path in (Path("agent_service/.env"), Path(".env")):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        break
