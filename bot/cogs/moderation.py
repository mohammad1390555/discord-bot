from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import can_bot_moderate, can_moderate
from bot.utils.embeds import WARNING, embed, ok
from bot.utils.time import human_duration, parse_duration
from bot.utils.ui import ConfirmView, Paginator


class Moderation(commands.Cog):
    """Permission-aware moderation with persistent case IDs and timed actions."""
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.scheduler.register("unmute", self._expire_timeout)
        self.bot.scheduler.register("unban", self._expire_ban)

    async def _confirm(self, interaction: discord.Interaction, text: str) -> bool:
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(embed=embed("Please confirm", text, colour=WARNING), view=view, ephemeral=True)
        await view.wait()
        return view.confirmed

    async def _expire_timeout(self, payload: dict) -> None:
        guild = self.bot.get_guild(int(payload["guild_id"]))
        if not guild:
            return
        member = guild.get_member(int(payload["user_id"]))
        if member and member.is_timed_out():
            try:
                await member.timeout(None, reason="Temporary timeout expired")
            except discord.HTTPException:
                return

    async def _expire_ban(self, payload: dict) -> None:
        guild = self.bot.get_guild(int(payload["guild_id"]))
        if not guild:
            return
        try:
            await guild.unban(discord.Object(id=int(payload["user_id"])), reason="Temporary ban expired")
        except (discord.NotFound, discord.HTTPException):
            pass

    @app_commands.command(name="ban", description="Ban a member and optionally delete their recent messages")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        can_bot_moderate(interaction.guild, member)  # type: ignore[arg-type]
        if not await self._confirm(interaction, f"Ban {member.mention}?\n**Reason:** {reason[:400]}"):
            return
        try:
            await member.ban(reason=f"{reason} | moderator: {interaction.user}")
            case = await self.bot.db.add_case(interaction.guild_id, member.id, interaction.user.id, "ban", reason)
        except discord.HTTPException:
            await interaction.followup.send("Discord rejected the ban. Check my role hierarchy and permissions.", ephemeral=True)
            return
        await interaction.followup.send(embed=ok(f"{member} was banned. Case **#{case}**."))

    @app_commands.command(name="softban", description="Ban and immediately unban a member to clear recent messages")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def softban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        can_bot_moderate(interaction.guild, member)  # type: ignore[arg-type]
        if not await self._confirm(interaction, f"Softban {member.mention} and clear their recent messages?"):
            return
        await member.ban(delete_message_seconds=86400, reason=reason)
        await interaction.guild.unban(member, reason="Softban complete")  # type: ignore[union-attr]
        case = await self.bot.db.add_case(interaction.guild_id, member.id, interaction.user.id, "softban", reason)
        await interaction.followup.send(embed=ok(f"{member} was softbanned. Case **#{case}**."))

    @app_commands.command(name="tempban", description="Ban a member for a duration, then automatically unban them")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def tempban(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason provided") -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        can_bot_moderate(interaction.guild, member)  # type: ignore[arg-type]
        try:
            delta = parse_duration(duration, maximum=28 * 86400)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if not await self._confirm(interaction, f"Temporarily ban {member.mention} for **{human_duration(int(delta.total_seconds()))}**?"):
            return
        await member.ban(reason=reason)
        ends = discord.utils.utcnow() + delta
        await self.bot.db.schedule("unban", ends, {"guild_id": interaction.guild_id, "user_id": member.id})
        case = await self.bot.db.add_case(interaction.guild_id, member.id, interaction.user.id, "tempban", reason, int(delta.total_seconds()))
        await interaction.followup.send(embed=ok(f"{member} was banned for {human_duration(int(delta.total_seconds()))}. Case **#{case}**."))

    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided") -> None:
        if not user_id.isdigit():
            await interaction.response.send_message("User ID must contain only digits.", ephemeral=True)
            return
        user = discord.Object(id=int(user_id))
        if not await self._confirm(interaction, f"Unban user `{user_id}`?\n**Reason:** {reason[:400]}"):
            return
        try:
            await interaction.guild.unban(user, reason=reason)  # type: ignore[union-attr]
        except discord.NotFound:
            await interaction.followup.send("That user is not banned.", ephemeral=True)
            return
        case = await self.bot.db.add_case(interaction.guild_id, int(user_id), interaction.user.id, "unban", reason)
        await interaction.followup.send(embed=ok(f"User `{user_id}` was unbanned. Case **#{case}**."))

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        can_bot_moderate(interaction.guild, member)  # type: ignore[arg-type]
        if not await self._confirm(interaction, f"Kick {member.mention}?\n**Reason:** {reason[:400]}"):
            return
        await member.kick(reason=reason)
        case = await self.bot.db.add_case(interaction.guild_id, member.id, interaction.user.id, "kick", reason)
        await interaction.followup.send(embed=ok(f"{member} was kicked. Case **#{case}**."))

    @app_commands.command(name="mutetimeout", description="Apply a Discord timeout to a member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def mutetimeout(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason provided") -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        can_bot_moderate(interaction.guild, member)  # type: ignore[arg-type]
        try:
            delta = parse_duration(duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if not await self._confirm(interaction, f"Timeout {member.mention} for **{human_duration(int(delta.total_seconds()))}**?"):
            return
        await member.timeout(delta, reason=reason)
        ends = discord.utils.utcnow() + delta
        await self.bot.db.schedule("unmute", ends, {"guild_id": interaction.guild_id, "user_id": member.id})
        case = await self.bot.db.add_case(interaction.guild_id, member.id, interaction.user.id, "timeout", reason, int(delta.total_seconds()))
        await interaction.followup.send(embed=ok(f"{member} is timed out for {human_duration(int(delta.total_seconds()))}. Case **#{case}**."))

    @app_commands.command(name="unmute", description="Remove a member's Discord timeout")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        await member.timeout(None, reason=reason)
        case = await self.bot.db.add_case(interaction.guild_id, member.id, interaction.user.id, "unmute", reason)
        await interaction.response.send_message(embed=ok(f"Timeout removed from {member.mention}. Case **#{case}**."))

    @app_commands.command(name="warn", description="Add a warning to a member's moderation history")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        warning_id = await self.bot.db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        case = await self.bot.db.add_case(interaction.guild_id, member.id, interaction.user.id, "warn", reason)
        try:
            await member.send(embed=embed("You received a warning", f"**{interaction.guild.name}**\n{reason}", colour=WARNING))
        except discord.HTTPException:
            pass
        await interaction.response.send_message(embed=ok(f"{member.mention} was warned. Warning **#{warning_id}**, case **#{case}**."))

    @app_commands.command(name="unwarn", description="Remove a warning by its ID")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def unwarn(self, interaction: discord.Interaction, warning_id: int) -> None:
        warning = await self.bot.db.fetchone("SELECT * FROM warnings WHERE id=? AND guild_id=?", (warning_id, interaction.guild_id))
        if not warning or not warning["active"]:
            await interaction.response.send_message("Active warning not found.", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE warnings SET active=0 WHERE id=?", (warning_id,))
        await interaction.response.send_message(embed=ok(f"Warning **#{warning_id}** was removed."))

    @app_commands.command(name="warnings", description="View a member's active warning history")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        rows = await self.bot.db.warnings(interaction.guild_id, member.id)
        if not rows:
            await interaction.response.send_message(embed=embed("Warnings", f"{member.mention} has no active warnings."))
            return
        pages = []
        for offset in range(0, len(rows), 10):
            page = rows[offset:offset + 10]
            description = "\n".join(f"**#{row['id']}** <t:{int(__import__('datetime').datetime.fromisoformat(row['created_at']).timestamp())}:R> — {row['reason']}" for row in page)
            pages.append(embed(f"Warnings for {member}", description))
        view = Paginator(interaction.user.id, pages)
        await interaction.response.send_message(embed=pages[0], view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="purgeclear", description="Delete recent messages with optional filters")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def purgeclear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], member: Optional[discord.Member] = None, bots_only: bool = False, embeds_only: bool = False, contains: Optional[str] = None) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command only works in text channels.", ephemeral=True)
            return
        if not await self._confirm(interaction, f"Delete up to **{amount}** matching messages in {interaction.channel.mention}?"):
            return
        def check(message: discord.Message) -> bool:
            return (not member or message.author.id == member.id) and (not bots_only or message.author.bot) and (not embeds_only or bool(message.embeds)) and (not contains or contains.lower() in message.content.lower())
        deleted = await interaction.channel.purge(limit=amount, check=check, reason=f"Purge by {interaction.user}")
        await interaction.followup.send(embed=ok(f"Deleted **{len(deleted)}** messages."), ephemeral=True)

    @app_commands.command(name="lockunlock", description="Lock or unlock the current channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.choices(action=[app_commands.Choice(name="Lock", value="lock"), app_commands.Choice(name="Unlock", value="unlock")])
    async def lockunlock(self, interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("This command only works in text channels.", ephemeral=True)
            return
        locked = action.value == "lock"
        await channel.set_permissions(interaction.guild.default_role, send_messages=not locked, reason=f"Channel {action.value} by {interaction.user}")
        await interaction.response.send_message(embed=ok(f"{channel.mention} is now {'locked' if locked else 'unlocked'}."))

    @app_commands.command(name="lockdown", description="Lock or unlock every text channel in the server")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.choices(action=[app_commands.Choice(name="Lock all channels", value="lock"), app_commands.Choice(name="Unlock all channels", value="unlock")])
    async def lockdown(self, interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
        locked = action.value == "lock"
        if not await self._confirm(interaction, f"{action.name} across **all text channels**? This can disrupt the whole server."):
            return
        changed = 0
        for channel in interaction.guild.text_channels:  # type: ignore[union-attr]
            try:
                await channel.set_permissions(interaction.guild.default_role, send_messages=not locked, reason=f"Server lockdown by {interaction.user}")  # type: ignore[union-attr]
                changed += 1
            except discord.HTTPException:
                continue
        await interaction.followup.send(embed=ok(f"{action.name} in **{changed}** channels."))

    @app_commands.command(name="slowmode", description="Set the current channel's slowmode")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]) -> None:
        if not hasattr(interaction.channel, "edit"):
            await interaction.response.send_message("This is not a configurable channel.", ephemeral=True)
            return
        await interaction.channel.edit(slowmode_delay=seconds, reason=f"Slowmode by {interaction.user}")
        await interaction.response.send_message(embed=ok(f"Slowmode set to **{seconds}s**."))

    @app_commands.command(name="nickname", description="Set or reset a member's server nickname")
    @app_commands.default_permissions(manage_nicknames=True)
    @app_commands.guild_only()
    async def nickname(self, interaction: discord.Interaction, member: discord.Member, nickname: Optional[str] = None) -> None:
        can_moderate(interaction.user, member)  # type: ignore[arg-type]
        await member.edit(nick=nickname, reason=f"Nickname changed by {interaction.user}")
        await interaction.response.send_message(embed=ok(f"Nickname {'reset' if nickname is None else 'updated'} for {member.mention}."))

    @app_commands.command(name="modlogs", description="View a member's moderation case history")
    @app_commands.default_permissions(view_audit_log=True)
    @app_commands.guild_only()
    async def modlogs(self, interaction: discord.Interaction, member: discord.Member) -> None:
        rows = await self.bot.db.cases(interaction.guild_id, member.id)
        if not rows:
            await interaction.response.send_message(embed=embed("Moderation history", "No cases found."))
            return
        pages = []
        for offset in range(0, len(rows), 8):
            description = "\n".join(f"**#{r['id']} {r['action'].upper()}** • <t:{int(__import__('datetime').datetime.fromisoformat(r['created_at']).timestamp())}:f>\n{r['reason']}" for r in rows[offset:offset + 8])
            pages.append(embed(f"Moderation history — {member}", description))
        view = Paginator(interaction.user.id, pages)
        await interaction.response.send_message(embed=pages[0], view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
