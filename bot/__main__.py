from __future__ import annotations

import logging
import sys
from pathlib import Path

from bot.config import settings
from bot.core.bot import AegisBot


def main() -> None:
    Path("data").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("data/aegis.log", encoding="utf-8"),
        ],
    )
    if not settings.token:
        raise SystemExit("DISCORD_TOKEN is required. Copy .env.example to .env and configure it.")
    if not settings.owner_ids:
        logging.getLogger("aegis").warning("OWNER_IDS is empty — owner commands will be unusable.")
    AegisBot(settings).run(settings.token, log_handler=None)


if __name__ == "__main__":
    main()
