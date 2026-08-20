from __future__ import annotations

import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import parse_iso
from bot.utils.embeds import embed, ok
from bot.utils.ui import Paginator


class Leveling(commands.Cog):
    """Cooldown-aware XP tracking with persistent leaderboards and role rewards."""
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cooldown_seconds = 60

    @staticmethod
    def level_for_xp(xp: int) -> int:
        return int((xp / 100) ** 0.5)

    @staticmethod
    def next_level_xp(level: int) -> int:
        return ((level + 1) ** 2) * 100

    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        settings = await self.bot.db.get_guild(message.guild.id)
        config = settings["settings"].get("leveling", {})
        if not config.get("enabled", True) or len(message.content) < 3:
            return
        user = await self.bot.db.upsert_user(message.guild.id, message.author.id)
        now = discord.utils.utcnow()
        if user.get("last_xp_at"):
            try:
                if (now - parse_iso(user["last_xp_at"])).total_seconds() < self.cooldown_seconds:
                    return
            except ValueError:
                pass
        gained = random.randint(int(config.get("xp_min", 8)), int(config.get("xp_max", 15)))
        old_level = int(user["level"])
        new_xp = int(user["xp"]) + gained
        new_level = self.level_for_xp(new_xp)
        await self.bot.db.update_user(message.guild.id, message.author.id, xp=new_xp, level=new_level, last_xp_at=now.isoformat())
        if new_level <= old_level:
            return
        channel_id = config.get("channel_id")
        channel = message.guild.get_channel(channel_id) if channel_id else message.channel
        template = config.get("message", "🎉 {user} reached level {level}!")
        if channel and hasattr(channel, "send"):
            await channel.send(embed=embed("Level up!", template.format(user=message.author.mention, level=new_level)))
        rewards = config.get("rewards", {})
        reward_id = rewards.get(str(new_level))
        role = message.guild.get_role(int(reward_id)) if reward_id else None
        if role and role < message.guild.me.top_role:  # type: ignore[union-attr]
            try:
                await message.author.add_roles(role, reason=f"Reached level {new_level}")
            except discord.HTTPException:
                pass

    @app_commands.command(name="ranklevel", description="Show your or another member's level and XP")
    @app_commands.guild_only()
    async def ranklevel(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        member = member or interaction.user
        user = await self.bot.db.upsert_user(interaction.guild_id, member.id)
        level, xp = int(user["level"]), int(user["xp"])
        current_floor = level * level * 100
        target = self.next_level_xp(level)
        progress = xp - current_floor
        needed = max(1, target - current_floor)
        filled = round(max(0, min(1, progress / needed)) * 16)
        bar = "█" * filled + "░" * (16 - filled)
        rank_row = await self.bot.db.fetchone("SELECT COUNT(*) AS rank FROM users WHERE guild_id=? AND xp>?", (interaction.guild_id, xp))
        result = embed(f"Rank — {member.display_name}", f"**Level {level}** • **{xp:,} XP**\n`{bar}` {progress:,}/{needed:,} to level {level + 1}\nServer rank: **#{(rank_row or {'rank': 0})['rank'] + 1}**")
        result.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="leaderboard", description="View the server XP leaderboard")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall("SELECT * FROM users WHERE guild_id=? ORDER BY xp DESC LIMIT 100", (interaction.guild_id,))
        pages = []
        for offset in range(0, len(rows) or 1, 10):
            page = rows[offset:offset + 10]
            lines = []
            for index, row in enumerate(page, offset + 1):
                member = interaction.guild.get_member(row["user_id"])
                lines.append(f"**{index}.** {member.mention if member else '`' + str(row['user_id']) + '`'} — level {row['level']} • {row['xp']:,} XP")
            pages.append(embed("XP leaderboard", "\n".join(lines) or "No XP recorded yet."))
        view = Paginator(interaction.user.id, pages)
        await interaction.response.send_message(embed=pages[0], view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="levelrole", description="Set a role reward for a level")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def levelrole(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 1000], role: Optional[discord.Role] = None) -> None:
        settings = await self.bot.db.get_guild(interaction.guild_id)
        rewards = settings["settings"].get("leveling", {}).get("rewards", {})
        if role:
            rewards[str(level)] = role.id
            message = f"Level {level} now awards {role.mention}."
        else:
            rewards.pop(str(level), None)
            message = f"Level {level} reward cleared."
        await self.bot.db.set_settings(interaction.guild_id, **{"leveling.rewards": rewards})
        await interaction.response.send_message(embed=ok(message))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leveling(bot))
