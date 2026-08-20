"""Environment-backed application configuration.

Only secrets belong in the environment. Guild-specific values live in the database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
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

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        owners = frozenset(
            int(value.strip())
            for value in os.getenv("OWNER_IDS", "").split(",")
            if value.strip().isdigit()
        )
        return cls(
            token=token,
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/bot.db"),
            owner_ids=owners,
            prefix=os.getenv("DEFAULT_PREFIX", "!")[:5] or "!",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            bot_name=os.getenv("BOT_NAME", "Aegis"),
            version=os.getenv("BOT_VERSION", "1.0.0"),
            weather_api_key=os.getenv("OPENWEATHER_API_KEY") or None,
            translate_api_url=os.getenv("TRANSLATE_API_URL") or None,
        )

    @property
    def sqlite_path(self) -> Path:
        """Return the SQLite path, creating its parent at database startup.

        The first release intentionally keeps a small, dependency-free storage adapter.
        ``DATABASE_URL`` accepts ``sqlite:///relative/path.db`` and ``sqlite:////abs``.
        A future PostgreSQL adapter can implement the same Database interface.
        """
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError(
                "This build supports SQLite DATABASE_URL values (sqlite:///path.db). "
                "Use the Database adapter interface when enabling PostgreSQL."
            )
        raw = self.database_url.removeprefix("sqlite:///")
        return Path("/") / raw if raw.startswith("/") else Path(raw)


settings = Settings.from_env()
