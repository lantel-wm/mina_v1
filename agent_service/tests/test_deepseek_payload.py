from __future__ import annotations

from mina_agent.config import Settings
from mina_agent.deepseek import DeepSeekClient


def test_deepseek_defaults_target_v4_flash() -> None:
    settings = Settings(api_key="test")
    client = DeepSeekClient(settings)

    assert client.configured()
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-v4-flash"
    assert settings.thinking == "disabled"

