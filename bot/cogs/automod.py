from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord.ext import commands

from bot.utils.cache import LRUCache
from bot.utils.embeds import DANGER, WARNING, embed
from bot.utils.format import safe_format
from bot.utils.modules import module_enabled

INVITE_RE = re.compile(r"(?:discord(?:app)?\.com/invite|discord\.gg)/[\w-]+", re.I)


class AutoModeration(commands.Cog):
    """Configurable message guard, welcome/leave, autorole and lightweight anti-raid."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.joins: dict[int, deque[float]] = defaultdict(deque)
        self.recent: LRUCache[tuple[int, int], tuple[str, float]] = LRUCache(512)

    async def _log(self, guild: discord.Guild, title: str, description: str, colour=WARNING) -> None:
        channel_id = await self.bot.db.setting(guild.id, "log_channels.moderation")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel and hasattr(channel, "send"):
            try:
                await channel.send(embed=embed(title, description, colour=colour))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        if not await module_enabled(self.bot, guild.id, "onboarding"):
            return
        now = discord.utils.utcnow().timestamp()
        window = self.joins[guild.id]
        window.append(now)
        while window and now - window[0] > 20:
            window.popleft()
        if len(window) >= 8:
            await self._log(guild, "Possible raid detected", f"{len(window)} members joined in 20 seconds.", DANGER)
            settings = await self.bot.db.get_guild(guild.id)
            if settings["settings"].get("automod", {}).get("raid_lockdown"):
                await self.bot.db.set_settings(guild.id, lockdown=True)
                for channel in guild.text_channels:
                    try:
                        await channel.set_permissions(guild.default_role, send_messages=False, reason="Anti-raid lockdown")
                    except discord.HTTPException:
                        continue
        if member.bot:
            return
        role_id = await self.bot.db.setting(guild.id, "autorole_id")
        role = guild.get_role(role_id) if role_id else None
        me = guild.me
        if role and me and role < me.top_role and not role.managed:
            try:
                await member.add_roles(role, reason="Aegis autorole")
            except discord.HTTPException:
                pass
        channel_id = await self.bot.db.setting(guild.id, "welcome.channel_id")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel and hasattr(channel, "send"):
            template = await self.bot.db.setting(guild.id, "welcome.message", "Welcome {user} to {server}!")
            text = safe_format(template, user=member.mention, server=guild.name, membercount=guild.member_count)
            try:
                await channel.send(embed=embed("Welcome", text))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not await module_enabled(self.bot, member.guild.id, "onboarding"):
            return
        channel_id = await self.bot.db.setting(member.guild.id, "leave.channel_id")
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if channel and hasattr(channel, "send"):
            template = await self.bot.db.setting(member.guild.id, "leave.message", "{user} has left {server}.")
            try:
                await channel.send(
                    embed=embed(
                        "Member left",
                        safe_format(template, user=str(member), server=member.guild.name, membercount=member.guild.member_count),
                    )
                )
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if not await module_enabled(self.bot, message.guild.id, "automod"):
            return
        if message.author.guild_permissions.manage_messages:
            return
        settings = await self.bot.db.get_guild(message.guild.id)
        config = settings["settings"].get("automod", {})
        if not config.get("enabled"):
            return
        content = message.content or ""
        lowered = content.casefold()
        banned = [str(word).casefold() for word in config.get("banned_words", [])]
        violations: list[str] = []
        if any(word and re.search(rf"\b{re.escape(word)}\b", lowered) for word in banned):
            violations.append("banned word")
        if INVITE_RE.search(content) and config.get("block_invites", False):
            violations.append("invite link")
        if len(message.mentions) > int(config.get("max_mentions", 5)):
            violations.append("excessive mentions")
        letters = [char for char in content if char.isalpha()]
        if len(letters) >= 12 and sum(char.isupper() for char in letters) / len(letters) >= float(config.get("max_caps", 0.8)):
            violations.append("excessive capitals")
        key = (message.guild.id, message.author.id)
        previous = self.recent.get(key)
        now = discord.utils.utcnow().timestamp()
        if previous and previous[0] == content and content and now - previous[1] < 15:
            violations.append("duplicate message spam")
        self.recent[key] = (content, now)
        if not violations:
            return
        try:
            await message.delete(reason="Aegis auto-moderation: " + ", ".join(violations))
        except discord.HTTPException:
            pass
        bot_id = self.bot.user.id if self.bot.user else 0
        await self.bot.db.add_warning(message.guild.id, message.author.id, bot_id, "AutoMod: " + ", ".join(violations))
        punishment = config.get("punishment", "warn")
        try:
            if punishment == "mute":
                await message.author.timeout(timedelta(minutes=10), reason="AutoMod escalation")
            elif punishment == "kick":
                await message.author.kick(reason="AutoMod escalation")
            elif punishment == "ban":
                await message.author.ban(reason="AutoMod escalation")
        except discord.HTTPException:
            pass
        try:
            await message.channel.send(
                embed=embed(
                    "Message removed",
                    f"{message.author.mention}, your message was removed for {', '.join(violations)}.",
                    colour=DANGER,
                ),
                delete_after=8,
            )
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoModeration(bot))
