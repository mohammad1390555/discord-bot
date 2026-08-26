"""Voice tools with Join-to-Create and a full button control panel for temp channels."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import iso
from bot.utils.embeds import BRAND, embed, error, ok
from bot.utils.modules import ModuleCog, module_enabled


class TempVCControlView(discord.ui.View):
    """Persistent button panel posted in every temporary voice channel.

    Only the channel owner (or members with Manage Channels) may use it.
    """

    def __init__(self, cog: "VoiceTools") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def _context(self, interaction: discord.Interaction):
        row = await self.cog.bot.db.fetchone(
            "SELECT * FROM temp_voice WHERE channel_id=?", (interaction.channel_id,))
        if not row or row["owner_id"] != interaction.user.id:
            member = interaction.user
            is_admin = isinstance(member, discord.Member) and member.guild_permissions.manage_channels
            if not is_admin:
                await interaction.response.send_message(
                    "Only the channel owner can use these controls.", ephemeral=True)
                return None
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("Not a voice channel.", ephemeral=True)
            return None
        return {"row": row, "channel": interaction.channel}

    @staticmethod
    def _status_embed(channel: discord.VoiceChannel, locked: bool) -> discord.Embed:
        members = ", ".join(m.display_name for m in channel.members[:20]) or "empty"
        return embed(
            "\U0001F50A Voice channel controls",
            f"**Channel:** {channel.name}\n"
            f"**Limit:** {channel.user_limit or 'unlimited'}\n"
            f"**Status:** {'locked' if locked else 'open'}\n"
            f"**Connected:** {len(channel.members)} - {members}",
            colour=BRAND)

    @discord.ui.button(label="Lock", emoji="\U0001F512", style=discord.ButtonStyle.danger,
                       custom_id="aegis:vc:lock")
    async def lock(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ctx = await self._context(interaction)
        if not ctx:
            return
        await ctx["channel"].set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message(embed=self._status_embed(ctx["channel"], True),
                                                ephemeral=True)

    @discord.ui.button(label="Unlock", emoji="\U0001F513", style=discord.ButtonStyle.success,
                       custom_id="aegis:vc:unlock")
    async def unlock(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ctx = await self._context(interaction)
        if not ctx:
            return
        await ctx["channel"].set_permissions(interaction.guild.default_role, connect=True)
        await interaction.response.send_message(embed=self._status_embed(ctx["channel"], False),
                                                ephemeral=True)

    @discord.ui.button(label="Hide", emoji="\U0001F441\uFE0F", style=discord.ButtonStyle.secondary,
                       custom_id="aegis:vc:hide")
    async def hide(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ctx = await self._context(interaction)
        if not ctx:
            return
        await ctx["channel"].set_permissions(interaction.guild.default_role,
                                             view_channel=False)
        await interaction.response.send_message(embed=ok("Channel hidden from @everyone."),
                                                ephemeral=True)

    @discord.ui.button(label="Show", emoji="\U0001F441", style=discord.ButtonStyle.secondary,
                       custom_id="aegis:vc:show")
    async def show(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ctx = await self._context(interaction)
        if not ctx:
            return
        await ctx["channel"].set_permissions(interaction.guild.default_role,
                                             view_channel=True)
        await interaction.response.send_message(embed=ok("Channel visible again."),
                                                ephemeral=True)

    @discord.ui.button(label="Limit", emoji="\U0001F465", style=discord.ButtonStyle.secondary,
                       custom_id="aegis:vc:limit")
    async def limit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ctx = await self._context(interaction)
        if not ctx:
            return
        await interaction.response.send_modal(LimitModal(self.cog, ctx["channel"]))

    @discord.ui.button(label="Claim", emoji="\U0001F3AB", style=discord.ButtonStyle.primary,
                       custom_id="aegis:vc:claim")
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        # Allow a connected member to take over when the owner left.
        row = await self.cog.bot.db.fetchone(
            "SELECT * FROM temp_voice WHERE channel_id=?", (interaction.channel_id,))
        if not row or not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("No claimable channel here.", ephemeral=True)
            return
        owner_present = any(m.id == row["owner_id"] for m in interaction.channel.members)
        if owner_present:
            await interaction.response.send_message(
                "The owner is still connected.", ephemeral=True)
            return
        await self.cog.bot.db.execute("UPDATE temp_voice SET owner_id=? WHERE channel_id=?",
                                      (interaction.user.id, interaction.channel_id))
        await interaction.response.send_message(
            embed=ok(f"{interaction.user.mention} is the new channel owner."), ephemeral=True)


class LimitModal(discord.ui.Modal, title="Set user limit"):
    value = discord.ui.TextInput(label="User limit (0-99, 0 = unlimited)",
                                 max_length=2, placeholder="5")

    def __init__(self, cog: "VoiceTools", channel: discord.VoiceChannel) -> None:
        super().__init__()
        self.cog = cog
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message("Enter a number between 0 and 99.",
                                                    ephemeral=True)
            return
        limit = min(int(raw), 99)
        await self.channel.edit(user_limit=limit)
        await interaction.response.send_message(
            embed=ok(f"User limit set to **{limit or 'unlimited'}**."), ephemeral=True)


class VoiceTools(ModuleCog):
    module_name = "voice"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._stay_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        # Drop records for channels that vanished while the bot was offline.
        rows = await self.bot.db.fetchall("SELECT channel_id FROM temp_voice")
        for row in rows:
            if self.bot.get_channel(row["channel_id"]) is None:
                await self.bot.db.execute("DELETE FROM temp_voice WHERE channel_id=?",
                                          (row["channel_id"],))
        self.bot.add_view(TempVCControlView(self))

    # ------------------------------------------------------------------
    # /voice - keep the bot sitting in a chosen voice channel
    # ------------------------------------------------------------------

    @app_commands.command(name="voice",
                          description="Make the bot join and stay in a voice channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.describe(
        channel="The voice channel the bot should sit in",
        action="Join or leave")
    @app_commands.choices(action=[
        app_commands.Choice(name="Join and stay", value="join"),
        app_commands.Choice(name="Leave", value="leave"),
    ])
    async def voice(self, interaction: discord.Interaction,
                    channel: discord.VoiceChannel | None = None,
                    action: app_commands.Choice[str] | None = None) -> None:
        guild = interaction.guild
        if guild is None:
            return
        mode = action.value if action else "join"

        if mode == "leave":
            await self._stop_stay(guild.id)
            vc = guild.voice_client
            if vc and vc.is_connected():
                await vc.disconnect(force=False)
                await interaction.response.send_message(embed=ok("Left the voice channel."))
            else:
                await interaction.response.send_message(
                    embed=error("I am not in a voice channel."), ephemeral=True)
            return

        if channel is None:
            await interaction.response.send_message(
                "Pick a voice channel to join.", ephemeral=True)
            return
        perms = channel.permissions_for(guild.me)
        if not (perms.connect and perms.view_channel):
            await interaction.response.send_message(
                embed=error(f"I lack **Connect/View** permission for {channel.mention}."),
                ephemeral=True)
            return

        await interaction.response.defer()
        await self._stop_stay(guild.id)  # replace any previous stay loop
        try:
            vc = await channel.connect(self_deaf=True)
        except discord.ClientException:
            vc = guild.voice_client  # already connected somewhere; move instead
            if vc is not None:
                await vc.move_to(channel)
        except discord.HTTPException:
            await interaction.followup.send(embed=error("Could not join that channel."))
            return
        self._start_stay(guild.id, channel.id)
        status = embed(
            "\U0001F50A Voice presence enabled",
            f"I will stay connected to {channel.mention} and do nothing.\n"
            "Use `/voice action:Leave` to remove me.",
            colour=BRAND)
        await interaction.followup.send(embed=status)

    def _start_stay(self, guild_id: int, channel_id: int) -> None:
        """Background watchdog: silently re-joins if disconnected or moved."""
        async def _watch() -> None:
            await asyncio.sleep(5)
            while True:
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    return
                vc = guild.voice_client
                target = guild.get_channel(channel_id)
                if target is None or not isinstance(target, discord.VoiceChannel):
                    return  # channel deleted; stop watching
                try:
                    if vc is None or not vc.is_connected():
                        await target.connect(self_deaf=True, timeout=30.0)
                    elif vc.channel and vc.channel.id != channel_id:
                        await vc.move_to(target)
                except (discord.HTTPException, asyncio.TimeoutError):
                    pass  # transient; retry next tick
                await asyncio.sleep(20)

        task = asyncio.create_task(_watch())
        self._stay_tasks[guild_id] = task

    async def _stop_stay(self, guild_id: int) -> None:
        task = self._stay_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    async def cog_unload(self) -> None:  # type: ignore[override]
        for task in self._stay_tasks.values():
            task.cancel()
        self._stay_tasks.clear()

    @app_commands.command(name="jointocreate",
                          description="Set the Join-to-Create voice channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def jointocreate(self,
                           interaction: discord.Interaction,
                           channel: discord.VoiceChannel | None) -> None:
        await self.bot.db.set_settings(
            interaction.guild_id,
            join_to_create_channel_id=channel.id if channel else None)
        await interaction.response.send_message(
            embed=ok(f"Join-to-Create: {channel.mention}." if channel
                     else "Join-to-Create disabled."))

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState,
        after: discord.VoiceState) -> None:
        if not member.guild or not await module_enabled(self.bot, member.guild.id, "voice"):
            return
        hub_id = await self.bot.db.setting(member.guild.id, "join_to_create_channel_id")

        # Create a temp channel when someone joins the hub.
        if after.channel and hub_id and after.channel.id == hub_id:
            category = after.channel.category
            name = str(self.bot.settings.get("voice.temp_channel_name",
                                             "{user}'s channel")).format(
                                                 user=member.display_name)
            try:
                created = await member.guild.create_voice_channel(
                    name[:100], category=category, reason="Join to create")
                await member.move_to(created)
                await self.bot.db.execute(
                    "INSERT OR REPLACE INTO temp_voice"
                    " (channel_id,guild_id,owner_id,created_at) VALUES (?,?,?,?)",
                    (created.id, member.guild.id, member.id, iso()))
            except discord.HTTPException:
                return
            # Post the persistent control panel into an affiliated text spot:
            # Discord has no text chat in pure voice channels for bots before
            # Stage/Text-in-Voice; keep a short-lived status message instead.
            try:
                panel_note = embed(
                    "\U0001F50A Your temporary channel",
                    "Use `/vclock`, `/vclimit`, `/vchide` or ask staff for help.\n"
                    "The channel deletes automatically when empty.",
                    colour=BRAND)
                # Best-effort: find a text channel in the same category.
                text_spot = next(
                    (c for c in member.guild.text_channels
                     if c.category == category and c.permissions_for(member.guild.me).send_messages),
                    None)
                if text_spot:
                    await text_spot.send(
                        content=f"{member.mention}",
                        embed=panel_note,
                        view=TempVCControlView(self),
                        delete_after=120.0)
            except discord.HTTPException:
                pass

        # Delete empty temp channels.
        if before.channel:
            owned = await self.bot.db.fetchone(
                "SELECT * FROM temp_voice WHERE channel_id=?", (before.channel.id,))
            if owned and not before.channel.members:
                try:
                    await before.channel.delete(reason="Empty temporary voice channel")
                except discord.HTTPException:
                    pass
                await self.bot.db.execute("DELETE FROM temp_voice WHERE channel_id=?",
                                          (before.channel.id,))

    async def _owned_channel(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        voice = getattr(interaction.user, "voice", None)
        channel = voice.channel if voice else None
        if not isinstance(channel, discord.VoiceChannel):
            return None
        row = await self.bot.db.fetchone(
            "SELECT * FROM temp_voice WHERE channel_id=? AND owner_id=?",
            (channel.id, interaction.user.id))
        return channel if row else None

    @app_commands.command(name="vclock", description="Lock your temporary voice channel")
    @app_commands.guild_only()
    async def vclock(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel(interaction)
        if not channel or not interaction.guild:
            await interaction.response.send_message(
                embed=error("You can only lock a temporary channel you own."), ephemeral=True)
            return
        await channel.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message(embed=ok("Channel locked."), ephemeral=True)

    @app_commands.command(name="vcunlock", description="Unlock your temporary voice channel")
    @app_commands.guild_only()
    async def vcunlock(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel(interaction)
        if not channel or not interaction.guild:
            await interaction.response.send_message(
                embed=error("You can only unlock a temporary channel you own."), ephemeral=True)
            return
        await channel.set_permissions(interaction.guild.default_role, connect=True)
        await interaction.response.send_message(embed=ok("Channel unlocked."), ephemeral=True)

    @app_commands.command(name="vclimit", description="Set the user limit on your temporary voice channel")
    @app_commands.guild_only()
    async def vclimit(self, interaction: discord.Interaction,
                      limit: app_commands.Range[int, 0, 99]) -> None:
        channel = await self._owned_channel(interaction)
        if not channel:
            await interaction.response.send_message(
                embed=error("You can only configure a temporary channel you own."), ephemeral=True)
            return
        await channel.edit(user_limit=int(limit))
        await interaction.response.send_message(
            embed=ok(f"User limit set to {limit}."), ephemeral=True)

    @app_commands.command(name="vckick", description="Disconnect a member from your temp channel")
    @app_commands.guild_only()
    async def vckick(self, interaction: discord.Interaction,
                     member: discord.Member) -> None:
        channel = await self._owned_channel(interaction)
        if not channel:
            await interaction.response.send_message(
                embed=error("You can only manage a temporary channel you own."), ephemeral=True)
            return
        if member.voice is None or member.voice.channel is None \
                or member.voice.channel.id != channel.id:
            await interaction.response.send_message(
                embed=error(f"{member.display_name} is not in your channel."), ephemeral=True)
            return
        try:
            await member.move_to(None, reason=f"Kicked from temp VC by {interaction.user}")
            await interaction.response.send_message(
                embed=ok(f"Disconnected {member.mention}."), ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message(
                embed=error("I could not disconnect that member."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceTools(bot))
