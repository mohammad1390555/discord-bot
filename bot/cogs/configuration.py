from __future__ import annotations

import io
import json
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import info, ok
from bot.utils.i18n import text as localized


class VerifyModal(discord.ui.Modal, title="Verification"):
    code = discord.ui.TextInput(label="Enter VERIFY to continue", max_length=6)

    def __init__(self, role: discord.Role) -> None:
        super().__init__()
        self.role = role

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if str(self.code).strip().casefold() != "verify":
            await interaction.response.send_message("Verification failed. Try again.", ephemeral=True)
            return
        if isinstance(interaction.user, discord.Member):
            await interaction.user.add_roles(self.role, reason="Verification completed")
        await interaction.response.send_message("You are verified. Welcome!", ephemeral=True)


class VerifyView(discord.ui.View):
    def __init__(self, role: discord.Role) -> None:
        super().__init__(timeout=None)
        self.role = role

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="✅", custom_id="aegis:verification:open")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(VerifyModal(self.role))


class SetupModal(discord.ui.Modal, title="Server setup"):
    prefix = discord.ui.TextInput(label="Command prefix", placeholder="!", max_length=5, required=False)
    language = discord.ui.TextInput(label="Language (en or fa)", placeholder="en", max_length=2, required=False)

    def __init__(self, cog: "Configuration") -> None:
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


