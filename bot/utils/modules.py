"""Per-guild feature flags from /panel, falling back to config.yml defaults."""
from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands


async def module_enabled(bot: Any, guild_id: int | None, name: str) -> bool:
    if guild_id is None:
        return True
    stored = await bot.db.setting(guild_id, f"modules.{name}", None)
    if stored is None:
        return bool((bot.settings.get("modules") or {}).get(name, True))
    return bool(stored)


class ModuleCog(commands.Cog):
    """Slash commands on this cog honour the matching /panel toggle."""

    module_name: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        name = getattr(self, "module_name", None)
        if not name:
            return True
        if await module_enabled(self.bot, interaction.guild_id, name):  # type: ignore[attr-defined]
            return True
        raise app_commands.CheckFailure(
            "That module is disabled on this server. An admin can enable it with /panel."
        )
