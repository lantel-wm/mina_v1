from __future__ import annotations

from mina_agent.config import Settings
from mina_agent.deepseek import DeepSeekClient
from mina_agent.deepseek import _is_loopback


def test_deepseek_defaults_target_v4_flash() -> None:
    settings = Settings(api_key="test")
    client = DeepSeekClient(settings)

    assert client.configured()
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-v4-flash"
    assert settings.thinking == "disabled"


def test_deepseek_loopback_base_urls_bypass_proxy() -> None:
    assert _is_loopback("http://127.0.0.1:18889")
    assert _is_loopback("http://localhost:18889")
    assert not _is_loopback("https://api.deepseek.com")
