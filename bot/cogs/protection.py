from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import error, info, ok, warning as warn_embed

SCAM = re.compile(r"(discord(?:app)?\.gift|free.?nitro|steamcommunity\.ru|discorcl\.|dlscord)", re.I)
INVITE = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite)/", re.I)


class Protection(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.actions: dict[int, Deque[tuple[datetime, int, str]]] = defaultdict(deque)

    async def enabled(self, guild_id: int) -> bool:
        return bool(await self.bot.db.setting(guild_id, "modules.protection", True))

    def _track(self, guild_id: int, user_id: int, kind: str) -> int:
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=int(self.bot.settings.get("protection.anti_nuke_window_seconds", 10)))
        q = self.actions[guild_id]
        q.append((now, user_id, kind))
        while q and now - q[0][0] > window:
            q.popleft()
        return sum(1 for _, uid, k in q if uid == user_id and k == kind)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.guild or member.bot or not await self.enabled(member.guild.id):
            return
        days = int(self.bot.settings.get("protection.anti_alt_days", 7))
        action = self.bot.settings.get("protection.anti_alt_action", "restrict")
        created = member.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - created
        if age.days < days and action == "kick":
            try:
                await member.kick(reason=f"Anti-alt: account younger than {days} days")
            except discord.HTTPException:
                pass
        if self.bot.settings.get("protection.dehoist", True):
            chars = str(self.bot.settings.get("protection.dehoist_characters", "!\"#$%&'*+,-./"))
            name = member.display_name
            if name and name[0] in chars:
                try:
                    await member.edit(nick="z" + name[:31], reason="Dehoist")
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        guild = channel.guild
        if not await self.enabled(guild.id):
            return
        if not self.bot.settings.get("protection.anti_nuke", True):
            return
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            count = self._track(guild.id, entry.user.id, "channel_delete")
            threshold = int(self.bot.settings.get("protection.anti_nuke_threshold", 5))
            if count >= threshold and entry.user != guild.me:
                member = guild.get_member(entry.user.id)
                if member and member.top_role < guild.me.top_role and not member.guild_permissions.administrator:
                    try:
                        await member.edit(roles=[r for r in member.roles if r.is_default()], reason="Anti-nuke")
                    except discord.HTTPException:
                        pass
                if guild.owner:
                    try:
                        await guild.owner.send(f"Anti-nuke: {entry.user} deleted {count} channels quickly in {guild.name}.")
                    except discord.HTTPException:
                        pass
            break

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot or not await self.enabled(message.guild.id):
            return
        if self.bot.settings.get("protection.scam_links", True) and SCAM.search(message.content or ""):
            try:
                await message.delete()
            except discord.HTTPException:
                return
            try:
                await message.channel.send(embed=warn_embed("Suspicious link removed."), delete_after=8)
            except discord.HTTPException:
                pass
        if self.bot.settings.get("protection.webhook_spam", True) and message.webhook_id:
            recent = [m async for m in message.channel.history(limit=8)]
            if sum(1 for m in recent if m.webhook_id == message.webhook_id) >= 6:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass

    @app_commands.command(name="lockdown", description="Lock or unlock all text channels")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def lockdown(self, interaction: discord.Interaction, enabled: bool) -> None:
        if not await self.enabled(interaction.guild_id):
            await interaction.response.send_message(embed=error("Protection module is disabled."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        overwritten = 0
        for channel in guild.text_channels:
            try:
                await channel.set_permissions(guild.default_role, send_messages=False if enabled else None, reason="Lockdown")
                overwritten += 1
            except discord.HTTPException:
                continue
        await self.bot.db.set_settings(guild.id, lockdown=enabled)
        key = "lockdown_on" if enabled else "lockdown_off"
        from bot.utils.i18n import text as localized
        msg = await localized(self.bot, guild.id, key, "Lockdown updated.")
        await interaction.followup.send(embed=ok(f"{msg} ({overwritten} channels)"), ephemeral=True)

    @app_commands.command(name="auditperms", description="Flag dangerous role and channel permissions")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def auditperms(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        flags: list[str] = []
        everyone = guild.default_role
        if everyone.permissions.administrator:
            flags.append("@everyone has Administrator")
        dangerous = ("administrator", "ban_members", "kick_members", "manage_guild", "mention_everyone")
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            perms = role.permissions
            hits = [name.replace("_", " ") for name in dangerous if getattr(perms, name)]
            if hits:
                flags.append(f"{role.mention}: {', '.join(hits)}")
        text = "\n".join(flags[:20]) or "No obvious misconfigurations found."
        await interaction.response.send_message(embed=info(text), ephemeral=True)

    @app_commands.command(name="backupserver", description="Export channel and role names as a text backup")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def backupserver(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        lines = [f"# {guild.name}", "## Roles"]
        for role in reversed(guild.roles):
            if not role.is_default():
                lines.append(f"- {role.name} ({role.id})")
        lines.append("## Channels")
        for channel in guild.channels:
            lines.append(f"- {channel.type.name}: {channel.name} ({channel.id})")
        payload = "\n".join(lines).encode()
        import io
        await interaction.response.send_message(
            embed=ok("Server structure backup attached."),
            file=discord.File(io.BytesIO(payload), filename=f"{guild.id}-backup.txt"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Protection(bot))
