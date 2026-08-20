from __future__ import annotations

import json
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import parse_iso, utcnow
from bot.utils.embeds import embed, ok
from bot.utils.time import human_duration, parse_duration
from bot.utils.ui import ConfirmView


class GiveawayView(discord.ui.View):
    def __init__(self, cog: "Giveaways") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Enter", style=discord.ButtonStyle.success, emoji="🎉", custom_id="aegis:giveaway:enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        giveaway = await self.cog.bot.db.fetchone("SELECT * FROM giveaways WHERE message_id=? AND ended_at IS NULL", (interaction.message.id if interaction.message else 0,))
        if not giveaway:
            await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
            return
        role_id = giveaway["required_role_id"]
        if role_id and (not isinstance(interaction.user, discord.Member) or role_id not in {role.id for role in interaction.user.roles}):
            await interaction.response.send_message("You do not have the required role to enter.", ephemeral=True)
            return
        entry = await self.cog.bot.db.fetchone("SELECT * FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (giveaway["id"], interaction.user.id))
        if entry:
            await self.cog.bot.db.execute("DELETE FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (giveaway["id"], interaction.user.id))
            message = "Your entry was removed."
        else:
            await self.cog.bot.db.execute("INSERT INTO giveaway_entries (giveaway_id,user_id,entered_at) VALUES (?,?,?)", (giveaway["id"], interaction.user.id, discord.utils.utcnow().isoformat()))
            message = "You are entered. Good luck!"
        await interaction.response.send_message(message, ephemeral=True)


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.scheduler.register("giveaway_end", self._finish)
        self.bot.add_view(GiveawayView(self))

    async def _finish(self, giveaway_id_payload: dict) -> None:
        giveaway_id = int(giveaway_id_payload["giveaway_id"])
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=? AND ended_at IS NULL", (giveaway_id,))
        if not giveaway:
            return
        entries = await self.bot.db.fetchall("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (giveaway_id,))
        pool = [row["user_id"] for row in entries]
        winners = random.sample(pool, min(giveaway["winners"], len(pool))) if pool else []
        await self.bot.db.execute("UPDATE giveaways SET ended_at=?, winner_ids=? WHERE id=?", (discord.utils.utcnow().isoformat(), json.dumps(winners), giveaway_id))
        channel = self.bot.get_channel(giveaway["channel_id"])
        if not channel or not hasattr(channel, "send"):
            return
        mention = ", ".join(f"<@{user_id}>" for user_id in winners) or "Nobody entered."
        try:
            await channel.send(embed=embed("Giveaway ended", f"**Prize:** {giveaway['prize']}\n**Winner{'s' if len(winners) != 1 else ''}:** {mention}", colour=discord.Colour(0xFEE75C)))
            message = await channel.fetch_message(giveaway["message_id"]) if giveaway["message_id"] else None
            if message:
                ending = message.embeds[0].copy() if message.embeds else embed("Giveaway ended")
                ending.description = f"**Prize:** {giveaway['prize']}\nThis giveaway has ended."
                await message.edit(embed=ending, view=None)
        except discord.HTTPException:
            pass

    @app_commands.command(name="gcreate", description="Start a button-based giveaway")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def gcreate(self, interaction: discord.Interaction, prize: str, duration: str, winners: app_commands.Range[int, 1, 20], required_role: discord.Role | None = None) -> None:
        try:
            delta = parse_duration(duration, maximum=30 * 86400)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        ends = discord.utils.utcnow() + delta
        await interaction.response.defer()
        giveaway_id = await self.bot.db.execute("INSERT INTO giveaways (guild_id,channel_id,host_id,prize,winners,required_role_id,ends_at) VALUES (?,?,?,?,?,?,?)", (interaction.guild_id, interaction.channel_id, interaction.user.id, prize[:250], winners, required_role.id if required_role else None, ends.isoformat()))
        view = GiveawayView(self)
        message = await interaction.channel.send(embed=embed("🎉 Giveaway", f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(ends.timestamp())}:R>\n**Hosted by:** {interaction.user.mention}\n{f'**Required role:** {required_role.mention}' if required_role else ''}", colour=discord.Colour(0xFEE75C)), view=view)
        await self.bot.db.execute("UPDATE giveaways SET message_id=? WHERE id=?", (message.id, giveaway_id))
        await self.bot.db.schedule("giveaway_end", ends, {"giveaway_id": giveaway_id})
        await interaction.followup.send(embed=ok(f"Giveaway **#{giveaway_id}** created."), ephemeral=True)

    @app_commands.command(name="gend", description="End an active giveaway now")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def gend(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=? AND guild_id=? AND ended_at IS NULL", (giveaway_id, interaction.guild_id))
        if not row:
            await interaction.response.send_message("Active giveaway not found.", ephemeral=True)
            return
        confirmation = ConfirmView(interaction.user.id)
        await interaction.response.send_message(embed=embed("End giveaway?", f"This immediately selects winners for giveaway **#{giveaway_id}**."), view=confirmation, ephemeral=True)
        await confirmation.wait()
        if not confirmation.confirmed:
            return
        await self._finish({"giveaway_id": giveaway_id})
        await interaction.followup.send(embed=ok(f"Giveaway **#{giveaway_id}** ended."), ephemeral=True)

    @app_commands.command(name="greroll", description="Choose a fresh winner for an ended giveaway")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def greroll(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=? AND guild_id=? AND ended_at IS NOT NULL", (giveaway_id, interaction.guild_id))
        if not row:
            await interaction.response.send_message("Ended giveaway not found.", ephemeral=True)
            return
        entries = await self.bot.db.fetchall("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (giveaway_id,))
        old = set(json.loads(row["winner_ids"]))
        pool = [entry["user_id"] for entry in entries if entry["user_id"] not in old]
        if not pool:
            await interaction.response.send_message("There are no alternate entrants.", ephemeral=True)
            return
        winner = random.choice(pool)
        await interaction.response.send_message(embed=ok(f"New winner for giveaway **#{giveaway_id}**: <@{winner}> 🎉"))

    @app_commands.command(name="glist", description="List active giveaways")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def glist(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall("SELECT * FROM giveaways WHERE guild_id=? AND ended_at IS NULL ORDER BY ends_at", (interaction.guild_id,))
        description = "\n".join(f"**#{row['id']}** {row['prize']} • ends in {human_duration(max(0, int((parse_iso(row['ends_at']) - utcnow()).total_seconds())))} • <#{row['channel_id']}>" for row in rows)
        await interaction.response.send_message(embed=embed("Active giveaways", description or "No active giveaways."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaways(bot))
