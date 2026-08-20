from __future__ import annotations

import io
import json
import re
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import info, ok
from bot.utils.i18n import text as localized


class VerifyModal(discord.ui.Modal, title="Verification"):
    code = discord.ui.TextInput(label="Enter VERIFY to continue", max_length=6)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if str(self.code).strip().casefold() != "verify":
            await interaction.response.send_message("Verification failed. Try again.", ephemeral=True)
            return
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Verification only works inside a server.", ephemeral=True)
            return
        role_id = await interaction.client.db.setting(interaction.guild.id, "verification.role_id")  # type: ignore[attr-defined]
        role = interaction.guild.get_role(role_id) if role_id else None
        if not role:
            await interaction.response.send_message("Verification is not configured on this server.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Verification completed")
        except discord.HTTPException:
            await interaction.response.send_message("I could not assign the verified role. Check my role hierarchy.", ephemeral=True)
            return
        await interaction.response.send_message("You are verified. Welcome!", ephemeral=True)


class VerifyView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="✅", custom_id="aegis:verification:open")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(VerifyModal())


class RoleToggle(discord.ui.DynamicItem[discord.ui.Button], template=r"aegis:role:(?P<role_id>[0-9]+)"):
    def __init__(self, role_id: int, label: str = "Role") -> None:
        super().__init__(
            discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"aegis:role:{role_id}",
            )
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ) -> RoleToggle:
        return cls(int(match["role_id"]), item.label or "Role")

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This is a server-only role menu.", ephemeral=True)
            return
        role = interaction.guild.get_role(self.role_id)
        me = interaction.guild.me
        if not role or not me:
            await interaction.response.send_message("That role no longer exists.", ephemeral=True)
            return
        if role.is_default() or role.managed or role >= me.top_role:
            await interaction.response.send_message("I cannot assign that role.", ephemeral=True)
            return
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Self-role menu")
                message = f"Removed {role.mention}."
            else:
                await interaction.user.add_roles(role, reason="Self-role menu")
                message = f"Added {role.mention}."
        except discord.HTTPException:
            await interaction.response.send_message("I could not update your roles.", ephemeral=True)
            return
        await interaction.response.send_message(message, ephemeral=True)