class SelfRoleSelect(discord.ui.Select):
    def __init__(self, roles: list[discord.Role]) -> None:
        self.roles_by_id = {str(role.id): role for role in roles}
        super().__init__(placeholder="Choose your roles", min_values=0, max_values=len(roles), options=[
            discord.SelectOption(label=role.name[:100], value=str(role.id), description="Toggle this role") for role in roles
        ])

    async def callback(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        selected = {int(value) for value in self.values}
        changed = []
        for role_id, role in self.roles_by_id.items():
            if int(role_id) in selected and role not in member.roles:
                await member.add_roles(role, reason="Self-role menu")
                changed.append(f"added {role.name}")
            elif int(role_id) not in selected and role in member.roles:
                await member.remove_roles(role, reason="Self-role menu")
                changed.append(f"removed {role.name}")
        await interaction.response.send_message("Roles updated: " + (", ".join(changed) or "no changes"), ephemeral=True)


class SelfRoleView(discord.ui.View):
    def __init__(self, roles: list[discord.Role]) -> None:
        super().__init__(timeout=900)
        self.add_item(SelfRoleSelect(roles))


class ReactionRoleView(discord.ui.View):
    def __init__(self, roles: list[discord.Role]) -> None:
        super().__init__(timeout=900)
        for role in roles:
            button = discord.ui.Button(label=role.name[:80], style=discord.ButtonStyle.secondary, custom_id=f"aegis:role:{role.id}")
            button.callback = self._toggle(role)  # type: ignore[method-assign]
            self.add_item(button)

    def _toggle(self, role: discord.Role):
        async def callback(interaction: discord.Interaction) -> None:
            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("This is a server-only role menu.", ephemeral=True)
                return
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Reaction-role menu")
                message = f"Removed {role.mention}."
            else:
                await interaction.user.add_roles(role, reason="Reaction-role menu")
                message = f"Added {role.mention}."
            await interaction.response.send_message(message, ephemeral=True)
        return callback


class SetupView(discord.ui.View):
    def __init__(self, cog: "Configuration", author_id: int) -> None:
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
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._views_restored = False

    async def _restore_verification_views(self) -> None:
        if self._views_restored or not self.bot.is_ready():
            return
        # setup_hook runs before the guild cache is populated; on_ready calls this
        # again so panels from previous processes remain interactive.
        for row in await self.bot.db.fetchall("SELECT guild_id, settings_json FROM guild_settings"):
            try:
                role_id = json.loads(row["settings_json"]).get("verification", {}).get("role_id")
                guild = self.bot.get_guild(row["guild_id"])
                role = guild.get_role(role_id) if guild and role_id else None
                if role:
                    self.bot.add_view(VerifyView(role))
            except (TypeError, json.JSONDecodeError):
                continue
        self._views_restored = True

    async def cog_load(self) -> None:
        await self._restore_verification_views()

    async def on_ready(self) -> None:
        await self._restore_verification_views()

    @app_commands.command(name="setup", description="Open the interactive server setup wizard")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.db.get_guild(interaction.guild_id)
        description = (
            "Configure Aegis for this server. The wizard stores settings in the database and survives restarts.\n\n"
            f"**Prefix:** `{settings['prefix']}`\n**Language:** `{settings['language']}`\n"
            "Use the buttons below to begin."
        )
        await interaction.response.send_message(embed=info(description), view=SetupView(self, interaction.user.id), ephemeral=True)

    @app_commands.command(name="setprefix", description="Set this server's optional legacy command prefix")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setprefix(self, interaction: discord.Interaction, prefix: str) -> None:
        if not 1 <= len(prefix) <= 5 or any(ch.isspace() for ch in prefix):
            await interaction.response.send_message("Prefix must be 1–5 non-space characters.", ephemeral=True)
            return
        await self.bot.db.set_settings(interaction.guild_id, prefix=prefix)
        await interaction.response.send_message(embed=ok(f"The prefix is now `{prefix}`."))

    @app_commands.command(name="setlanguage", description="Set the server language (English or Persian)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.choices(language=[
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="Persian / فارسی", value="fa"),
    ])
    async def setlanguage(self, interaction: discord.Interaction, language: app_commands.Choice[str]) -> None:
        await self.bot.db.set_settings(interaction.guild_id, language=language.value)
        message = "زبان روی فارسی تنظیم شد." if language.value == "fa" else "Language set to **English**."
        await interaction.response.send_message(embed=ok(message))

    @app_commands.command(name="setlogchannel", description="Route a log category to a channel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setlogchannel(self, interaction: discord.Interaction, category: Literal["general", "moderation", "messages", "members", "voice"], channel: discord.TextChannel) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{f"log_channels.{category}": channel.id})
        await interaction.response.send_message(embed=ok(f"{category.title()} logs will be sent to {channel.mention}."))

    @app_commands.command(name="setwelcome", description="Configure welcome channel and message")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setwelcome(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str = "Welcome {user} to {server}!") -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{"welcome.channel_id": channel.id, "welcome.message": message[:1000]})
        await interaction.response.send_message(embed=ok(f"Welcome messages will be sent in {channel.mention}."))

    @app_commands.command(name="setleave", description="Configure leave channel and message")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setleave(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str = "{user} has left {server}.") -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{"leave.channel_id": channel.id, "leave.message": message[:1000]})
        await interaction.response.send_message(embed=ok(f"Leave messages will be sent in {channel.mention}."))

    @app_commands.command(name="setwelcomechannel", description="Set or clear the welcome channel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setwelcomechannel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{"welcome.channel_id": channel.id if channel else None})
        await interaction.response.send_message(embed=ok(f"Welcome channel: {channel.mention}." if channel else "Welcome messages disabled."))

    @app_commands.command(name="setwelcomemessage", description="Set the welcome message template")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setwelcomemessage(self, interaction: discord.Interaction, message: str) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{"welcome.message": message[:1000]})
        await interaction.response.send_message(embed=ok("Welcome message updated. Variables: `{user}`, `{server}`, `{membercount}`."))

    @app_commands.command(name="setleavechannel", description="Set or clear the leave channel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setleavechannel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{"leave.channel_id": channel.id if channel else None})
        await interaction.response.send_message(embed=ok(f"Leave channel: {channel.mention}." if channel else "Leave messages disabled."))

    @app_commands.command(name="setleavemessage", description="Set the leave message template")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setleavemessage(self, interaction: discord.Interaction, message: str) -> None:
        await self.bot.db.set_settings(interaction.guild_id, **{"leave.message": message[:1000]})
        await interaction.response.send_message(embed=ok("Leave message updated. Variables: `{user}`, `{server}`, `{membercount}`."))

    @app_commands.command(name="autorole", description="Set or clear the role assigned to new members")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def autorole(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, autorole_id=role.id if role else None)
        await interaction.response.send_message(embed=ok(f"Autorole set to {role.mention}." if role else "Autorole disabled."))

    @app_commands.command(name="verification", description="Create a button verification panel for new members")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def verification(self, interaction: discord.Interaction, role: discord.Role, channel: discord.TextChannel | None = None) -> None:
        if role >= interaction.guild.me.top_role:  # type: ignore[union-attr]
            await interaction.response.send_message("I can only assign roles below my highest role.", ephemeral=True)
            return
        destination = channel or interaction.channel
        await self.bot.db.set_settings(interaction.guild_id, **{"verification.role_id": role.id})
        await destination.send(embed=info("Server verification", "Click **Verify** and enter the short confirmation code to unlock the server."), view=VerifyView(role))
        await interaction.response.send_message(embed=ok(f"Verification panel created in {destination.mention}."), ephemeral=True)

    @app_commands.command(name="reactionrole", description="Create a button message that toggles one or more roles")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def reactionrole(self, interaction: discord.Interaction, title: str, role_one: discord.Role, role_two: discord.Role | None = None, role_three: discord.Role | None = None, role_four: discord.Role | None = None, role_five: discord.Role | None = None) -> None:
        roles = [role for role in (role_one, role_two, role_three, role_four, role_five) if role]
        if any(role >= interaction.guild.me.top_role for role in roles):  # type: ignore[union-attr]
            await interaction.response.send_message("I can only assign roles below my highest role.", ephemeral=True)
            return
        await interaction.channel.send(embed=info(title[:256], "Click a button to toggle a role."), view=ReactionRoleView(roles))
        await interaction.response.send_message(embed=ok("Role menu created."), ephemeral=True)

    @app_commands.command(name="selfrole", description="Create a select menu for self-assignable roles")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def selfrole(self, interaction: discord.Interaction, title: str, role_one: discord.Role, role_two: discord.Role | None = None, role_three: discord.Role | None = None, role_four: discord.Role | None = None, role_five: discord.Role | None = None) -> None:
        roles = [role for role in (role_one, role_two, role_three, role_four, role_five) if role]
        if any(role >= interaction.guild.me.top_role for role in roles):  # type: ignore[union-attr]
            await interaction.response.send_message("I can only assign roles below my highest role.", ephemeral=True)
            return
        await interaction.channel.send(embed=info(title[:256], "Choose the roles you want to have."), view=SelfRoleView(roles))
        await interaction.response.send_message(embed=ok("Self-role menu created."), ephemeral=True)

    @app_commands.command(name="setcounting", description="Set the channel for the counting game")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setcounting(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, counting_channel_id=channel.id if channel else None)
        await interaction.response.send_message(embed=ok(f"Counting channel: {channel.mention}." if channel else "Counting disabled."))

    @app_commands.command(name="automod", description="Configure banned words, invites and spam punishment")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.choices(punishment=[
        app_commands.Choice(name="Warn only", value="warn"), app_commands.Choice(name="Timeout", value="mute"),
        app_commands.Choice(name="Kick", value="kick"), app_commands.Choice(name="Ban", value="ban"),
    ])
    async def automod(self, interaction: discord.Interaction, enabled: bool = True, banned_words: str = "", block_invites: bool = False, punishment: app_commands.Choice[str] | None = None, raid_lockdown: bool = False) -> None:
        values = [word.strip() for word in banned_words.split(",") if word.strip()][:100]
        await self.bot.db.set_settings(interaction.guild_id, **{"automod.enabled": enabled, "automod.banned_words": values, "automod.block_invites": block_invites, "automod.punishment": punishment.value if punishment else "warn", "automod.raid_lockdown": raid_lockdown})
        await interaction.response.send_message(embed=ok(f"Auto-moderation {'enabled' if enabled else 'disabled'}. {len(values)} banned words configured."))

    @app_commands.command(name="setdjrole", description="Restrict music controls to a DJ role")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setdjrole(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        await self.bot.db.set_settings(interaction.guild_id, dj_role_id=role.id if role else None)
        await interaction.response.send_message(embed=ok(f"DJ role: {role.mention}." if role else "DJ role restriction disabled."))

    @app_commands.command(name="settings", description="Show all configured Aegis settings")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
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

    @app_commands.command(name="exportconfig", description="Export this server's Aegis configuration")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def exportconfig(self, interaction: discord.Interaction) -> None:
        row = await self.bot.db.get_guild(interaction.guild_id)
        row["settings"].pop("token", None)
        payload = json.dumps(row, ensure_ascii=False, indent=2).encode()
        await interaction.response.send_message(file=discord.File(io.BytesIO(payload), filename="aegis-config.json"), ephemeral=True)

    @app_commands.command(name="importconfig", description="Import a previously exported Aegis configuration JSON")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
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
            values = {key: value for key, value in values.items() if isinstance(key, str) and key not in {"token", "guild_id"}}
            columns = {key: payload[key] for key in ("prefix", "language") if key in payload and isinstance(payload[key], str)}
            # Imported settings are namespaced, never raw SQL column names.
            await self.bot.db.set_settings(interaction.guild_id, **columns, **values)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            await interaction.response.send_message("That is not a valid Aegis configuration export.", ephemeral=True)
            return
        await interaction.response.send_message(embed=ok("Configuration imported."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Configuration(bot))
