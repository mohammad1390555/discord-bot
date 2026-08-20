from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

BRAND = discord.Colour(0x5865F2)
SUCCESS = discord.Colour(0x57F287)
WARNING = discord.Colour(0xFEE75C)
DANGER = discord.Colour(0xED4245)


def embed(title: str, description: str = "", *, colour: discord.Colour = BRAND,
          bot_name: str = "Aegis", version: str = "1.0.0", **kwargs: Any) -> discord.Embed:
    result = discord.Embed(title=title, description=description, colour=colour,
                           timestamp=datetime.now(timezone.utc), **kwargs)
    result.set_footer(text=f"{bot_name} • v{version}")
    return result


def ok(description: str, **kwargs: Any) -> discord.Embed:
    return embed("Done", description, colour=SUCCESS, **kwargs)


def error(description: str, **kwargs: Any) -> discord.Embed:
    return embed("Something went wrong", description, colour=DANGER, **kwargs)


def info(description: str, title: str = "Aegis", **kwargs: Any) -> discord.Embed:
    return embed(title, description, **kwargs)


def warning(description: str, **kwargs: Any) -> discord.Embed:
    return embed("Notice", description, colour=WARNING, **kwargs)


def shorten(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
