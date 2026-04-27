from __future__ import annotations

import uvicorn

from .config import load_settings
from .logging_config import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    uvicorn.run("mina_agent.app:app", host=settings.host, port=settings.port, reload=False, log_config=None)


if __name__ == "__main__":
    main()
