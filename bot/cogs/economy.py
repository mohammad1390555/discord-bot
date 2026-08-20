from __future__ import annotations

import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import parse_iso
from bot.utils.embeds import embed, ok


async def item_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    rows = await interaction.client.db.fetchall("SELECT item_id, name FROM shop_items WHERE guild_id=? AND item_id LIKE ? LIMIT 25", (interaction.guild_id, current.lower() + "%"))  # type: ignore[attr-defined]
    return [app_commands.Choice(name=f"{row['item_id']} — {row['name']}"[:100], value=row["item_id"]) for row in rows]


class Economy(commands.Cog):
    """Per-server currency, rewards, shop and safe mini-games."""
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _balance(self, guild_id: int, user_id: int) -> int:
        return int((await self.bot.db.upsert_user(guild_id, user_id))["currency"])

    async def _change(self, guild_id: int, user_id: int, amount: int) -> int:
        await self.bot.db.upsert_user(guild_id, user_id)
        await self.bot.db.execute("UPDATE users SET currency=MAX(0,currency+?) WHERE guild_id=? AND user_id=?", (amount, guild_id, user_id))
        return await self._balance(guild_id, user_id)

    async def _cooldown_ready(self, guild_id: int, user_id: int, field: str, seconds: int) -> tuple[bool, int]:
        row = await self.bot.db.upsert_user(guild_id, user_id)
        value = row.get(field)
        if value:
            remaining = seconds - int((discord.utils.utcnow() - parse_iso(value)).total_seconds())
            if remaining > 0:
                return False, remaining
        return True, 0

    @app_commands.command(name="balance", description="Show a member's server currency")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        member = member or interaction.user
        amount = await self._balance(interaction.guild_id, member.id)
        await interaction.response.send_message(embed=embed(f"Wallet — {member.display_name}", f"**{amount:,} coins** 💰"))

    @app_commands.command(name="daily", description="Claim your daily currency reward")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        ready, remaining = await self._cooldown_ready(interaction.guild_id, interaction.user.id, "daily_at", 86400)
        if not ready:
            await interaction.response.send_message(f"Your daily reward is ready <t:{int(discord.utils.utcnow().timestamp()) + remaining}:R>.", ephemeral=True)
            return
        reward = random.randint(100, 250)
        await self.bot.db.update_user(interaction.guild_id, interaction.user.id, daily_at=discord.utils.utcnow().isoformat())
        total = await self._change(interaction.guild_id, interaction.user.id, reward)
        await interaction.response.send_message(embed=ok(f"You claimed **{reward:,} coins**. Balance: **{total:,}**."))

    @app_commands.command(name="weekly", description="Claim your weekly currency reward")
    @app_commands.guild_only()
    async def weekly(self, interaction: discord.Interaction) -> None:
        ready, remaining = await self._cooldown_ready(interaction.guild_id, interaction.user.id, "weekly_at", 604800)
        if not ready:
            await interaction.response.send_message(f"Your weekly reward is ready <t:{int(discord.utils.utcnow().timestamp()) + remaining}:R>.", ephemeral=True)
            return
        reward = random.randint(700, 1500)
        await self.bot.db.update_user(interaction.guild_id, interaction.user.id, weekly_at=discord.utils.utcnow().isoformat())
        total = await self._change(interaction.guild_id, interaction.user.id, reward)
        await interaction.response.send_message(embed=ok(f"You claimed **{reward:,} coins**. Balance: **{total:,}**."))

    @app_commands.command(name="work", description="Work for a random currency reward")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 30.0)
    async def work(self, interaction: discord.Interaction) -> None:
        reward = random.randint(25, 100)
        total = await self._change(interaction.guild_id, interaction.user.id, reward)
        jobs = ["fixed a satellite", "baked a cake", "walked a dragon", "reviewed code"]
        await interaction.response.send_message(embed=ok(f"You {random.choice(jobs)} and earned **{reward} coins**. Balance: **{total:,}**."))

    @app_commands.command(name="pay", description="Transfer currency to another member")
    @app_commands.guild_only()
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]) -> None:
        if member.id == interaction.user.id or member.bot:
            await interaction.response.send_message("Choose another human member.", ephemeral=True)
            return
        balance = await self._balance(interaction.guild_id, interaction.user.id)
        if balance < amount:
            await interaction.response.send_message("You do not have enough coins.", ephemeral=True)
            return
        await self._change(interaction.guild_id, interaction.user.id, -amount)
        await self._change(interaction.guild_id, member.id, amount)
        await interaction.response.send_message(embed=ok(f"Transferred **{amount:,} coins** to {member.mention}."))

    @app_commands.command(name="shop", description="Browse this server's currency shop")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall("SELECT * FROM shop_items WHERE guild_id=? ORDER BY price", (interaction.guild_id,))
        text = "\n".join(f"`{row['item_id']}` — **{row['name']}** • {row['price']:,} coins\n{row['description']}" for row in rows)
        await interaction.response.send_message(embed=embed("Server shop", text or "The shop is empty. Staff can add items with `/shopadd`."))

    @app_commands.command(name="shopadd", description="Add or update a shop item")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def shopadd(self, interaction: discord.Interaction, item_id: str, name: str, price: app_commands.Range[int, 1, 1_000_000], role: Optional[discord.Role] = None, description: str = "") -> None:
        await self.bot.db.execute("INSERT INTO shop_items (guild_id,item_id,name,price,role_id,description) VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id,item_id) DO UPDATE SET name=excluded.name,price=excluded.price,role_id=excluded.role_id,description=excluded.description", (interaction.guild_id, item_id.lower()[:30], name[:100], price, role.id if role else None, description[:250]))
        await interaction.response.send_message(embed=ok(f"Shop item `{item_id.lower()[:30]}` saved."))

    @app_commands.command(name="buy", description="Buy an item from this server's shop")
    @app_commands.autocomplete(item_id=item_autocomplete)
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, item_id: str) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM shop_items WHERE guild_id=? AND item_id=?", (interaction.guild_id, item_id.lower()))
        if not row:
            await interaction.response.send_message("Shop item not found.", ephemeral=True)
            return
        balance = await self._balance(interaction.guild_id, interaction.user.id)
        if balance < row["price"]:
            await interaction.response.send_message("You do not have enough coins.", ephemeral=True)
            return
        await self._change(interaction.guild_id, interaction.user.id, -row["price"])
        await self.bot.db.execute("INSERT INTO inventory (guild_id,user_id,item_id) VALUES (?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+1", (interaction.guild_id, interaction.user.id, row["item_id"]))
        if row["role_id"] and isinstance(interaction.user, discord.Member):
            role = interaction.guild.get_role(row["role_id"])
            if role:
                await interaction.user.add_roles(role, reason=f"Bought {row['item_id']}")
        await interaction.response.send_message(embed=ok(f"You bought **{row['name']}** for **{row['price']:,} coins**."))

    @app_commands.command(name="inventory", description="View your purchased shop items")
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        member = member or interaction.user
        rows = await self.bot.db.fetchall("SELECT inventory.*, shop_items.name FROM inventory LEFT JOIN shop_items USING (guild_id,item_id) WHERE inventory.guild_id=? AND user_id=?", (interaction.guild_id, member.id))
        await interaction.response.send_message(embed=embed(f"Inventory — {member.display_name}", "\n".join(f"**{row['name'] or row['item_id']}** × {row['quantity']}" for row in rows) or "Empty."))

    async def _gamble(self, interaction: discord.Interaction, bet: int, result: int, label: str) -> None:
        balance = await self._balance(interaction.guild_id, interaction.user.id)
        if balance < bet:
            await interaction.response.send_message("You do not have enough coins.", ephemeral=True)
            return
        await self._change(interaction.guild_id, interaction.user.id, result - bet)
        net = result - bet
        await interaction.response.send_message(embed=ok(f"{label}\nNet: **{net:+,} coins** • Balance: **{await self._balance(interaction.guild_id, interaction.user.id):,}**"))

    @app_commands.command(name="coinflip", description="Bet on a coin flip")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0)
    @app_commands.choices(choice=[app_commands.Choice(name="Heads", value="heads"), app_commands.Choice(name="Tails", value="tails")])
    async def coinflip(self, interaction: discord.Interaction, bet: app_commands.Range[int, 1, 100_000], choice: app_commands.Choice[str]) -> None:
        won = random.choice(("heads", "tails")) == choice.value
        await self._gamble(interaction, bet, bet * 2 if won else 0, f"The coin landed **{choice.value if won else ('tails' if choice.value == 'heads' else 'heads')}** — {'you win!' if won else 'you lose.'}")

    @app_commands.command(name="slots", description="Play slots for currency")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 15.0)
    async def slots(self, interaction: discord.Interaction, bet: app_commands.Range[int, 1, 100_000]) -> None:
        symbols = [random.choice(["🍒", "🍋", "🔔", "⭐", "💎"]) for _ in range(3)]
        payout = bet * (10 if len(set(symbols)) == 1 else 3 if len(set(symbols)) == 2 else 0)
        await self._gamble(interaction, bet, payout, " | ".join(symbols) + (" — JACKPOT!" if payout == bet * 10 else ""))

    @app_commands.command(name="blackjack", description="Play a quick blackjack hand")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 20.0)
    async def blackjack(self, interaction: discord.Interaction, bet: app_commands.Range[int, 1, 100_000]) -> None:
        player = random.randint(15, 21)
        dealer = random.randint(15, 21)
        result = bet if player > dealer or dealer > 21 else bet * 2 if player == 21 else 0
        label = f"You: **{player}** • Dealer: **{dealer}** — " + ("win!" if result else "dealer wins.")
        await self._gamble(interaction, bet, result, label)

    @app_commands.command(name="addmoney", description="Give currency to a member")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def addmoney(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]) -> None:
        total = await self._change(interaction.guild_id, member.id, amount)
        await interaction.response.send_message(embed=ok(f"Added **{amount:,} coins** to {member.mention}. Balance: **{total:,}**."))

    @app_commands.command(name="removemoney", description="Remove currency from a member")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def removemoney(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]) -> None:
        total = await self._change(interaction.guild_id, member.id, -amount)
        await interaction.response.send_message(embed=ok(f"Removed **{amount:,} coins** from {member.mention}. Balance: **{total:,}**."))

    @app_commands.command(name="resetbalance", description="Reset a member's currency")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def resetbalance(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self.bot.db.update_user(interaction.guild_id, member.id, currency=0)
        await interaction.response.send_message(embed=ok(f"Reset {member.mention}'s balance."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))
