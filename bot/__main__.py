from __future__ import annotations

import logging
import sys

from bot.config import settings
from bot.core.bot import AegisBot


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("aegis.log", encoding="utf-8")],
    )
    if not settings.token:
        raise SystemExit("DISCORD_TOKEN is required. Copy .env.example to .env and configure it.")
    AegisBot(settings).run(settings.token, log_handler=None)


if __name__ == "__main__":
    main()
