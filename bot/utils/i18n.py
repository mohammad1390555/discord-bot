"""Tiny async guild-aware translation layer.

Feature cogs can ask for a message by key instead of branching on language. The
catalog is deliberately small and easy to extend; user-authored templates remain
unchanged and can contain Discord's normal variables.
"""
from __future__ import annotations

from typing import Any

CATALOG: dict[str, dict[str, str]] = {
    "en": {
        "permission": "You do not have permission to use that command.",
        "cancelled": "Cancelled. No changes were made.",
        "saved": "Your settings were saved.",
        "not_found": "Nothing was found.",
    },
    "fa": {
        "permission": "شما اجازه استفاده از این دستور را ندارید.",
        "cancelled": "لغو شد؛ تغییری انجام نشد.",
        "saved": "تنظیمات شما ذخیره شد.",
        "not_found": "موردی پیدا نشد.",
    },
}


async def text(bot: Any, guild_id: int | None, key: str, fallback: str | None = None, **values: Any) -> str:
    language = await bot.db.setting(guild_id, "language", "en") if guild_id else "en"
    result = CATALOG.get(language, CATALOG["en"]).get(key, fallback or key)
    return result.format(**values) if values else result
