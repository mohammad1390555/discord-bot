"""Guild-aware strings from config/messages.yml (English catalog)."""
from __future__ import annotations

from typing import Any

FALLBACK = {
    "permission": "You do not have permission to use that command.",
    "cancelled": "Cancelled. No changes were made.",
    "saved": "Your settings were saved.",
    "not_found": "Nothing was found.",
}


def catalog(bot: Any) -> dict[str, str]:
    messages = getattr(getattr(bot, "settings", None), "messages", None) or {}
    english = messages.get("en") if isinstance(messages, dict) else None
    if isinstance(english, dict):
        return {**FALLBACK, **{str(k): str(v) for k, v in english.items()}}
    return FALLBACK


async def text(bot: Any, guild_id: int | None, key: str, fallback: str | None = None, **values: Any) -> str:
    result = catalog(bot).get(key, fallback or key)
    return result.format(**values) if values else result
