from __future__ import annotations

import ast

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.extensions import EXTENSIONS
from bot.utils.embeds import embed, error, ok
from bot.utils.ui import ConfirmView, Paginator

ALLOWED_RELOADS = set(EXTENSIONS)


class Admin(commands.Cog):
    """Owner operations; eval is expression-only, never arbitrary exec."""

    owner = app_commands.Group(name="owner", description="Bot owner tools")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.bot.settings.owner_ids:
            if interaction.response.is_done():
                await interaction.followup.send("This command is owner-only.", ephemeral=True)
            else:
                await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return False
        return True

    @staticmethod
    def _safe_expression(source: str) -> ast.Expression:
        tree = ast.parse(source, mode="eval")
        allowed = (
            ast.Expression,
            ast.Constant,
            ast.List,
            ast.Tuple,
            ast.Dict,
            ast.Set,
            ast.BinOp,
            ast.UnaryOp,
            ast.BoolOp,
            ast.Compare,
            ast.operator,
            ast.unaryop,
            ast.boolop,
            ast.cmpop,
        )
        if any(not isinstance(node, allowed) for node in ast.walk(tree)):
            raise ValueError("Only literal values and basic arithmetic/comparisons are allowed.")
        return tree

    @owner.command(name="eval", description="Owner-only safe expression evaluator")
    async def evalexec(self, interaction: discord.Interaction, expression: str) -> None:
        if not await self._owner(interaction):
            return
        try:
            tree = self._safe_expression(expression[:500])
            result = eval(compile(tree, "<safe-eval>", "eval"), {"__builtins__": {}}, {})
        except (SyntaxError, ValueError, TypeError, NameError, ZeroDivisionError, OverflowError) as exc:
            await interaction.response.send_message(embed=error(f"Evaluation blocked: {exc}"), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embed("Safe evaluation", f"```py\n{str(result)[:1500]}\n```"), ephemeral=True
        )

    @owner.command(name="reload", description="Reload a feature cog without restarting")
    @app_commands.choices(extension=[app_commands.Choice(name=item.rsplit(".", 1)[-1], value=item) for item in EXTENSIONS])
    async def reload(self, interaction: discord.Interaction, extension: app_commands.Choice[str]) -> None:
        if not await self._owner(interaction):
            return
        if extension.value not in ALLOWED_RELOADS:
            await interaction.response.send_message("That cog is not reloadable or does not exist.", ephemeral=True)
            return
        await self.bot.reload_extension(extension.value)
        await interaction.response.send_message(embed=ok(f"Reloaded `{extension.value}`."), ephemeral=True)

    @owner.command(name="shutdown", description="Owner-only graceful bot shutdown")
    async def shutdown(self, interaction: discord.Interaction) -> None:
        if not await self._owner(interaction):
            return
        await interaction.response.send_message(embed=ok("Shutting down gracefully."), ephemeral=True)
        await self.bot.close()

    @owner.command(name="blacklist", description="Block a user or guild from using the bot")
    @app_commands.choices(
        kind=[app_commands.Choice(name="User", value="user"), app_commands.Choice(name="Guild", value="guild")]
    )
    async def blacklist(self, interaction: discord.Interaction, kind: app_commands.Choice[str], target_id: str, reason: str = "") -> None:
        if not await self._owner(interaction):
            return
        if not target_id.isdigit():
            await interaction.response.send_message("Target ID must be numeric.", ephemeral=True)
            return
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist (kind,target_id,reason,created_at) VALUES (?,?,?,?)",
            (kind.value, int(target_id), reason[:250], discord.utils.utcnow().isoformat()),
        )
        await interaction.response.send_message(embed=ok(f"{kind.name} `{target_id}` blacklisted."), ephemeral=True)

    @owner.command(name="unblacklist", description="Unblock a user or guild")
    @app_commands.choices(
        kind=[app_commands.Choice(name="User", value="user"), app_commands.Choice(name="Guild", value="guild")]
    )
    async def unblacklist(self, interaction: discord.Interaction, kind: app_commands.Choice[str], target_id: str) -> None:
        if not await self._owner(interaction):
            return
        if not target_id.isdigit():
            await interaction.response.send_message("Target ID must be numeric.", ephemeral=True)
            return
        await self.bot.db.execute("DELETE FROM blacklist WHERE kind=? AND target_id=?", (kind.value, int(target_id)))
        await interaction.response.send_message(embed=ok(f"{kind.name} `{target_id}` unblacklisted."), ephemeral=True)

    @owner.command(name="broadcast", description="Send an owner announcement to configured log channels")
    async def broadcast(self, interaction: discord.Interaction, message: str) -> None:
        if not await self._owner(interaction):
            return
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            embed=embed(
                "Broadcast confirmation",
                f"Send this to configured channels in **{len(self.bot.guilds)}** servers?\n\n{message[:500]}",
                colour=discord.Colour(0xFEE75C),
            ),
            view=view,
            ephemeral=True,
        )
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

    @owner.command(name="guilds", description="List servers the bot is connected to")
    async def guilds(self, interaction: discord.Interaction) -> None:
        if not await self._owner(interaction):
            return
        rows = sorted(self.bot.guilds, key=lambda guild: guild.member_count or 0, reverse=True)
        pages = []
        for offset in range(0, len(rows) or 1, 15):
            description = "\n".join(
                f"**{i}.** {guild.name} (`{guild.id}`) — {guild.member_count or 0:,} members"
                for i, guild in enumerate(rows[offset : offset + 15], offset + 1)
            )
            pages.append(embed("Connected guilds", description or "No guilds."))
        view = Paginator(interaction.user.id, pages)
        await view.send(interaction, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
