from __future__ import annotations

import logging
import logging.config
from typing import Any

from .config import Settings


def configure_logging(settings: Settings) -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    level = _level(settings.log_level)
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "default",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level,
                "formatter": "default",
                "filename": str(settings.log_path),
                "maxBytes": settings.log_max_bytes,
                "backupCount": settings.log_backup_count,
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": level,
            "handlers": ["console", "file"],
        },
        "loggers": {
            "mina_agent": {
                "level": level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn": {
                "level": level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
    }
    logging.config.dictConfig(config)
    logging.getLogger("mina_agent").info("logging configured path=%s level=%s", settings.log_path, logging.getLevelName(level))


def _level(value: str) -> int:
    level = getattr(logging, value.upper(), None)
    if isinstance(level, int):
        return level
    return logging.INFO
