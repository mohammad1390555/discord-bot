"""Full button-driven ticket system for Aegis.

Features
--------
- Panel with a topic dropdown plus per-topic quick-open buttons
- Priority selection (low / medium / high / urgent) at ticket creation
- In-ticket control panel: claim, close, close with reason, transcript, lock/unlock
- Staff-only buttons with permission checks
- Rich welcome embed with context (opener, topic, priority, created timestamp)
- HTML-style plain-text transcript saved to the moderation log
- Optional user rating (1-5 stars) after closure via DM
- Ticket naming with zero-padded IDs and sane truncation
"""

from __future__ import annotations

import asyncio
import io
from datetime import timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import BRAND, SUCCESS, WARNING, DANGER, embed, ok, error, warning as warn_embed
from bot.utils.modules import ModuleCog
from bot.utils.ui import ConfirmView

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CUSTOM_ID_PREFIX = "aegis:ticket"

TOPICS = [
    {"label": "General support", "value": "general", "emoji": "\U0001F4AC",
     "description": "Questions and general help"},
    {"label": "Report a member", "value": "report", "emoji": "\U0001F6E1\uFE0F",
     "description": "Report rule-breaking behavior"},
    {"label": "Partnership", "value": "partnership", "emoji": "\U0001F91D",
     "description": "Business and partnership inquiries"},
    {"label": "Billing", "value": "billing", "emoji": "\U0001F4B3",
     "description": "Payments, refunds and invoices"},
    {"label": "Technical issue", "value": "technical", "emoji": "\U0001F527",
     "description": "Bugs and technical problems"},
]

PRIORITIES = [
    {"label": "Low", "value": "low", "emoji": "\U0001F7E2", "colour": 0x57F287,
     "description": "Can wait, no rush"},
    {"label": "Medium", "value": "medium", "emoji": "\U0001F7E1", "colour": 0xFEE75C,
     "description": "Normal priority"},
    {"label": "High", "value": "high", "emoji": "\U0001F7E0", "colour": 0xE67E22,
     "description": "Important, needs attention soon"},
    {"label": "Urgent", "value": "urgent", "emoji": "\U0001F534", "colour": 0xED4245,
     "description": "Critical, cannot use the server"},
]


def _topic_label(value: str) -> str:
    for topic in TOPICS:
        if topic["value"] == value:
            return topic["label"]
    return value.replace("_", " ").title()


def _priority_meta(value: str) -> dict:
    for priority in PRIORITIES:
        if priority["value"] == value:
            return priority
    return PRIORITIES[1]


def _is_staff(interaction: discord.Interaction, support_role_id: Optional[int]) -> bool:
    """Staff = Manage Channels permission OR the configured support role."""
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_channels:
        return True
    if support_role_id and any(role.id == support_role_id for role in member.roles):
        return True
    return False


# ---------------------------------------------------------------------------
# Persistent views
# ---------------------------------------------------------------------------

class TicketPanelView(discord.ui.View):
    """Public panel: dropdown + one-click open buttons."""

    def __init__(self, cog: "Tickets") -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(TopicSelect(cog))
        for index in (0, 1, 3):  # most common topics get direct buttons
            topic = TOPICS[index]
            cog_ref = self.cog
            topic_value = topic["value"]

            async def open_cb(interaction: discord.Interaction,
                              _cog: "Tickets" = cog_ref,
                              _value: str = topic_value) -> None:
                await _cog.start_ticket_flow(interaction, _value)

            button = discord.ui.Button(
                label=f"Open: {topic['label']}", emoji=topic["emoji"],
                style=discord.ButtonStyle.secondary,
                custom_id=f"{CUSTOM_ID_PREFIX}:open:{topic['value']}",
                row=2 if index == 0 else (3 if index == 1 else 3),
            )
            button.callback = open_cb
            self.add_item(button)


