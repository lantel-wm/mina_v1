from __future__ import annotations

import logging

from mina_agent.config import Settings, load_settings
from mina_agent.logging_config import configure_logging


def test_log_settings_can_be_loaded_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINA_LOG_PATH", "tmp/mina.log")
    monkeypatch.setenv("MINA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("MINA_LOG_MAX_BYTES", "12345")
    monkeypatch.setenv("MINA_LOG_BACKUP_COUNT", "7")

    settings = load_settings()

    assert settings.log_path.as_posix() == "tmp/mina.log"
    assert settings.log_level == "DEBUG"
    assert settings.log_max_bytes == 12345
    assert settings.log_backup_count == 7


def test_configure_logging_writes_file(tmp_path) -> None:
    settings = Settings(log_path=tmp_path / "logs" / "mina_agent.log", log_level="INFO")

    configure_logging(settings)
    logging.getLogger("mina_agent.tests").info("file logging smoke")
    for handler in logging.getLogger("mina_agent").handlers:
        handler.flush()

    assert settings.log_path.exists()
    assert "file logging smoke" in settings.log_path.read_text(encoding="utf-8")
