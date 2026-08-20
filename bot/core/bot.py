from __future__ import annotations

import logging
import os
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Settings
from bot.core.scheduler import PersistentScheduler
from bot.database import Database
from bot.utils.checks import UserFacingError
from bot.utils.embeds import error

log = logging.getLogger(__name__)


class AegisCommandTree(app_commands.CommandTree):
    """Application-command global gate for owner-managed user/guild blacklists."""
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        bot = self.client
        if interaction.user.id in bot.settings.owner_ids:
            return True
        user = await bot.db.fetchone("SELECT 1 FROM blacklist WHERE kind='user' AND target_id=?", (interaction.user.id,))
        guild = await bot.db.fetchone("SELECT 1 FROM blacklist WHERE kind='guild' AND target_id=?", (interaction.guild_id,)) if interaction.guild_id else None
        if user:
            raise app_commands.CheckFailure("You are blacklisted from using this bot.")
        if guild:
            raise app_commands.CheckFailure("This server is blacklisted from using this bot.")
        return True


class AegisBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = False
        intents.voice_states = True
        self.settings = settings
        super().__init__(
            command_prefix=self.prefix_for,
            tree_cls=AegisCommandTree,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            activity=discord.Game(name=settings.get("bot.activity", "/panel • all-in-one server tools")),
        )
        self.db = Database(settings.database_url)
        self.scheduler = PersistentScheduler(self.db)
        self.started_at = time.monotonic()
        self.deleted_messages: dict[int, dict[str, Any]] = {}
        self.edited_messages: dict[int, dict[str, Any]] = {}
        self.synced = False
        self.add_check(self._prefix_access_check)

    async def _prefix_access_check(self, context: commands.Context) -> bool:
        if context.author.id in self.settings.owner_ids:
            return True
        user = await self.db.fetchone("SELECT 1 FROM blacklist WHERE kind='user' AND target_id=?", (context.author.id,))
        guild = await self.db.fetchone("SELECT 1 FROM blacklist WHERE kind='guild' AND target_id=?", (context.guild.id,)) if context.guild else None
        return not user and not guild

    async def prefix_for(self, bot: commands.Bot, message: discord.Message) -> list[str]:
        if not message.guild:
            return commands.when_mentioned_or(self.settings.prefix)(bot, message)
        prefix = await self.db.setting(message.guild.id, "prefix", self.settings.prefix)
        return list(commands.when_mentioned_or(prefix)(bot, message))

    async def setup_hook(self) -> None:
        await self.db.connect()
        extensions = [
            "bot.cogs.admin",
            "bot.cogs.configuration",
            "bot.cogs.moderation",
            "bot.cogs.automod",
            "bot.cogs.logging_events",
            "bot.cogs.utility",
            "bot.cogs.tickets",
            "bot.cogs.giveaways",
            "bot.cogs.leveling",
            "bot.cogs.economy",
            "bot.cogs.fun",
            "bot.cogs.music",
            "bot.cogs.panel",
            "bot.cogs.protection",
            "bot.cogs.engagement",
            "bot.cogs.voice_tools",
        ]
        for extension in extensions:
            try:
                await self.load_extension(extension)
            except Exception:
                log.exception("Unable to load extension %s", extension)
                raise
        self.scheduler.start()
        # Sync globally by default. Set SYNC_GUILD_ID for fast development sync.
        sync_guild = os.getenv("SYNC_GUILD_ID", "").strip()
        if sync_guild.isdigit():
            guild = discord.Object(id=int(sync_guild))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to development guild %s", sync_guild)
        else:
            await self.tree.sync()
        self.synced = True

    async def close(self) -> None:
        await self.scheduler.stop()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Ready as %s in %d guilds using discord.py %s", self.user, len(self.guilds), discord.__version__)

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        if hasattr(context.command, "on_error"):
            return
        original = getattr(exception, "original", exception)
        if isinstance(original, commands.CommandNotFound):
            return
        if isinstance(original, (commands.MissingPermissions, commands.BotMissingPermissions)):
            message = "You do not have permission to use that command."
        elif isinstance(original, commands.CommandOnCooldown):
            message = f"Try again in {original.retry_after:.1f} seconds."
        elif isinstance(original, (commands.MissingRequiredArgument, commands.BadArgument)):
            message = f"Invalid command arguments: {original}"
        elif isinstance(original, UserFacingError):
            message = str(original)
        else:
            log.exception("Prefix command failed", exc_info=original)
            message = "I couldn't complete that request. Please try again later."
        await context.reply(embed=error(message, bot_name=self.settings.bot_name, version=self.settings.version), mention_author=False)

    async def on_app_command_error(self, interaction: discord.Interaction, exception: discord.app_commands.AppCommandError) -> None:
        original = getattr(exception, "original", exception)
        if isinstance(original, discord.app_commands.CommandOnCooldown):
            message = f"Try again in {original.retry_after:.1f} seconds."
        elif isinstance(original, discord.app_commands.MissingPermissions):
            message = "You do not have permission to use that command."
        elif isinstance(original, discord.app_commands.CheckFailure):
            message = str(original) or "You cannot use that command here."
        elif isinstance(original, (discord.Forbidden, discord.HTTPException)):
            log.warning("Discord rejected an interaction: %s", original)
            message = "Discord rejected that action. Check my role and channel permissions."
        else:
            log.exception("Slash command failed", exc_info=original)
            message = "I couldn't complete that request. Please try again later."
        response = error(message, bot_name=self.settings.bot_name, version=self.settings.version)
        if interaction.response.is_done():
            await interaction.followup.send(embed=response, ephemeral=True)
        else:
            await interaction.response.send_message(embed=response, ephemeral=True)

    @property
    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    @property
    def memory_mb(self) -> float:
        try:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except (ImportError, AttributeError):
            return 0.0