class TopicSelect(discord.ui.Select):
    def __init__(self, cog: "Tickets") -> None:
        self.cog = cog
        super().__init__(
            placeholder="Choose a ticket topic...",
            custom_id=f"{CUSTOM_ID_PREFIX}:topic",
            options=[discord.SelectOption(**{k: t[k] for k in ("label", "value", "emoji", "description")})
                     for t in TOPICS],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.start_ticket_flow(interaction, self.values[0])


class PrioritySelect(discord.ui.Select):
    def __init__(self, flow: "TicketFlowView") -> None:
        self.flow = flow
        options = [discord.SelectOption(
            label=p["label"], value=p["value"], emoji=p["emoji"], description=p["description"])
            for p in PRIORITIES]
        super().__init__(placeholder="Priority?", custom_id=f"{CUSTOM_ID_PREFIX}:priority",
                         options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.flow.priority = self.values[0]
        await interaction.response.defer()


class CancelButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Cancel", emoji="\u274C", style=discord.ButtonStyle.danger,
                         custom_id=f"{CUSTOM_ID_PREFIX}:cancel")

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(content="Ticket creation cancelled.",
                                                view=self.view)
        self.view.stop()


class TicketFlowView(discord.ui.View):
    """Ephemeral confirmation step: pick priority, confirm or cancel."""

    def __init__(self, cog: "Tickets", author_id: int, topic_value: str) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.topic_value = topic_value
        self.priority = "medium"
        self.add_item(PrioritySelect(self))
        self.add_item(CancelButton())
        confirm = discord.ui.Button(label="Create ticket", emoji="\u2705",
                                    style=discord.ButtonStyle.success,
                                    custom_id=f"{CUSTOM_ID_PREFIX}:confirm")
        confirm.callback = self._confirm
        self.add_item(confirm)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This menu is not yours.", ephemeral=True)
            return False
        return True

    async def _confirm(self, interaction: discord.Interaction) -> None:
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Creating your ticket...", view=self)
        self.stop()
        await self.cog.create_ticket(interaction, self.topic_value, self.priority)


class TicketControlView(discord.ui.View):
    """Persistent control strip posted inside every ticket channel."""

    def __init__(self, cog: "Tickets") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def _guard(self, interaction: discord.Interaction) -> Optional[dict]:
        row = await self.cog._ticket_row(interaction.channel_id)
        if not row:
            await interaction.response.send_message(
                "This is not an open Aegis ticket.", ephemeral=True)
            return None
        config = await self.cog.bot.db.get_guild(interaction.guild_id)
        support_role_id = config["settings"].get("ticket", {}).get("support_role_id")
        if not _is_staff(interaction, support_role_id):
            await interaction.response.send_message(
                "Only support staff can use this control.", ephemeral=True)
            return None
        return row

    @discord.ui.button(label="Claim", emoji="\U0001F3AB", style=discord.ButtonStyle.primary,
                       custom_id=f"{CUSTOM_ID_PREFIX}:ctl:claim")
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await self._guard(interaction)
        if not row:
            return
        if row["claimed_by"] == interaction.user.id:
            await interaction.response.send_message("You already own this ticket.", ephemeral=True)
            return
        await self.cog.bot.db.execute("UPDATE tickets SET claimed_by=? WHERE id=?",
                                      (interaction.user.id, row["id"]))
        staff = interaction.user.mention
        await interaction.response.send_message(embed=embed(
            f"\U0001F3AB Claimed by {staff}",
            f"Ticket **#{row['id']}** is now handled by {staff}. "
            "Please coordinate here.",
            colour=BRAND,
        ))
        await self._refresh_topic_embed(interaction)

    @discord.ui.button(label="Close", emoji="\U0001F512", style=discord.ButtonStyle.danger,
                       custom_id=f"{CUSTOM_ID_PREFIX}:ctl:close")
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await self._guard(interaction)
        if not row:
            return
        confirmation = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            embed=warn_embed("Close this ticket?",
                             "A text transcript will be sent to the moderation log, then the channel is deleted."),
            view=confirmation, ephemeral=True)
        await confirmation.wait()
        if confirmation.confirmed:
            await self.cog.close_ticket(interaction, row, reason="Closed via button")

    @discord.ui.button(label="Close with reason", emoji="\U0001F4DD",
                       style=discord.ButtonStyle.danger,
                       custom_id=f"{CUSTOM_ID_PREFIX}:ctl:close_reason")
    async def close_with_reason(self, interaction: discord.Interaction,
                                _: discord.ui.Button) -> None:
        row = await self._guard(interaction)
        if not row:
            return
        await interaction.response.send_modal(CloseReasonModal(self.cog, row))

    @discord.ui.button(label="Transcript", emoji="\U0001F4C4", style=discord.ButtonStyle.secondary,
                       custom_id=f"{CUSTOM_ID_PREFIX}:ctl:transcript")
    async def transcript(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await self._guard(interaction)
        if not row:
            return
        await interaction.response.defer(ephemeral=True)
        data = await self.cog.build_transcript(interaction.channel, row)
        await interaction.followup.send(
            embed=ok(f"Transcript of {len(data['messages'])} messages attached."),
            file=discord.File(data["buffer"], filename=data["filename"]),
            ephemeral=True,
        )

    @discord.ui.button(label="Lock", emoji="\U0001F512", style=discord.ButtonStyle.secondary,
                       custom_id=f"{CUSTOM_ID_PREFIX}:ctl:lock")
    async def lock(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await self._guard(interaction)
        if not row or not isinstance(interaction.channel, discord.TextChannel):
            return
        opener = interaction.guild.get_member(row["opener_id"])
        if opener:
            await interaction.channel.set_permissions(opener, send_messages=False)
        await interaction.response.send_message(embed=embed(
            "\U0001F512 Ticket locked",
            f"Only staff can write in this ticket now. Unlock with the button or `/ticket unlock`.",
            colour=WARNING))

    @discord.ui.button(label="Unlock", emoji="\U0001F513", style=discord.ButtonStyle.secondary,
                       custom_id=f"{CUSTOM_ID_PREFIX}:ctl:unlock")
    async def unlock(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        row = await self._guard(interaction)
        if not row or not isinstance(interaction.channel, discord.TextChannel):
            return
        opener = interaction.guild.get_member(row["opener_id"])
        if opener:
            await interaction.channel.set_permissions(opener, send_messages=True)
        await interaction.response.send_message(embed=ok("Ticket unlocked - the opener can write again."))

    async def _refresh_topic_embed(self, interaction: discord.Interaction) -> None:
        """Pin/refresh nothing heavy; just acknowledge ownership change visually."""
        try:
            async for message in interaction.channel.history(limit=20):
                if message.author.id != self.cog.bot.user.id or not message.embeds:
                    continue
                first = message.embeds[0]
                if first.title and first.title.startswith("\U0001F39F\uFE0F"):
                    break
        except discord.HTTPException:
            pass


class CloseReasonModal(discord.ui.Modal):
    reason = discord.ui.TextInput(label="Close reason", style=discord.TextStyle.paragraph,
                                  max_length=500, placeholder="Why is this ticket being closed?")

    def __init__(self, cog: "Tickets", row: dict) -> None:
        super().__init__(title=f"Close ticket #{row['id']}")
        self.cog = cog
        self.row = row

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.close_ticket(interaction, self.row, reason=str(self.reason.value))


class RatingView(discord.ui.View):
    """DM rating prompt after closure; 1-5 stars, one vote."""

    def __init__(self, cog: "Tickets", guild_id: int, ticket_id: int) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.ticket_id = ticket_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Any click disables all buttons so only one rating lands.
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        return True

    async def _rate(self, interaction: discord.Interaction, score: int) -> None:
        await self.cog.bot.db.execute("UPDATE tickets SET rating=? WHERE id=?",
                                      (score, self.ticket_id))
        await interaction.response.edit_message(
            content=f"Thanks! You rated ticket **#{self.ticket_id}** "
                    + "\u2b50" * score,
            view=None)
        self.stop()

    @discord.ui.button(label="1", emoji="\u2b50", custom_id=f"{CUSTOM_ID_PREFIX}:rate:1")
    async def rate1(self, interaction, _): await self._rate(interaction, 1)
    @discord.ui.button(label="2", emoji="\u2b50", custom_id=f"{CUSTOM_ID_PREFIX}:rate:2")
    async def rate2(self, interaction, _): await self._rate(interaction, 2)
    @discord.ui.button(label="3", emoji="\u2b50", custom_id=f"{CUSTOM_ID_PREFIX}:rate:3")
    async def rate3(self, interaction, _): await self._rate(interaction, 3)
    @discord.ui.button(label="4", emoji="\u2b50", custom_id=f"{CUSTOM_ID_PREFIX}:rate:4")
    async def rate4(self, interaction, _): await self._rate(interaction, 4)
    @discord.ui.button(label="5", emoji="\u2b50", custom_id=f"{CUSTOM_ID_PREFIX}:rate:5")
    async def rate5(self, interaction, _): await self._rate(interaction, 5)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Tickets(ModuleCog):
    ticket = app_commands.Group(name="ticket", description="Private support ticket tools")
    module_name = "tickets"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketControlView(self))

    # -- creation -----------------------------------------------------------

    async def start_ticket_flow(self, interaction: discord.Interaction,
                                topic_value: str) -> None:
        """Ephemeral priority picker before actually opening the channel."""
        guild = interaction.guild
        if guild is None:
            return
        existing = await self.bot.db.fetchone(
            "SELECT id, channel_id FROM tickets WHERE guild_id=? AND opener_id=? AND closed_at IS NULL",
            (guild.id, interaction.user.id),
        )
        if existing:
            channel = guild.get_channel(existing["channel_id"])
            label = channel.mention if channel else f"ticket #{existing['id']}"
            await interaction.response.send_message(
                embed=warn_embed("You already have an open ticket", label),
                ephemeral=True)
            return
        view = TicketFlowView(self, interaction.user.id, topic_value)
        await interaction.response.send_message(
            embed=embed(
                "\U0001F39F\uFE0F New ticket setup",
                f"Topic: **{_topic_label(topic_value)}**\n"
                "Pick a priority, then create the ticket."),
            view=view, ephemeral=True)

    async def create_ticket(self, interaction: discord.Interaction,
                            topic_value: str, priority: str) -> None:
        guild = interaction.guild
        configuration = await self.bot.db.get_guild(guild.id)
        settings = configuration["settings"].get("ticket", {})
        category = guild.get_channel(settings.get("category_id")) \
            if settings.get("category_id") else None
        support = guild.get_role(settings.get("support_role_id")) \
            if settings.get("support_role_id") else None
        meta = _priority_meta(priority)
        count = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM tickets WHERE guild_id=?", (guild.id,))
        next_number = (count["n"] if count else 0) + 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True),
        }
        if support:
            overwrites[support] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_messages=True)
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_channels=True)

        try:
            channel = await guild.create_text_channel(
                f"\U0001F39F-{next_number:04d}-{interaction.user.name}"[:90],
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"Ticket opened by {interaction.user} ({_topic_label(topic_value)})",
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="I cannot create ticket channels - give me **Manage Channels**.",
                view=None)
            return
        except discord.HTTPException:
            await interaction.edit_original_response(
                content="I couldn't create a ticket right now, please try again later.",
                view=None)
            return

        opened_iso = discord.utils.utcnow().isoformat()
        ticket_id = await self.bot.db.execute(
            "INSERT INTO tickets (guild_id,channel_id,opener_id,topic,priority,opened_at)"
            " VALUES (?,?,?,?,?,?)",
            (guild.id, channel.id, interaction.user.id, topic_value, priority, opened_iso),
        )

        welcome = embed(
            f"\U0001F39F\uFE0F Ticket #{ticket_id} \u2014 {_topic_label(topic_value)}",
            f"{interaction.user.mention}, welcome!\n"
            "Describe your issue in as much detail as you can - "
            "the support team has been notified.\n\n"
            "**Controls below are for support staff only.**",
            colour=meta["colour"],
        )
        welcome.add_field(name="Opener", value=f"{interaction.user} (`{interaction.user.id}`)")
        welcome.add_field(name="Priority", value=f"{meta['emoji']} {meta['label']}")
        welcome.add_field(name="Status", value="Open \U0001F7E2")
        welcome.set_thumbnail(url=interaction.user.display_avatar.url)
        await channel.send(
            content=f"{interaction.user.mention} {support.mention if support else ''}".strip(),
            embed=welcome,
            view=TicketControlView(self),
        )
        try:
            await interaction.edit_original_response(
                content=f"[+] Your ticket is ready: {channel.mention}", view=None)
        except discord.HTTPException:
            pass

    # -- closing -------------------------------------------------------------

    async def _ticket_row(self, channel_id: int) -> dict | None:
        return await self.bot.db.fetchone(
            "SELECT * FROM tickets WHERE channel_id=? AND closed_at IS NULL", (channel_id,))

    async def build_transcript(self, channel, row: dict) -> dict:
        lines = [f"AEGIS TICKET TRANSCRIPT #{row['id']}",
                 f"Guild: {channel.guild.name} ({channel.guild.id})",
                 f"Channel: #{channel.name}",
                 "=" * 60]
        count = 0
        async for message in channel.history(limit=1000, oldest_first=True):
            stamp = message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            attachments = "".join(f"\n    [attachment] {a.url}" for a in message.attachments)
            lines.append(f"[{stamp}] {message.author} ({message.author.id}):")
            if message.clean_content:
                lines.append(message.clean_content)
            if attachments:
                lines.append(attachments.strip("\n    "))
            count += 1
        lines.append("=" * 60)
        lines.append(f"Total messages: {count}")
        buffer = io.BytesIO("\n".join(lines).encode("utf-8"))
        return {"buffer": buffer, "messages": count,
                "filename": f"ticket-{row['id']}-transcript.txt"}

    async def close_ticket(self, interaction: discord.Interaction, row: dict,
                           *, reason: str) -> None:
        await interaction.response.defer(ephemeral=False)
        channel = interaction.channel
        data = await self.build_transcript(channel, row)

        closed_iso = discord.utils.utcnow().isoformat()
        await self.bot.db.execute(
            "UPDATE tickets SET closed_at=?, closed_by=?, close_reason=? WHERE id=?",
            (closed_iso, interaction.user.id, reason[:500], row["id"]))

        log_id = await self.bot.db.setting(interaction.guild_id, "log_channels.moderation")
        log_channel = interaction.guild.get_channel(log_id) if log_id else None
        if log_channel and hasattr(log_channel, "send"):
            summary = embed(
                f"\U0001F512 Ticket #{row['id']} closed",
                f"**Reason:** {reason}\n"
                f"**Closed by:** {interaction.user} (`{interaction.user.id}`)\n"
                f"**Messages:** {data['messages']}\n"
                f"**Topic:** {_topic_label(row['topic'])}",
                colour=DANGER)
            try:
                await log_channel.send(embed=summary,
                                       file=discord.File(data["buffer"], filename=data["filename"]))
            except discord.HTTPException:
                pass

        opener = interaction.guild.get_member(row["opener_id"])
        await interaction.followup.send(embed=ok(
            f"Ticket closed by {interaction.user.mention}. Channel deletes in 5 seconds."))

        # DM rating request (best-effort).
        if opener:
            try:
                await opener.send(
                    embed=embed(
                        "\u2b50 How was your support experience?",
                        f"Ticket **#{row['id']}** in **{interaction.guild.name}** was closed.\n"
                        "Rate the support quality:",
                        colour=BRAND),
                    view=RatingView(self, interaction.guild_id, row["id"]))
            except discord.HTTPException:
                pass  # DMs closed; ignore.

        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket #{row['id']} closed by {interaction.user}")
        except discord.HTTPException:
            pass

    # -- admin setup ----------------------------------------------------------

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
        panel_text = (
            "**Need help?**\n\n"
            "Pick a topic from the menu below, or use a quick-open button.\n"
            "A private channel will be created for you and the support team."
        )
        panel = discord.Embed(title="\U0001F39F\uFE0F Support Tickets",
                              description=panel_text, colour=BRAND)
        try:
            message = await interaction.channel.send(embed=panel, view=TicketPanelView(self))
        except discord.HTTPException:
            await interaction.response.send_message(
                "I could not post the ticket panel here.", ephemeral=True)
            return
        await self.bot.db.set_settings(interaction.guild_id,
                                       **{"ticket.message_id": message.id})
        await interaction.response.send_message(embed=ok("Ticket panel created."), ephemeral=True)

    @ticket.command(name="open", description="Open a support ticket (interactive)")
    @app_commands.guild_only()
    async def ticket_open(self, interaction: discord.Interaction) -> None:
        fresh = discord.ui.View(timeout=90)
        fresh.add_item(TicketTopicStandalone(self))
        fresh.add_item(TicketFlowProxy(self, interaction.user.id))
        await interaction.response.send_message(
            embed=embed("\U0001F39F\uFE0F Open a ticket", "Choose a topic to continue."),
            view=fresh, ephemeral=True)

    # -- legacy slash commands kept for compatibility --------------------------

    @ticket.command(name="close", description="Close this ticket and send a transcript")
    @app_commands.guild_only()
    async def ticket_close(self, interaction: discord.Interaction) -> None:
        row = await self._ticket_row(interaction.channel_id)
        if not row or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This is not an open Aegis ticket.", ephemeral=True)
            return
        await interaction.response.send_modal(CloseReasonModal(self, row))

    @ticket.command(name="claim", description="Claim this ticket")
    @app_commands.guild_only()
    async def ticket_claim(self, interaction: discord.Interaction) -> None:
        row = await self._ticket_row(interaction.channel_id)
        if not row:
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE tickets SET claimed_by=? WHERE id=?",
                                  (interaction.user.id, row["id"]))
        await interaction.response.send_message(
            embed=ok(f"{interaction.user.mention} claimed ticket **#{row['id']}**."))

    @ticket.command(name="add", description="Add a member to this ticket")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_add(self, interaction: discord.Interaction,
                         member: discord.Member) -> None:
        row = await self._ticket_row(interaction.channel_id)
        if not row or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(
            member, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(
            embed=ok(f"Added {member.mention} to this ticket."))

    @ticket.command(name="remove", description="Remove a member from this ticket")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_remove(self, interaction: discord.Interaction,
                            member: discord.Member) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) \
                or not await self._ticket_row(interaction.channel_id):
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(
            embed=ok(f"Removed {member.mention} from this ticket."))

    @ticket.command(name="stats", description="Show ticket statistics for this server")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_stats(self, interaction: discord.Interaction) -> None:
        total = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM tickets WHERE guild_id=?", (interaction.guild_id,))
        open_now = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND closed_at IS NULL",
            (interaction.guild_id,))
        avg_rating = await self.bot.db.fetchone(
            "SELECT AVG(rating) AS avg FROM tickets WHERE guild_id=? AND rating IS NOT NULL",
            (interaction.guild_id,))
        top_staff = await self.bot.db.fetchall(
            "SELECT claimed_by, COUNT(*) AS n FROM tickets WHERE guild_id=? AND claimed_by"
            " IS NOT NULL GROUP BY claimed_by ORDER BY n DESC LIMIT 3", (interaction.guild_id,))
        stats_embed = embed(
            "\U0001F4CA Ticket statistics",
            f"**Total:** {total['n']}\n"
            f"**Open now:** {open_now['n']}\n"
            f"**Average rating:** {round(avg_rating['avg'], 2) if avg_rating['avg'] else 'no ratings yet'}",
            colour=BRAND)
        if top_staff:
            stats_embed.add_field(
                name="Most active staff",
                value="\n".join(f"<@{t['claimed_by']}> - {t['n']} tickets" for t in top_staff),
                inline=False)
        await interaction.response.send_message(embed=stats_embed)


class TicketTopicStandalone(discord.ui.Select):
    def __init__(self, cog: Tickets) -> None:
        self.cog = cog
        super().__init__(placeholder="Choose a ticket topic...",
                         options=[discord.SelectOption(
                             **{k: t[k] for k in ("label", "value", "emoji", "description")})
                             for t in TOPICS])

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.start_ticket_flow(interaction, self.values[0])


class TicketFlowProxy(discord.ui.Button):
    def __init__(self, cog: Tickets, author_id: int) -> None:
        super().__init__(label="Continue", emoji="\u27A1\uFE0F",
                         style=discord.ButtonStyle.success)
        self.cog = cog
        self.author_id = author_id
        self.chosen_topic: Optional[str] = None

    async def callback(self, interaction: discord.Interaction) -> None:
        # Find the sibling select in the same view.
        view_children = self.view.children if self.view else []
        select = next((child for child in view_children
                       if isinstance(child, TicketTopicStandalone)), None)
        if not select or not select.values:
            await interaction.response.send_message("Pick a topic first.", ephemeral=True)
            return
        await self.cog.start_ticket_flow(interaction, select.values[0])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