def role_menu(roles: list[discord.Role]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for role in roles[:25]:
        view.add_item(RoleToggle(role.id, role.name))
    return view


class SetupModal(discord.ui.Modal, title="Server setup"):
    prefix = discord.ui.TextInput(label="Command prefix", placeholder="!", max_length=5, required=False)
    language = discord.ui.TextInput(label="Language (en or fa)", placeholder="en", max_length=2, required=False)

    def __init__(self, cog: Configuration) -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        prefix = str(self.prefix).strip() or self.cog.bot.settings.prefix
        language = str(self.language).strip().lower() or "en"
        if language not in {"en", "fa"}:
            language = "en"
        await self.cog.bot.db.set_settings(interaction.guild_id, prefix=prefix, language=language)
        saved = await localized(self.cog.bot, interaction.guild_id, "saved", "Setup saved.")
        await interaction.response.send_message(
            embed=ok(f"{saved} Prefix: `{prefix}` • Language: `{language}`"), ephemeral=True
        )


class SetupView(discord.ui.View):
    def __init__(self, cog: Configuration, author_id: int) -> None:
        super().__init__(timeout=180)
        self.cog, self.author_id = cog, author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the setup author can use this wizard.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Open wizard", style=discord.ButtonStyle.primary, emoji="⚙️")
    async def wizard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(SetupModal(self.cog))

    @discord.ui.button(label="Set this channel as logs", style=discord.ButtonStyle.secondary, emoji="📋")
    async def logs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.bot.db.set_settings(interaction.guild_id, **{"log_channels.general": interaction.channel_id})
        await interaction.response.send_message(embed=ok("This channel is now the general log channel."), ephemeral=True)


class Configuration(commands.Cog):
    """Per-guild settings and the interactive first-run wizard."""

    config = app_commands.Group(
        name="config",
        description="Configure Aegis for this server",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(VerifyView())
        self.bot.add_dynamic_items(RoleToggle)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(RoleToggle)

    @app_commands.command(name="setup", description="Open the interactive server setup wizard")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.db.get_guild(interaction.guild_id)
        description = (
            "Configure Aegis for this server. The wizard stores settings in the database and survives restarts.\n\n"
            f"**Prefix:** `{settings['prefix']}`\n**Language:** `{settings['language']}`\n"
            "Use the buttons below to begin, or `/config view` for the full list."
        )
        await interaction.response.send_message(embed=info(description), view=SetupView(self, interaction.user.id), ephemeral=True)

    @config.command(name="prefix", description="Set this server's optional legacy command prefix")
    async def setprefix(self, interaction: discord.Interaction, prefix: str) -> None:
        if not 1 <= len(prefix) <= 5 or any(ch.isspace() for ch in prefix):
            await interaction.response.send_message("Prefix must be 1–5 non-space characters.", ephemeral=True)
            return
        await self.bot.db.set_settings(interaction.guild_id, prefix=prefix)
        await interaction.response.send_message(embed=ok(f"The prefix is now `{prefix}`."))

    @config.command(name="language", description="Set the server language (English or Persian)")
    @app_commands.choices(
        language=[
            app_commands.Choice(name="English", value="en"),
            app_commands.Choice(name="Persian / فارسی", value="fa"),
        ]
    )
    async def setlanguage(self, interaction: discord.Interaction, language: app_commands.Choice[str]) -> None:
        await self.bot.db.set_settings(interaction.guild_id, language=language.value)
        message = "زبان روی فارسی تنظیم شد." if language.value == "fa" else "Language set to **English**."
        await interaction.response.send_message(embed=ok(message))

    @config.command(name="logs", description="Route a log category to a channel")
    async def setlogchannel(
        self,
        interaction: discord.Interaction,
        category: Literal["general", "moderation", "messages", "members", "voice", "invites", "server"],
        channel: discord.TextChannel,
    ) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{f"log_channels.{category}": channel.id})
        await interaction.response.send_message(embed=ok(f"{category.title()} logs will be sent to {channel.mention}."))

    @config.command(name="welcome", description="Set or disable the welcome channel and message")
    async def setwelcome(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        message: str | None = None,
    ) -> None:
        updates: dict = {}
        if channel is None and message is None:
            updates["welcome.channel_id"] = None
            text = "Welcome messages disabled."
        else:
            if channel:
                updates["welcome.channel_id"] = channel.id
            if message:
                updates["welcome.message"] = message[:1000]
            text = "Welcome settings updated. Variables: `{user}`, `{server}`, `{membercount}`."
        await self.bot.db.set_settings(interaction.guild_id, **updates)
        await interaction.response.send_message(embed=ok(text))

    @config.command(name="leave", description="Set or disable the leave channel and message")
    async def setleave(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        message: str | None = None,
    ) -> None:
        updates: dict = {}
        if channel is None and message is None:
            updates["leave.channel_id"] = None
            text = "Leave messages disabled."
        else:
            if channel:
                updates["leave.channel_id"] = channel.id
            if message:
                updates["leave.message"] = message[:1000]
            text = "Leave settings updated. Variables: `{user}`, `{server}`, `{membercount}`."
        await self.bot.db.set_settings(interaction.guild_id, **updates)
        await interaction.response.send_message(embed=ok(text))

    @config.command(name="autorole", description="Set or clear the role assigned to new members")
    async def autorole(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, autorole_id=role.id if role else None)
        await interaction.response.send_message(embed=ok(f"Autorole set to {role.mention}." if role else "Autorole disabled."))

    @config.command(name="verification", description="Create a button verification panel for new members")
    async def verification(
        self, interaction: discord.Interaction, role: discord.Role, channel: discord.TextChannel | None = None
    ) -> None:
        if not interaction.guild or not interaction.guild.me:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I can only assign roles below my highest role.", ephemeral=True)
            return
        destination = channel or interaction.channel
        if not isinstance(destination, discord.TextChannel):
            await interaction.response.send_message("Choose a text channel for the panel.", ephemeral=True)
            return
        await self.bot.db.set_settings(interaction.guild_id, **{"verification.role_id": role.id})
        try:
            await destination.send(
                embed=info("Server verification", "Click **Verify** and enter the short confirmation code to unlock the server."),
                view=VerifyView(),
            )
        except discord.HTTPException:
            await interaction.response.send_message("I could not post the verification panel there.", ephemeral=True)
            return
        await interaction.response.send_message(embed=ok(f"Verification panel created in {destination.mention}."), ephemeral=True)

    @config.command(name="reactionrole", description="Create a persistent button message that toggles roles")
    async def reactionrole(
        self,
        interaction: discord.Interaction,
        title: str,
        role_one: discord.Role,
        role_two: discord.Role | None = None,
        role_three: discord.Role | None = None,
        role_four: discord.Role | None = None,
        role_five: discord.Role | None = None,
    ) -> None:
        roles = [role for role in (role_one, role_two, role_three, role_four, role_five) if role]
        await self._post_roles(interaction, title, roles)

    async def _post_roles(
        self,
        interaction: discord.Interaction,
        title: str,
        roles: list[discord.Role],
    ) -> None:
        if not interaction.guild or not interaction.guild.me:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if any(role >= interaction.guild.me.top_role for role in roles):
            await interaction.response.send_message("I can only assign roles below my highest role.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use this in a text channel.", ephemeral=True)
            return
        await interaction.channel.send(embed=info(title[:256], "Click a button to toggle a role."), view=role_menu(roles))
        await interaction.response.send_message(embed=ok("Role menu created."), ephemeral=True)

    @config.command(name="selfrole", description="Create a persistent self-assignable role menu")
    async def selfrole(
        self,
        interaction: discord.Interaction,
        title: str,
        role_one: discord.Role,
        role_two: discord.Role | None = None,
        role_three: discord.Role | None = None,
        role_four: discord.Role | None = None,
        role_five: discord.Role | None = None,
    ) -> None:
        roles = [role for role in (role_one, role_two, role_three, role_four, role_five) if role]
        await self._post_roles(interaction, title, roles)

    @config.command(name="counting", description="Set the channel for the counting game")
    async def setcounting(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, counting_channel_id=channel.id if channel else None)
        if channel is None:
            await self.bot.db.execute("DELETE FROM counting_state WHERE guild_id=?", (interaction.guild_id,))
        await interaction.response.send_message(embed=ok(f"Counting channel: {channel.mention}." if channel else "Counting disabled."))

    @config.command(name="automod", description="Configure banned words, invites and spam punishment")
    @app_commands.choices(
        punishment=[
            app_commands.Choice(name="Warn only", value="warn"),
            app_commands.Choice(name="Timeout", value="mute"),
            app_commands.Choice(name="Kick", value="kick"),
            app_commands.Choice(name="Ban", value="ban"),
        ]
    )
    async def automod(
        self,
        interaction: discord.Interaction,
        enabled: bool = True,
        banned_words: str = "",
        block_invites: bool = False,
        punishment: app_commands.Choice[str] | None = None,
        raid_lockdown: bool = False,
    ) -> None:
        values = [word.strip() for word in banned_words.split(",") if word.strip()][:100]
        await self.bot.db.set_settings(
            interaction.guild_id,
            **{
                "automod.enabled": enabled,
                "automod.banned_words": values,
                "automod.block_invites": block_invites,
                "automod.punishment": punishment.value if punishment else "warn",
                "automod.raid_lockdown": raid_lockdown,
            },
        )
        await interaction.response.send_message(
            embed=ok(f"Auto-moderation {'enabled' if enabled else 'disabled'}. {len(values)} banned words configured.")
        )

    @config.command(name="djrole", description="Restrict music controls to a DJ role")
    async def setdjrole(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, dj_role_id=role.id if role else None)
        await interaction.response.send_message(embed=ok(f"DJ role: {role.mention}." if role else "DJ role restriction disabled."))

    @config.command(name="suggestions", description="Set the anonymous suggestions channel")
    async def suggestions(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, suggestions_channel_id=channel.id if channel else None)
        await interaction.response.send_message(
            embed=ok(f"Suggestions channel: {channel.mention}." if channel else "Suggestions disabled.")
        )

    @config.command(name="confess", description="Set the anonymous confessions channel")
    async def confess(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, confess_channel_id=channel.id if channel else None)
        await interaction.response.send_message(
            embed=ok(f"Confessions channel: {channel.mention}." if channel else "Confessions disabled.")
        )

    @config.command(name="view", description="Show all configured Aegis settings")
    async def settings_command(self, interaction: discord.Interaction) -> None:
        row = await self.bot.db.get_guild(interaction.guild_id)
        data = {key: value for key, value in row.items() if key not in {"guild_id", "updated_at", "settings"}}
        data.update(row["settings"])
        lines = []
        for key, value in data.items():
            if isinstance(value, dict):
                value = ", ".join(f"{sub}={val}" for sub, val in value.items())
            lines.append(f"**{key.replace('_', ' ').title()}:** `{value}`")
        await interaction.response.send_message(embed=info("\n".join(lines) or "No settings saved yet."))

    @config.command(name="export", description="Export this server's Aegis configuration")
    async def exportconfig(self, interaction: discord.Interaction) -> None:
        row = await self.bot.db.get_guild(interaction.guild_id)
        row["settings"].pop("token", None)
        payload = json.dumps(row, ensure_ascii=False, indent=2).encode()
        await interaction.response.send_message(
            file=discord.File(io.BytesIO(payload), filename="aegis-config.json"), ephemeral=True
        )

    @config.command(name="import", description="Import a previously exported Aegis configuration JSON")
    async def importconfig(self, interaction: discord.Interaction, attachment: discord.Attachment) -> None:
        if not attachment.filename.lower().endswith(".json") or attachment.size > 512_000:
            await interaction.response.send_message("Attach a JSON file smaller than 512 KB.", ephemeral=True)
            return
        try:
            payload = json.loads((await attachment.read()).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            values = payload.get("settings", payload)
            if not isinstance(values, dict):
                raise ValueError
            values = {
                key: value
                for key, value in values.items()
                if isinstance(key, str) and key not in {"token", "guild_id"}
            }
            columns = {
                key: payload[key]
                for key in ("prefix", "language")
                if key in payload and isinstance(payload[key], str)
            }
            await self.bot.db.set_settings(interaction.guild_id, **columns, **values)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            await interaction.response.send_message("That is not a valid Aegis configuration export.", ephemeral=True)
            return
        await interaction.response.send_message(embed=ok("Configuration imported."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Configuration(bot))
