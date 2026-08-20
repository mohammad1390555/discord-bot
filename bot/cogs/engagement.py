from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import info, ok


class ConfessionModal(discord.ui.Modal, title="Anonymous confession"):
    body = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, channel: discord.TextChannel) -> None:
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.channel.send(embed=info(str(self.body), title="Anonymous confession"))
        await interaction.response.send_message("Posted anonymously.", ephemeral=True)


class Engagement(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def on(self, guild_id: int) -> bool:
        return bool(await self.bot.db.setting(guild_id, "modules.engagement", True))

    @app_commands.command(name="starboard", description="Set the starboard channel and threshold")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def starboard(self, interaction: discord.Interaction, channel: discord.TextChannel, threshold: app_commands.Range[int, 1, 25] = 3) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{"starboard.channel_id": channel.id, "starboard.threshold": int(threshold)})
        await interaction.response.send_message(embed=ok(f"Starboard: {channel.mention} at {threshold} stars."))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or not await self.on(payload.guild_id):
            return
        cfg = (await self.bot.db.get_guild(payload.guild_id))["settings"].get("starboard") or {}
        channel_id = cfg.get("channel_id")
        if not channel_id or str(payload.emoji) != str(cfg.get("emoji") or "⭐"):
            return
        guild = self.bot.get_guild(payload.guild_id)
        source = guild.get_channel(payload.channel_id) if guild else None
        dest = guild.get_channel(channel_id) if guild else None
        if not isinstance(source, discord.TextChannel) or not isinstance(dest, discord.TextChannel):
            return
        try:
            message = await source.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == str(payload.emoji):
                count = reaction.count
                break
        if count < int(cfg.get("threshold") or 3):
            return
        embed = info(message.content or "*attachment*")
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Jump", value=f"[Open]({message.jump_url})")
        await dest.send(content=f"⭐ **{count}** | {source.mention}", embed=embed)

    @app_commands.command(name="confess", description="Submit an anonymous confession to a channel")
    @app_commands.guild_only()
    async def confess(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not await self.on(interaction.guild_id):
            await interaction.response.send_message("Engagement module is disabled.", ephemeral=True)
            return
        await interaction.response.send_modal(ConfessionModal(channel))

    @app_commands.command(name="birthday", description="Save your birthday as MM-DD")
    @app_commands.guild_only()
    async def birthday(self, interaction: discord.Interaction, date: str) -> None:
        if len(date) != 5 or date[2] != "-":
            await interaction.response.send_message("Use MM-DD, for example 08-20.", ephemeral=True)
            return
        await self.bot.db.set_settings(interaction.guild_id, **{f"birthdays.{interaction.user.id}": date})
        await interaction.response.send_message(embed=ok(f"Birthday saved as `{date}`."), ephemeral=True)

    @app_commands.command(name="suggestbox", description="Send an anonymous suggestion")
    @app_commands.guild_only()
    async def suggestbox(self, interaction: discord.Interaction, text: str) -> None:
        channel_id = await self.bot.db.setting(interaction.guild_id, "suggestions_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else interaction.channel
        await channel.send(embed=info(text[:2000], title="Suggestion"))
        await interaction.response.send_message(embed=ok("Suggestion submitted."), ephemeral=True)

    @app_commands.command(name="lfg", description="Post a looking-for-group request")
    @app_commands.guild_only()
    async def lfg(self, interaction: discord.Interaction, activity: str, spots: app_commands.Range[int, 1, 10] = 3) -> None:
        view = discord.ui.View(timeout=3600)
        button = discord.ui.Button(label="Join", style=discord.ButtonStyle.success)

        async def join(inter: discord.Interaction) -> None:
            await inter.response.send_message(f"{inter.user.mention} joined **{activity}**.", ephemeral=False)

        button.callback = join  # type: ignore[method-assign]
        view.add_item(button)
        await interaction.response.send_message(
            embed=info(f"{interaction.user.mention} is looking for **{spots}** more for **{activity}**."),
            view=view,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Engagement(bot))
