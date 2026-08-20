from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import error, ok


class VoiceTools(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.temp: dict[int, int] = {}  # channel_id -> owner_id

    async def on(self, guild_id: int) -> bool:
        return bool(await self.bot.db.setting(guild_id, "modules.voice", True))

    @app_commands.command(name="jointocreate", description="Set the Join-to-Create voice channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def jointocreate(self, interaction: discord.Interaction, channel: discord.VoiceChannel | None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, join_to_create_channel_id=channel.id if channel else None)
        await interaction.response.send_message(embed=ok(f"Join-to-Create: {channel.mention}." if channel else "Join-to-Create disabled."))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if not member.guild or not await self.on(member.guild.id):
            return
        hub_id = await self.bot.db.setting(member.guild.id, "join_to_create_channel_id")
        if after.channel and hub_id and after.channel.id == hub_id:
            category = after.channel.category
            name = str(self.bot.settings.get("voice.temp_channel_name", "{user}'s channel")).format(user=member.display_name)
            try:
                created = await member.guild.create_voice_channel(name[:100], category=category, reason="Join to create")
                await member.move_to(created)
                self.temp[created.id] = member.id
            except discord.HTTPException:
                return
        if before.channel and before.channel.id in self.temp and not before.channel.members:
            try:
                await before.channel.delete(reason="Empty temporary voice channel")
            except discord.HTTPException:
                pass
            self.temp.pop(before.channel.id, None)

    @app_commands.command(name="vclock", description="Lock your temporary voice channel")
    @app_commands.guild_only()
    async def vclock(self, interaction: discord.Interaction) -> None:
        channel = getattr(interaction.user, "voice", None)
        channel = channel.channel if channel else None
        if not isinstance(channel, discord.VoiceChannel) or self.temp.get(channel.id) != interaction.user.id:
            await interaction.response.send_message(embed=error("You can only lock a temporary channel you own."), ephemeral=True)
            return
        await channel.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message(embed=ok("Channel locked."), ephemeral=True)

    @app_commands.command(name="vclimit", description="Set the user limit on your temporary voice channel")
    @app_commands.guild_only()
    async def vclimit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]) -> None:
        channel = getattr(interaction.user, "voice", None)
        channel = channel.channel if channel else None
        if not isinstance(channel, discord.VoiceChannel) or self.temp.get(channel.id) != interaction.user.id:
            await interaction.response.send_message(embed=error("You can only configure a temporary channel you own."), ephemeral=True)
            return
        await channel.edit(user_limit=int(limit))
        await interaction.response.send_message(embed=ok(f"User limit set to {limit}."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceTools(bot))
