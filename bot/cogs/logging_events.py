from __future__ import annotations

import discord
from discord.ext import commands

from bot.utils.embeds import embed, shorten
from bot.utils.modules import module_enabled


class LoggingEvents(commands.Cog):
    """Event listeners for configurable moderation, message, member and voice logs."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _send(self, guild: discord.Guild, category: str, title: str, description: str, *, colour=0x5865F2) -> None:
        if not await module_enabled(self.bot, guild.id, "logging"):
            return
        channel_id = await self.bot.db.setting(guild.id, f"log_channels.{category}")
        if not channel_id and category != "general":
            channel_id = await self.bot.db.setting(guild.id, "log_channels.general")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel and hasattr(channel, "send"):
            try:
                await channel.send(embed=embed(title, description, colour=discord.Colour(colour)))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild:
            return
        if not message.author.bot:
            self.bot.deleted_messages[message.channel.id] = {
                "author": str(message.author),
                "content": message.content,
                "attachments": [a.url for a in message.attachments],
            }
        if message.author.bot:
            return
        mention = getattr(message.channel, "mention", f"#{getattr(message.channel, 'name', message.channel.id)}")
        await self._send(
            message.guild,
            "messages",
            "Message deleted",
            f"**Author:** {message.author.mention}\n**Channel:** {mention}\n{shorten(message.content or '*no text*')}",
            colour=0xED4245,
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages or not messages[0].guild:
            return
        channel = messages[0].channel
        mention = getattr(channel, "mention", str(channel.id))
        await self._send(
            messages[0].guild,
            "messages",
            "Messages bulk-deleted",
            f"**{len(messages)}** messages removed in {mention}.",
            colour=0xED4245,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not before.guild or before.content == after.content or before.author.bot:
            return
        self.bot.edited_messages[before.channel.id] = {
            "before": before.content,
            "after": after.content,
            "author": str(before.author),
        }
        mention = getattr(before.channel, "mention", str(before.channel.id))
        await self._send(
            before.guild,
            "messages",
            "Message edited",
            f"**Author:** {before.author.mention}\n**Channel:** {mention}\n"
            f"**Before:** {shorten(before.content or '*empty*')}\n**After:** {shorten(after.content or '*empty*')}",
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        age_days = (discord.utils.utcnow() - member.created_at).days
        warning = " ⚠️ Account is less than 7 days old." if age_days < 7 else ""
        await self._send(member.guild, "members", "Member joined", f"{member.mention} joined the server.{warning}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._send(
            member.guild, "members", "Member left", f"{member} (`{member.id}`) left the server.", colour=0xED4245
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick != after.nick:
            await self._send(
                after.guild,
                "members",
                "Nickname changed",
                f"{after.mention}: `{before.nick or 'none'}` → `{after.nick or 'none'}`",
            )
        before_roles = {role.id for role in before.roles}
        after_roles = {role.id for role in after.roles}
        if before_roles != after_roles:
            added = [
                after.guild.get_role(role_id).mention
                for role_id in after_roles - before_roles
                if after.guild.get_role(role_id)
            ]
            removed = [
                before.guild.get_role(role_id).mention
                for role_id in before_roles - after_roles
                if before.guild.get_role(role_id)
            ]
            await self._send(
                after.guild,
                "members",
                "Roles changed",
                f"{after.mention}\n**Added:** {', '.join(added) or 'none'}\n**Removed:** {', '.join(removed) or 'none'}",
            )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        mention = getattr(channel, "mention", f"**{channel.name}**")
        await self._send(channel.guild, "server", "Channel created", f"{mention} (`{channel.id}`)")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self._send(
            channel.guild, "server", "Channel deleted", f"**{channel.name}** (`{channel.id}`)", colour=0xED4245
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        if before.name != after.name:
            mention = getattr(after, "mention", after.name)
            await self._send(after.guild, "server", "Channel renamed", f"`{before.name}` → {mention}")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        await self._send(guild, "moderation", "Member banned", f"{user} (`{user.id}`) was banned.", colour=0xED4245)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        await self._send(guild, "moderation", "Member unbanned", f"{user} (`{user.id}`) was unbanned.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if before.channel == after.channel:
            return
        old = before.channel.mention if before.channel else "nothing"
        new = after.channel.mention if after.channel else "nothing"
        await self._send(member.guild, "voice", "Voice state changed", f"{member.mention}: {old} → {new}")

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        await self._send(
            invite.guild,
            "invites",
            "Invite created",
            f"Code `{invite.code}` • max uses: {invite.max_uses or '∞'} • by {invite.inviter}",
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        await self._send(invite.guild, "invites", "Invite deleted", f"Code `{invite.code}` expired or was revoked.", colour=0xED4245)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingEvents(bot))
