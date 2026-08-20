from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import info, ok
from bot.utils.modules import ModuleCog, module_enabled


class ConfessionModal(discord.ui.Modal, title="Anonymous confession"):
    body = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, channel: discord.TextChannel) -> None:
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.channel.send(embed=info(str(self.body), title="Anonymous confession"))
        except discord.HTTPException:
            await interaction.response.send_message("I could not post that confession.", ephemeral=True)
            return
        await interaction.response.send_message("Posted anonymously.", ephemeral=True)


class LFGView(discord.ui.View):
    def __init__(self, host_id: int, activity: str, spots: int) -> None:
        super().__init__(timeout=3600)
        self.host_id = host_id
        self.activity = activity
        self.spots = spots
        self.joined: list[int] = [host_id]

    def _embed(self, host: discord.abc.User) -> discord.Embed:
        mentions = " ".join(f"<@{uid}>" for uid in self.joined)
        remaining = max(0, self.spots - (len(self.joined) - 1))
        return info(
            f"{host.mention} is looking for **{self.spots}** more for **{self.activity}**.\n"
            f"**Party:** {mentions}\n**Spots left:** {remaining}"
        )

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        uid = interaction.user.id
        if uid in self.joined:
            if uid == self.host_id:
                await interaction.response.send_message("You're hosting this party.", ephemeral=True)
                return
            self.joined.remove(uid)
            action = "left"
        else:
            if len(self.joined) - 1 >= self.spots:
                await interaction.response.send_message("This party is full.", ephemeral=True)
                return
            self.joined.append(uid)
            action = "joined"
        host = interaction.guild.get_member(self.host_id) if interaction.guild else interaction.user
        await interaction.response.edit_message(embed=self._embed(host or interaction.user), view=self)
        try:
            await interaction.followup.send(f"{interaction.user.mention} {action} **{self.activity}**.", ephemeral=False)
        except discord.HTTPException:
            pass


class Engagement(ModuleCog):
    module_name = "engagement"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _starboard_update(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or not await module_enabled(self.bot, payload.guild_id, "engagement"):
            return
        if payload.user_id == (self.bot.user.id if self.bot.user else 0):
            return
        cfg = (await self.bot.db.get_guild(payload.guild_id))["settings"].get("starboard") or {}
        channel_id = cfg.get("channel_id")
        emoji = str(cfg.get("emoji") or "⭐")
        if not channel_id or str(payload.emoji) != emoji:
            return
        guild = self.bot.get_guild(payload.guild_id)
        source = guild.get_channel(payload.channel_id) if guild else None
        dest = guild.get_channel(channel_id) if guild else None
        if not isinstance(source, discord.TextChannel) or not isinstance(dest, discord.TextChannel):
            return
        if source.id == dest.id:
            return
        try:
            message = await source.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if message.author.bot:
            return
        count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == emoji:
                count = reaction.count
                break
        existing = await self.bot.db.fetchone(
            "SELECT * FROM starboard_messages WHERE source_message_id=?", (message.id,)
        )
        threshold = int(cfg.get("threshold") or 3)
        if count < threshold:
            if existing:
                try:
                    posted = await dest.fetch_message(existing["starboard_message_id"])
                    await posted.delete()
                except discord.HTTPException:
                    pass
                await self.bot.db.execute("DELETE FROM starboard_messages WHERE source_message_id=?", (message.id,))
            return
        card = info(message.content or "*attachment*")
        card.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        if message.attachments:
            card.set_image(url=message.attachments[0].url)
        card.add_field(name="Jump", value=f"[Open]({message.jump_url})")
        content = f"⭐ **{count}** | {source.mention}"
        if existing:
            try:
                posted = await dest.fetch_message(existing["starboard_message_id"])
                await posted.edit(content=content, embed=card)
                return
            except discord.HTTPException:
                await self.bot.db.execute("DELETE FROM starboard_messages WHERE source_message_id=?", (message.id,))
        posted = await dest.send(content=content, embed=card)
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO starboard_messages (source_message_id,starboard_message_id,channel_id,guild_id) VALUES (?,?,?,?)",
            (message.id, posted.id, dest.id, payload.guild_id),
        )

    @app_commands.command(name="starboard", description="Set the starboard channel and threshold")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def starboard(
        self, interaction: discord.Interaction, channel: discord.TextChannel, threshold: app_commands.Range[int, 1, 25] = 3
    ) -> None:
        await self.bot.db.set_settings(
            interaction.guild_id, **{"starboard.channel_id": channel.id, "starboard.threshold": int(threshold)}
        )
        await interaction.response.send_message(embed=ok(f"Starboard: {channel.mention} at {threshold} stars."))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._starboard_update(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._starboard_update(payload)

    @app_commands.command(name="confess", description="Submit an anonymous confession")
    @app_commands.guild_only()
    async def confess(self, interaction: discord.Interaction) -> None:
        channel_id = await self.bot.db.setting(interaction.guild_id, "confess_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id and interaction.guild else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Confessions are not set up. An admin can use `/config confess`.", ephemeral=True
            )
            return
        await interaction.response.send_modal(ConfessionModal(channel))

    @app_commands.command(name="birthday", description="Save your birthday as MM-DD")
    @app_commands.guild_only()
    async def birthday(self, interaction: discord.Interaction, date: str) -> None:
        try:
            parsed = datetime.strptime(date.strip(), "%m-%d")
        except ValueError:
            await interaction.response.send_message("Use MM-DD, for example 08-20.", ephemeral=True)
            return
        stored = f"{parsed.month:02d}-{parsed.day:02d}"
        await self.bot.db.set_settings(interaction.guild_id, **{f"birthdays.{interaction.user.id}": stored})
        await interaction.response.send_message(embed=ok(f"Birthday saved as `{stored}`."), ephemeral=True)

    @app_commands.command(name="suggestbox", description="Send an anonymous suggestion")
    @app_commands.guild_only()
    async def suggestbox(self, interaction: discord.Interaction, text: str) -> None:
        channel_id = await self.bot.db.setting(interaction.guild_id, "suggestions_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id and interaction.guild else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Suggestions are not set up. An admin can use `/config suggestions`.", ephemeral=True
            )
            return
        try:
            await channel.send(embed=info(text[:2000], title="Suggestion"))
        except discord.HTTPException:
            await interaction.response.send_message("I could not post that suggestion.", ephemeral=True)
            return
        await interaction.response.send_message(embed=ok("Suggestion submitted."), ephemeral=True)

    @app_commands.command(name="lfg", description="Post a looking-for-group request")
    @app_commands.guild_only()
    async def lfg(self, interaction: discord.Interaction, activity: str, spots: app_commands.Range[int, 1, 10] = 3) -> None:
        view = LFGView(interaction.user.id, activity[:100], int(spots))
        await interaction.response.send_message(embed=view._embed(interaction.user), view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Engagement(bot))
