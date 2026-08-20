from __future__ import annotations

import ast

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import embed, error, ok
from bot.utils.ui import ConfirmView, Paginator

ALLOWED_RELOADS = {
    "bot.cogs.admin", "bot.cogs.configuration", "bot.cogs.moderation", "bot.cogs.automod",
    "bot.cogs.logging_events", "bot.cogs.utility", "bot.cogs.tickets", "bot.cogs.giveaways",
    "bot.cogs.leveling", "bot.cogs.economy", "bot.cogs.fun", "bot.cogs.music",
}


class Admin(commands.Cog):
    """Owner operations; evalexec is expression-only, never arbitrary exec."""
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.bot.settings.owner_ids:
            await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return False
        return True

    @staticmethod
    def _safe_expression(source: str) -> ast.Expression:
        tree = ast.parse(source, mode="eval")
        allowed = (ast.Expression, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.BinOp,
                   ast.UnaryOp, ast.BoolOp, ast.Compare, ast.operator, ast.unaryop, ast.boolop, ast.cmpop)
        if any(not isinstance(node, allowed) for node in ast.walk(tree)):
            raise ValueError("Only literal values and basic arithmetic/comparisons are allowed.")
        return tree

    @app_commands.command(name="evalexec", description="Owner-only safe expression evaluator")
    @app_commands.default_permissions(administrator=True)
    async def evalexec(self, interaction: discord.Interaction, expression: str) -> None:
        if not await self._owner(interaction):
            return
        try:
            tree = self._safe_expression(expression[:500])
            result = eval(compile(tree, "<safe-eval>", "eval"), {"__builtins__": {}}, {})
        except (SyntaxError, ValueError, TypeError, NameError, ZeroDivisionError) as exc:
            await interaction.response.send_message(embed=error(f"Evaluation blocked: {exc}"), ephemeral=True)
            return
        await interaction.response.send_message(embed=embed("Safe evaluation", f"```py\n{str(result)[:1500]}\n```"), ephemeral=True)

    @app_commands.command(name="reload", description="Reload a feature cog without restarting")
    @app_commands.default_permissions(administrator=True)
    async def reload(self, interaction: discord.Interaction, extension: str) -> None:
        if not await self._owner(interaction):
            return
        if extension not in ALLOWED_RELOADS:
            await interaction.response.send_message("That cog is not reloadable or does not exist.", ephemeral=True)
            return
        await self.bot.reload_extension(extension)
        await interaction.response.send_message(embed=ok(f"Reloaded `{extension}`."), ephemeral=True)

    @app_commands.command(name="shutdownrestart", description="Owner-only graceful bot shutdown")
    @app_commands.default_permissions(administrator=True)
    async def shutdownrestart(self, interaction: discord.Interaction, action: str = "shutdown") -> None:
        if not await self._owner(interaction):
            return
        if action.casefold() != "shutdown":
            await interaction.response.send_message("Restart is managed by your process supervisor. Use `shutdown` to stop gracefully.", ephemeral=True)
            return
        await interaction.response.send_message(embed=ok("Shutting down gracefully."), ephemeral=True)
        await self.bot.close()

    @app_commands.command(name="blacklistunblacklist", description="Block or unblock a user or guild")
    @app_commands.default_permissions(administrator=True)
    async def blacklistunblacklist(self, interaction: discord.Interaction, action: str, kind: str, target_id: str, reason: str = "") -> None:
        if not await self._owner(interaction):
            return
        if action not in {"blacklist", "unblacklist"} or kind not in {"user", "guild"} or not target_id.isdigit():
            await interaction.response.send_message("Use action `blacklist`/`unblacklist`, kind `user`/`guild`, and a numeric ID.", ephemeral=True)
            return
        if action == "blacklist":
            await self.bot.db.execute("INSERT OR REPLACE INTO blacklist (kind,target_id,reason,created_at) VALUES (?,?,?,?)", (kind, int(target_id), reason[:250], discord.utils.utcnow().isoformat()))
        else:
            await self.bot.db.execute("DELETE FROM blacklist WHERE kind=? AND target_id=?", (kind, int(target_id)))
        await interaction.response.send_message(embed=ok(f"{kind.title()} `{target_id}` {action}ed."), ephemeral=True)

    @app_commands.command(name="broadcast", description="Send an owner announcement to configured log channels")
    @app_commands.default_permissions(administrator=True)
    async def broadcast(self, interaction: discord.Interaction, message: str) -> None:
        if not await self._owner(interaction):
            return
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(embed=embed("Broadcast confirmation", f"Send this to configured channels in **{len(self.bot.guilds)}** servers?\n\n{message[:500]}", colour=discord.Colour(0xFEE75C)), view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            return
        sent = 0
        for guild in self.bot.guilds:
            channel_id = await self.bot.db.setting(guild.id, "log_channels.general")
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel and hasattr(channel, "send"):
                try:
                    await channel.send(embed=embed("Announcement", message[:2000]))
                    sent += 1
                except discord.HTTPException:
                    continue
        await interaction.followup.send(embed=ok(f"Broadcast delivered to {sent} servers."), ephemeral=True)

    @app_commands.command(name="guilds", description="List servers the bot is connected to")
    @app_commands.default_permissions(administrator=True)
    async def guilds(self, interaction: discord.Interaction) -> None:
        if not await self._owner(interaction):
            return
        rows = sorted(self.bot.guilds, key=lambda guild: guild.member_count or 0, reverse=True)
        pages = []
        for offset in range(0, len(rows) or 1, 15):
            description = "\n".join(f"**{i}.** {guild.name} (`{guild.id}`) — {guild.member_count or 0:,} members" for i, guild in enumerate(rows[offset:offset + 15], offset + 1))
            pages.append(embed("Connected guilds", description or "No guilds."))
        view = Paginator(interaction.user.id, pages)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
