"""Guild-aware strings from config/messages.yml."""
from __future__ import annotations

from typing import Any

FALLBACK = {
    "permission": "You do not have permission to use that command.",
    "cancelled": "Cancelled. No changes were made.",
    "saved": "Your settings were saved.",
    "not_found": "Nothing was found.",
    "no_module": "That module is disabled on this server. An admin can enable it with /panel.",
}


def _as_catalog(block: Any) -> dict[str, str]:
    if not isinstance(block, dict):
        return {}
    return {str(key): str(value) for key, value in block.items()}


def catalog(bot: Any, lang: str = "en") -> dict[str, str]:
    messages = getattr(getattr(bot, "settings", None), "messages", None) or {}
    english = _as_catalog(messages.get("en") if isinstance(messages, dict) else None)
    overlay = _as_catalog(messages.get(lang) if isinstance(messages, dict) and lang != "en" else None)
    return {**FALLBACK, **english, **overlay}


async def text(bot: Any, guild_id: int | None, key: str, fallback: str | None = None, **values: Any) -> str:
    lang = "en"
    if guild_id is not None:
        try:
            lang = str(await bot.db.setting(guild_id, "language", "en") or "en")
        except Exception:
            lang = "en"
    result = catalog(bot, lang).get(key, fallback or key)
    if not values:
        return result
    try:
        return result.format(**values)
    except (KeyError, ValueError, IndexError):
        return result
