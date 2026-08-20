from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import info, ok
from bot.utils.i18n import text as localized

MODULES = [
    "moderation",
    "automod",
    "logging",
    "tickets",
    "giveaways",
    "leveling",
    "economy",
    "fun",
    "music",
    "utility",
    "protection",
    "engagement",
    "voice",
    "onboarding",
]


class ModuleSelect(discord.ui.Select):
    def __init__(self, cog: "Panel", enabled: dict[str, bool]) -> None:
        options = [
            discord.SelectOption(
                label=name.title(),
                value=name,
                description="Enabled" if enabled.get(name, True) else "Disabled",
                default=bool(enabled.get(name, True)),
            )
            for name in MODULES[:25]
        ]
        super().__init__(placeholder="Toggle modules (select enabled ones)", min_values=0, max_values=len(options), options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = set(self.values)
        updates = {f"modules.{name}": name in selected for name in MODULES}
        await self.cog.bot.db.set_settings(interaction.guild_id, **updates)
        saved = await localized(self.cog.bot, interaction.guild_id, "saved", "Your settings were saved.")
        on = ", ".join(sorted(selected)) or "none"
        await interaction.response.send_message(embed=ok(f"{saved}\nEnabled: `{on}`"), ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self, cog: "Panel", enabled: dict[str, bool], author_id: int) -> None:
        super().__init__(timeout=180)
        self.author_id = author_id
        self.add_item(ModuleSelect(cog, enabled))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command author can use this panel.", ephemeral=True)
            return False
        return True


class Panel(commands.Cog):
    """Interactive per-server feature dashboard."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="panel", description="Open the server module control panel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def panel(self, interaction: discord.Interaction) -> None:
        settings = (await self.bot.db.get_guild(interaction.guild_id))["settings"]
        enabled = settings.get("modules") or {}
        yaml_defaults = self.bot.settings.get("modules") or {}
        merged = {name: bool(enabled.get(name, yaml_defaults.get(name, True))) for name in MODULES}
        lines = [f"{'✅' if merged[n] else '❌'} **{n}**" for n in MODULES]
        title = await localized(self.bot, interaction.guild_id, "panel_title", "Aegis control panel")
        intro = await localized(self.bot, interaction.guild_id, "panel_intro", "Toggle modules for this server.")
        embed = info(intro + "\n\n" + "\n".join(lines))
        embed.title = title
        await interaction.response.send_message(embed=embed, view=PanelView(self, merged, interaction.user.id), ephemeral=True)

    @app_commands.command(name="module", description="Enable or disable a single module")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(name="Module name", enabled="On or off")
    @app_commands.choices(name=[app_commands.Choice(name=n, value=n) for n in MODULES])
    async def module(self, interaction: discord.Interaction, name: app_commands.Choice[str], enabled: bool) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{f"modules.{name.value}": enabled})
        key = "module_on" if enabled else "module_off"
        message = await localized(self.bot, interaction.guild_id, key, "Module **{name}** updated.", name=name.value)
        await interaction.response.send_message(embed=ok(message), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Panel(bot))
