from __future__ import annotations

import asyncio
import io
from datetime import timezone

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import embed, ok
from bot.utils.modules import ModuleCog
from bot.utils.ui import ConfirmView


class OpenTicketView(discord.ui.View):
    def __init__(self, cog: Tickets) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Open a ticket", style=discord.ButtonStyle.success, emoji="🎫", custom_id="aegis:ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.open_ticket(interaction, "General support")


class TicketTopicSelect(discord.ui.Select):
    def __init__(self, cog: Tickets) -> None:
        self.cog = cog
        super().__init__(
            placeholder="Choose a ticket topic",
            custom_id="aegis:ticket:topic",
            options=[
                discord.SelectOption(label="General support", value="General support", emoji="💬"),
                discord.SelectOption(label="Report a member", value="Report a member", emoji="🛡️"),
                discord.SelectOption(label="Partnership", value="Partnership", emoji="🤝"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    def __init__(self, cog: Tickets) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketTopicSelect(cog))


class Tickets(ModuleCog):
    ticket = app_commands.Group(name="ticket", description="Private support ticket tools")
    module_name = "tickets"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(OpenTicketView(self))
        self.bot.add_view(TicketPanelView(self))

    async def open_ticket(self, interaction: discord.Interaction, topic: str) -> None:
        guild = interaction.guild
        if guild is None:
            return
        existing = await self.bot.db.fetchone(
            "SELECT * FROM tickets WHERE guild_id=? AND opener_id=? AND closed_at IS NULL",
            (guild.id, interaction.user.id),
        )
        if existing:
            channel = guild.get_channel(existing["channel_id"])
            await interaction.response.send_message(
                f"You already have an open ticket: {channel.mention if channel else 'ticket #' + str(existing['id'])}",
                ephemeral=True,
            )
            return
        configuration = await self.bot.db.get_guild(guild.id)
        ticket_settings = configuration["settings"].get("ticket", {})
        category = guild.get_channel(ticket_settings.get("category_id")) if ticket_settings.get("category_id") else None
        support = guild.get_role(ticket_settings.get("support_role_id")) if ticket_settings.get("support_role_id") else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if support:
            overwrites[support] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
            )
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
            )
        try:
            channel = await guild.create_text_channel(
                f"ticket-{interaction.user.name}"[:90],
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"Ticket opened by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I cannot create ticket channels. Give me **Manage Channels**.", ephemeral=True
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message("I couldn't create a ticket right now.", ephemeral=True)
            return
        ticket_id = await self.bot.db.execute(
            "INSERT INTO tickets (guild_id,channel_id,opener_id,topic,opened_at) VALUES (?,?,?,?,?)",
            (guild.id, channel.id, interaction.user.id, topic, discord.utils.utcnow().isoformat()),
        )
        await channel.send(
            content=f"{interaction.user.mention} {support.mention if support else ''}",
            embed=embed(
                f"Ticket #{ticket_id} — {topic}",
                "A member of the support team will be with you shortly. Use `/ticket close` when resolved.",
                colour=discord.Colour(0x57F287),
            ),
        )
        await interaction.response.send_message(f"Your ticket is ready: {channel.mention}", ephemeral=True)

    @ticket.command(name="setup", description="Configure the ticket category, support role and panel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
        support_role: discord.Role | None = None,
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use this in a text channel.", ephemeral=True)
            return
        await self.bot.db.set_settings(
            interaction.guild_id,
            **{
                "ticket.category_id": category.id if category else None,
                "ticket.support_role_id": support_role.id if support_role else None,
            },
        )
        try:
            message = await interaction.channel.send(
                embed=embed("Need help?", "Choose a topic below to open a private ticket."),
                view=TicketPanelView(self),
            )
        except discord.HTTPException:
            await interaction.response.send_message("I could not post the ticket panel here.", ephemeral=True)
            return
        await self.bot.db.set_settings(interaction.guild_id, **{"ticket.message_id": message.id})
        await interaction.response.send_message(embed=ok("Ticket panel created."), ephemeral=True)

    @ticket.command(name="open", description="Open a support ticket")
    @app_commands.guild_only()
    async def ticket_open(self, interaction: discord.Interaction) -> None:
        view = discord.ui.View(timeout=60)
        view.add_item(TicketTopicSelect(self))
        await interaction.response.send_message("Choose a ticket topic:", view=view, ephemeral=True)

    async def _ticket_row(self, channel_id: int) -> dict | None:
        return await self.bot.db.fetchone("SELECT * FROM tickets WHERE channel_id=? AND closed_at IS NULL", (channel_id,))

    @ticket.command(name="close", description="Close this ticket and send a transcript")
    @app_commands.guild_only()
    async def ticket_close(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command only works inside a ticket channel.", ephemeral=True)
            return
        row = await self._ticket_row(interaction.channel.id)
        if not row:
            await interaction.response.send_message("This is not an open Aegis ticket.", ephemeral=True)
            return
        confirmation = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            embed=embed("Close ticket?", "The channel will be deleted after a text transcript is sent to the moderation log."),
            view=confirmation,
            ephemeral=True,
        )
        await confirmation.wait()
        if not confirmation.confirmed:
            return
        lines = [f"Ticket #{row['id']} • {interaction.guild.name}", "=" * 70]
        async for message in interaction.channel.history(limit=1000, oldest_first=True):
            stamp = message.created_at.astimezone(timezone.utc).isoformat()
            lines.append(f"[{stamp}] {message.author} ({message.author.id}): {message.clean_content}")
        transcript = io.BytesIO("\n".join(lines).encode("utf-8"))
        await self.bot.db.execute("UPDATE tickets SET closed_at=? WHERE id=?", (discord.utils.utcnow().isoformat(), row["id"]))
        log_id = await self.bot.db.setting(interaction.guild_id, "log_channels.moderation")
        log_channel = interaction.guild.get_channel(log_id) if log_id else None
        if log_channel and hasattr(log_channel, "send"):
            try:
                await log_channel.send(
                    content=f"Ticket #{row['id']} closed by {interaction.user}.",
                    file=discord.File(transcript, filename=f"ticket-{row['id']}.txt"),
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send(embed=ok("Ticket closed. This channel will be deleted in 5 seconds."))
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket #{row['id']} closed by {interaction.user}")
        except discord.HTTPException:
            pass

    @ticket.command(name="claim", description="Claim this ticket")
    @app_commands.guild_only()
    async def ticket_claim(self, interaction: discord.Interaction) -> None:
        row = await self._ticket_row(interaction.channel_id)
        if not row:
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE tickets SET claimed_by=? WHERE id=?", (interaction.user.id, row["id"]))
        await interaction.response.send_message(embed=ok(f"{interaction.user.mention} claimed ticket **#{row['id']}**."))

    @ticket.command(name="add", description="Add a member to this ticket")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member) -> None:
        row = await self._ticket_row(interaction.channel_id)
        if not row or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(embed=ok(f"Added {member.mention} to this ticket."))

    @ticket.command(name="remove", description="Remove a member from this ticket")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_remove(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) or not await self._ticket_row(interaction.channel_id):
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(embed=ok(f"Removed {member.mention} from this ticket."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
