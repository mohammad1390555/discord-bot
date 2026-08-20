from __future__ import annotations

from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands


def guild_only() -> Callable[[Any], Any]:
    return app_commands.checks.guild_only()


def owner_only(bot: Any) -> Callable[[Any], Any]:
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id not in bot.settings.owner_ids:
            raise app_commands.CheckFailure("This command is restricted to the bot owner.")
        return True

    return app_commands.check(predicate)


class UserFacingError(commands.CommandError):
    """An expected error which should be shown without a traceback."""


def can_moderate(member: discord.Member, target: discord.Member) -> None:
    if target.id == member.id:
        raise UserFacingError("You cannot moderate yourself.")
    if target.id == member.guild.owner_id:
        raise UserFacingError("The server owner cannot be moderated.")
    if target.top_role >= member.top_role and member.id != member.guild.owner_id:
        raise UserFacingError("That member has an equal or higher role than you.")


def can_bot_moderate(guild: discord.Guild, target: discord.Member) -> None:
    me = guild.me
    if me and target.top_role >= me.top_role:
        raise UserFacingError("That member has an equal or higher role than the bot.")


async def send_ephemeral(interaction: discord.Interaction, message: str, *, colour: int = 0xED4245) -> None:
    embed = discord.Embed(description=message, colour=colour)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        pass
