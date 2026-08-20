from __future__ import annotations

import io
import random
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import embed, error, ok, shorten


class RPSView(discord.ui.View):
    def __init__(self, cog: "Fun", author_id: int) -> None:
        super().__init__(timeout=60)
        self.cog, self.author_id = cog, author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This game belongs to another player.", ephemeral=True)
            return False
        return True

    async def choose(self, interaction: discord.Interaction, choice: str) -> None:
        bot_choice = random.choice(["rock", "paper", "scissors"])
        result = "draw" if choice == bot_choice else "win" if (choice, bot_choice) in {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")} else "lose"
        await interaction.response.edit_message(embed=embed("Rock Paper Scissors", f"You chose **{choice}**. I chose **{bot_choice}**.\n\n**{result.upper()}**"), view=None)
        self.stop()

    @discord.ui.button(label="Rock", emoji="🪨")
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.choose(interaction, "rock")

    @discord.ui.button(label="Paper", emoji="📄")
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.choose(interaction, "paper")

    @discord.ui.button(label="Scissors", emoji="✂️")
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.choose(interaction, "scissors")


async def tag_name_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    rows = await interaction.client.db.fetchall("SELECT name FROM tags WHERE guild_id=? AND name LIKE ? ORDER BY name LIMIT 25", (interaction.guild_id, current.casefold() + "%"))  # type: ignore[attr-defined]
    return [app_commands.Choice(name=row["name"], value=row["name"]) for row in rows]


class Fun(commands.Cog):
    tag = app_commands.Group(name="tag", description="Server custom responses")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.last_count: dict[int, tuple[int, int]] = {}

    @app_commands.command(name="8ball", description="Ask the magic 8-ball a question")
    async def eight_ball(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.send_message(embed=embed("Magic 8-ball", random.choice(["It is certain.", "Without a doubt.", "Ask again later.", "Cannot predict now.", "Don't count on it.", "Very doubtful."])))

    async def _api_json(self, url: str) -> dict | list | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                    return await response.json()
        except (aiohttp.ClientError, TimeoutError):
            return None

    @app_commands.command(name="meme", description="Fetch a random meme")
    async def meme(self, interaction: discord.Interaction) -> None:
        data = await self._api_json("https://meme-api.com/gimme")
        if not isinstance(data, dict) or not data.get("url"):
            await interaction.response.send_message(embed=error("The meme service is unavailable."), ephemeral=True)
            return
        result = embed(data.get("title", "Random meme"), f"from r/{data.get('subreddit', 'memes')}")
        result.set_image(url=data["url"])
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="joke", description="Tell a random joke")
    async def joke(self, interaction: discord.Interaction) -> None:
        data = await self._api_json("https://official-joke-api.appspot.com/random_joke")
        text = f"{data['setup']}\n\n||{data['punchline']}||" if isinstance(data, dict) and data.get("setup") else "Why did the bot cross the channel? To get to the other side of the API."
        await interaction.response.send_message(embed=embed("Joke", text))

    @app_commands.command(name="fact", description="Share a random fact")
    async def fact(self, interaction: discord.Interaction) -> None:
        data = await self._api_json("https://uselessfacts.jsph.pl/api/v2/facts/random?language=en")
        text = data.get("text") if isinstance(data, dict) else "Honey never spoils when stored properly."
        await interaction.response.send_message(embed=embed("Random fact", text))

    @app_commands.command(name="quote", description="Share an inspirational quote")
    async def quote(self, interaction: discord.Interaction) -> None:
        data = await self._api_json("https://dummyjson.com/quotes/random")
        text = f"“{data['quote']}”\n— {data['author']}" if isinstance(data, dict) and data.get("quote") else "“Great things are done by a series of small things brought together.” — Vincent van Gogh"
        await interaction.response.send_message(embed=embed("Quote", text))

    @app_commands.command(name="rps", description="Play rock paper scissors")
    async def rps(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=embed("Rock Paper Scissors", "Choose your move."), view=RPSView(self, interaction.user.id))

    @app_commands.command(name="ship", description="Calculate a playful compatibility score")
    async def ship(self, interaction: discord.Interaction, first: discord.User, second: Optional[discord.User] = None) -> None:
        second = second or interaction.user
        random.seed(min(first.id, second.id) + max(first.id, second.id))
        score = random.randint(0, 100)
        random.seed()
        await interaction.response.send_message(embed=embed("Compatibility", f"{first.mention} 💞 {second.mention}\n\n**{score}%** — {['The stars are curious.', 'There is potential!', 'A legendary duo.'][0 if score < 35 else 1 if score < 75 else 2]}"))

    @app_commands.command(name="rate", description="Rate anything with a little personality")
    async def rate(self, interaction: discord.Interaction, thing: str) -> None:
        score = random.randint(0, 100)
        await interaction.response.send_message(embed=embed("Official rating", f"I rate **{thing[:150]}** a **{score}/100**."))

    @app_commands.command(name="trivia", description="Get a random trivia question")
    async def trivia(self, interaction: discord.Interaction) -> None:
        data = await self._api_json("https://opentdb.com/api.php?amount=1&type=multiple")
        if not isinstance(data, dict) or not data.get("results"):
            await interaction.response.send_message(embed=error("Trivia is unavailable right now."), ephemeral=True)
            return
        import html
        question = html.unescape(data["results"][0]["question"])
        answer = html.unescape(data["results"][0]["correct_answer"])
        choices = [html.unescape(value) for value in data["results"][0]["incorrect_answers"]] + [answer]
        random.shuffle(choices)
        view = TriviaView(question, answer, choices, interaction.user.id)
        await interaction.response.send_message(embed=embed("Trivia", question), view=view)

    @app_commands.command(name="caption", description="Add a simple caption to an uploaded image")
    async def caption(self, interaction: discord.Interaction, image: discord.Attachment, text: str) -> None:
        if not image.content_type or not image.content_type.startswith("image/") or image.size > 8_000_000:
            await interaction.response.send_message("Attach an image smaller than 8 MB.", ephemeral=True)
            return
        try:
            from PIL import Image, ImageDraw, ImageFont
            source = Image.open(io.BytesIO(await image.read())).convert("RGB")
            draw = ImageDraw.Draw(source)
            font = ImageFont.load_default(size=max(18, source.width // 24))
            draw.rectangle((0, 0, source.width, 70), fill=(0, 0, 0))
            draw.text((source.width // 2, 35), text[:150], fill="white", font=font, anchor="mm")
            output = io.BytesIO()
            source.save(output, format="PNG")
            output.seek(0)
        except (ImportError, OSError):
            await interaction.response.send_message("Image tools are unavailable on this deployment.", ephemeral=True)
            return
        await interaction.response.send_message(file=discord.File(output, filename="caption.png"))

    @tag.command(name="create", description="Create a custom tag")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def tag_create(self, interaction: discord.Interaction, name: str, content: str) -> None:
        name = name.casefold().strip()
        if not name.isalnum() or len(name) > 32:
            await interaction.response.send_message("Tag names must be 1–32 letters or digits.", ephemeral=True)
            return
        await self.bot.db.execute("INSERT INTO tags (guild_id,name,content,owner_id,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(guild_id,name) DO UPDATE SET content=excluded.content,owner_id=excluded.owner_id,updated_at=excluded.updated_at", (interaction.guild_id, name, content[:2000], interaction.user.id, discord.utils.utcnow().isoformat()))
        await interaction.response.send_message(embed=ok(f"Tag `{name}` saved."))

    @tag.command(name="edit", description="Edit a custom tag")
    @app_commands.autocomplete(name=tag_name_autocomplete)
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def tag_edit(self, interaction: discord.Interaction, name: str, content: str) -> None:
        changed = await self.bot.db.execute("UPDATE tags SET content=?,owner_id=?,updated_at=? WHERE guild_id=? AND name=?", (content[:2000], interaction.user.id, discord.utils.utcnow().isoformat(), interaction.guild_id, name.casefold()))
        await interaction.response.send_message(embed=ok("Tag updated.") if changed else error("Tag not found."))

    @tag.command(name="delete", description="Delete a custom tag")
    @app_commands.autocomplete(name=tag_name_autocomplete)
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def tag_delete(self, interaction: discord.Interaction, name: str) -> None:
        await self.bot.db.execute("DELETE FROM tags WHERE guild_id=? AND name=?", (interaction.guild_id, name.casefold()))
        await interaction.response.send_message(embed=ok("Tag deleted."))

    @tag.command(name="list", description="List this server's custom tags")
    @app_commands.guild_only()
    async def tag_list(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall("SELECT name FROM tags WHERE guild_id=? ORDER BY name", (interaction.guild_id,))
        await interaction.response.send_message(embed=embed("Server tags", ", ".join(f"`{row['name']}`" for row in rows) or "No tags yet."))

    @app_commands.command(name="count", description="Post the next number in the configured counting channel")
    @app_commands.guild_only()
    async def count(self, interaction: discord.Interaction, number: int) -> None:
        channel_id = await self.bot.db.setting(interaction.guild_id, "counting_channel_id")
        if channel_id != interaction.channel_id:
            await interaction.response.send_message("Counting is not enabled in this channel.", ephemeral=True)
            return
        last = self.last_count.get(interaction.guild_id, (0, 0))
        if last[1] == interaction.user.id or number != last[0] + 1:
            self.last_count[interaction.guild_id] = (0, 0)
            await interaction.response.send_message(embed=error("Wrong number. The count resets to **0**."))
            return
        self.last_count[interaction.guild_id] = (number, interaction.user.id)
        await interaction.response.send_message(embed=ok(f"**{number}** — keep going!"))

    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        tag = await self.bot.db.fetchone("SELECT content FROM tags WHERE guild_id=? AND name=?", (message.guild.id, message.content.casefold().strip()))
        if tag:
            await message.channel.send(tag["content"])


class TriviaView(discord.ui.View):
    def __init__(self, question: str, answer: str, choices: list[str], author_id: int) -> None:
        super().__init__(timeout=45)
        self.answer, self.author_id = answer, author_id
        for choice in choices:
            button = discord.ui.Button(label=shorten(choice, 75), style=discord.ButtonStyle.primary)
            button.callback = self._answer(choice)  # type: ignore[method-assign]
            self.add_item(button)

    def _answer(self, choice: str):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("This trivia question belongs to another player.", ephemeral=True)
                return
            await interaction.response.edit_message(embed=embed("Trivia", f"{'Correct! 🎉' if choice == self.answer else f'Not quite. The answer was **{self.answer}**.'}"), view=None)
            self.stop()
        return callback


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Fun(bot))
