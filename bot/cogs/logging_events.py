from __future__ import annotations

import discord
from discord.ext import commands

from bot.utils.embeds import embed, shorten


class LoggingEvents(commands.Cog):
    """Event listeners for configurable moderation, message, member and voice logs."""
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _send(self, guild: discord.Guild, category: str, title: str, description: str, *, colour=0x5865F2) -> None:
        channel_id = await self.bot.db.setting(guild.id, f"log_channels.{category}")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel and hasattr(channel, "send"):
            try:
                await channel.send(embed=embed(title, description, colour=discord.Colour(colour)))
            except discord.HTTPException:
                pass

    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild:
            return
        self.bot.deleted_messages[message.channel.id] = {
            "author": message.author, "content": message.content, "attachments": [a.url for a in message.attachments],
        }
        await self._send(message.guild, "messages", "Message deleted", f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n{shorten(message.content or '*no text*')}", colour=0xED4245)

    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        for message in messages:
            await self.on_message_delete(message)

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not before.guild or before.content == after.content:
            return
        self.bot.edited_messages[before.channel.id] = {"before": before.content, "after": after.content, "author": before.author}
        await self._send(before.guild, "messages", "Message edited", f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n**Before:** {shorten(before.content or '*empty*')}\n**After:** {shorten(after.content or '*empty*')}")

    async def on_member_join(self, member: discord.Member) -> None:
        age_days = (discord.utils.utcnow() - member.created_at).days
        warning = " ⚠️ Account is less than 7 days old." if age_days < 7 else ""
        await self._send(member.guild, "members", "Member joined", f"{member.mention} joined the server.{warning}")

    async def on_member_remove(self, member: discord.Member) -> None:
        await self._send(member.guild, "members", "Member left", f"{member} (`{member.id}`) left the server.", colour=0xED4245)

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick != after.nick:
            await self._send(after.guild, "members", "Nickname changed", f"{after.mention}: `{before.nick or 'none'}` → `{after.nick or 'none'}`")
        before_roles = {role.id for role in before.roles}
        after_roles = {role.id for role in after.roles}
        if before_roles != after_roles:
            added = [after.guild.get_role(role_id).mention for role_id in after_roles - before_roles if after.guild.get_role(role_id)]
            removed = [before.guild.get_role(role_id).mention for role_id in before_roles - after_roles if before.guild.get_role(role_id)]
            await self._send(after.guild, "members", "Roles changed", f"{after.mention}\n**Added:** {', '.join(added) or 'none'}\n**Removed:** {', '.join(removed) or 'none'}")

    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self._send(channel.guild, "general", "Channel created", f"{channel.mention} (`{channel.id}`)")

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self._send(channel.guild, "general", "Channel deleted", f"**{channel.name}** (`{channel.id}`)", colour=0xED4245)

    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        if before.name != after.name:
            await self._send(after.guild, "general", "Channel renamed", f"`{before.name}` → {after.mention}")

    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        await self._send(guild, "moderation", "Member banned", f"{user} (`{user.id}`) was banned.", colour=0xED4245)

    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        await self._send(guild, "moderation", "Member unbanned", f"{user} (`{user.id}`) was unbanned.")

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if before.channel == after.channel:
            return
        old = before.channel.mention if before.channel else "nothing"
        new = after.channel.mention if after.channel else "nothing"
        await self._send(member.guild, "voice", "Voice state changed", f"{member.mention}: {old} → {new}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingEvents(bot))
