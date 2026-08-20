"""Environment secrets plus YAML defaults from config/."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from bot.yaml_config import load_yaml, nested

load_dotenv()


@dataclass(slots=True)
class Settings:
    token: str
    database_url: str
    owner_ids: frozenset[int]
    prefix: str
    log_level: str
    bot_name: str
    version: str
    weather_api_key: str | None = None
    translate_api_url: str | None = None
    yaml: dict[str, Any] = field(default_factory=dict)
    messages: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        yaml_cfg = load_yaml("config.yml")
        messages = load_yaml("messages.yml")
        token = os.getenv("DISCORD_TOKEN", "").strip()
        owners = frozenset(
            int(value.strip())
            for value in os.getenv("OWNER_IDS", "").split(",")
            if value.strip().isdigit()
        )
        bot_block = yaml_cfg.get("bot") or {}
        return cls(
            token=token,
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/bot.db"),
            owner_ids=owners,
            prefix=os.getenv("DEFAULT_PREFIX") or bot_block.get("default_prefix") or "!",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            bot_name=os.getenv("BOT_NAME") or bot_block.get("name") or "Aegis",
            version=os.getenv("BOT_VERSION") or str(bot_block.get("version") or "1.1.0"),
            weather_api_key=os.getenv("OPENWEATHER_API_KEY") or None,
            translate_api_url=os.getenv("TRANSLATE_API_URL") or None,
            yaml=yaml_cfg,
            messages=messages,
        )

    def get(self, path: str, default: Any = None) -> Any:
        return nested(self.yaml, path, default)

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError(
                "This build supports SQLite DATABASE_URL values (sqlite:///path.db). "
                "Use the Database adapter interface when enabling PostgreSQL."
            )
        raw = self.database_url.removeprefix("sqlite:///")
        return Path("/") / raw if raw.startswith("/") else Path(raw)


settings = Settings.from_env()
