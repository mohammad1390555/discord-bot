from __future__ import annotations

import discord

from .embeds import embed


class ConfirmView(discord.ui.View):
    """Reusable confirmation view; only the initiating member can click it."""

    def __init__(self, author_id: int, *, timeout: float = 30) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed = False
        self.message: discord.InteractionMessage | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command author can use this confirmation.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✓")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="×")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(embed=embed("Cancelled", "No changes were made."), view=self)
        self.stop()


class Paginator(discord.ui.View):
    def __init__(self, author_id: int, pages: list[discord.Embed], *, timeout: float = 120) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.pages = pages or [embed("Empty", "Nothing to show.")]
        self.index = 0
        self.message: discord.InteractionMessage | discord.Message | None = None
        self._refresh()

    def _refresh(self) -> None:
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.pages) - 1
        self.counter.label = f"{self.index + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This paginator belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="‹", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def counter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="›", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def send(self, interaction: discord.Interaction, *, ephemeral: bool = False) -> None:
        await interaction.response.send_message(embed=self.pages[0], view=self, ephemeral=ephemeral)
        self.message = await interaction.original_response()

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True  # type: ignore[union-attr]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class CategorySelect(discord.ui.Select):
    def __init__(self, pages: dict[str, discord.Embed]) -> None:
        self.pages = pages
        super().__init__(
            placeholder="Choose a command category",
            options=[discord.SelectOption(label=key.replace("_", " ").title(), value=key) for key in pages],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=self.pages[self.values[0]])


class HelpView(discord.ui.View):
    def __init__(self, pages: dict[str, discord.Embed]) -> None:
        super().__init__(timeout=180)
        self.add_item(CategorySelect(pages))
