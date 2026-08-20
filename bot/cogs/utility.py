from __future__ import annotations

import io
import platform
import urllib.parse
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import embed, error, info, ok, shorten
from bot.utils.modules import ModuleCog, module_enabled
from bot.utils.time import human_duration, parse_duration
from bot.utils.ui import HelpView


class PollView(discord.ui.View):
    def __init__(self, question: str, options: list[str]) -> None:
        super().__init__(timeout=None)
        self.question, self.options = question, options
        self.votes: dict[int, int] = {}
        for index, option in enumerate(options):
            button = discord.ui.Button(
                label=shorten(option, 75), style=discord.ButtonStyle.primary, custom_id=f"poll:{id(self)}:{index}"
            )
            button.callback = self._vote(index)  # type: ignore[method-assign]
            self.add_item(button)

    def _vote(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            self.votes[interaction.user.id] = index
            counts = [sum(value == i for value in self.votes.values()) for i in range(len(self.options))]
            await interaction.response.send_message(f"Vote recorded for **{self.options[index]}**.", ephemeral=True)
            if interaction.message:
                await interaction.message.edit(embed=self.result_embed(counts), view=self)

        return callback

    def result_embed(self, counts: list[int] | None = None) -> discord.Embed:
        counts = counts or [sum(value == i for value in self.votes.values()) for i in range(len(self.options))]
        total = sum(counts)
        body = "\n".join(
            f"**{i + 1}. {option}** — {count} vote{'s' if count != 1 else ''}"
            for i, (option, count) in enumerate(zip(self.options, counts))
        )
        return embed(self.question, f"{body}\n\n*{total} total votes*")


def help_pages() -> dict[str, discord.Embed]:
    return {
        "moderation": embed(
            "Moderation",
            "`/ban` `/kick` `/warn` `/warnings` `/timeout` `/purge` `/lock` `/unlock` `/lockdown` `/slowmode` `/modlogs`\n\n"
            "Staff commands require the matching Discord permission.",
        ),
        "server": embed(
            "Server configuration",
            "`/setup` `/panel` `/module` `/config prefix` `/config language` `/config logs` `/config welcome` "
            "`/config leave` `/config autorole` `/config automod` `/config view` `/config export`",
        ),
        "utility": embed(
            "Utility",
            "`/userinfo` `/serverinfo` `/avatar` `/banner` `/ping` `/botinfo` `/remindme` `/poll` `/afk` "
            "`/translate` `/weather` `/define` `/qr` `/shorten` `/snipe` `/editsnipe` `/invite`",
        ),
        "community": embed(
            "Community",
            "`/rank` `/leaderboard` `/balance` `/daily` `/weekly` `/work` `/pay` `/shop` `/inventory`\n"
            "`/8ball` `/joke` `/fact` `/quote` `/rps` `/ship` `/rate` `/meme` `/trivia`",
        ),
        "support": embed(
            "Tickets, giveaways, music",
            "`/ticket setup` `/ticket close` `/ticket claim`\n"
            "`/giveaway create` `/giveaway end` `/giveaway reroll` `/giveaway list`\n"
            "`/music play` `/music skip` `/music queue` `/music nowplaying`",
        ),
        "safety": embed(
            "Protection & voice",
            "`/auditperms` `/backupserver` `/starboard` `/confess` `/lfg` `/jointocreate` `/vclock` `/vclimit`",
        ),
    }


class Utility(ModuleCog):
    module_name = "utility"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        command = interaction.command
        name = getattr(command, "name", None)
        if name in {"help", "ping", "botinfo", "invite"}:
            return True
        return await super().interaction_check(interaction)

    async def cog_load(self) -> None:
        self.bot.scheduler.register("reminder", self._deliver_reminder)

    async def _deliver_reminder(self, payload: dict) -> None:
        reminder = await self.bot.db.close_reminder(int(payload["reminder_id"]))
        if not reminder:
            return
        channel = self.bot.get_channel(reminder["channel_id"]) if reminder["channel_id"] else None
        try:
            user = self.bot.get_user(reminder["user_id"]) or await self.bot.fetch_user(reminder["user_id"])
        except discord.HTTPException:
            user = None
        destination = channel if channel and hasattr(channel, "send") else user
        if destination is None:
            return
        try:
            await destination.send(embed=embed("Reminder", reminder["message"]))  # type: ignore[union-attr]
        except discord.HTTPException:
            pass

    async def _json(self, method: str, url: str, **kwargs):
        session = self.bot.session
        close = False
        if session is None or session.closed:
            session = aiohttp.ClientSession()
            close = True
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.content_type and "json" in response.content_type:
                    return await response.json()
                return await response.text()
        finally:
            if close:
                await session.close()

    @app_commands.command(name="help", description="Browse Aegis commands by category")
    async def help_command(self, interaction: discord.Interaction) -> None:
        pages = help_pages()
        await interaction.response.send_message(embed=pages["utility"], view=HelpView(pages), ephemeral=True)

    @commands.command(name="ping", help="Show bot and Discord API latency")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def legacy_ping(self, context: commands.Context) -> None:
        await context.reply(embed=info(f"Gateway latency: **{self.bot.latency * 1000:.0f} ms**"), mention_author=False)

    @commands.command(name="help", help="Open the interactive command guide")
    async def legacy_help(self, context: commands.Context) -> None:
        await context.reply("Use `/help` for the interactive command guide.", mention_author=False)

    @app_commands.command(name="ping", description="Show bot and Discord API latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=info(f"Gateway: **{self.bot.latency * 1000:.0f} ms**\nAPI: measuring…"))
        message = await interaction.original_response()
        started = discord.utils.utcnow()
        await message.edit(
            embed=info(
                f"Gateway: **{self.bot.latency * 1000:.0f} ms**\n"
                f"API: **{(discord.utils.utcnow() - started).total_seconds() * 1000:.0f} ms**"
            )
        )

    @app_commands.command(name="userinfo", description="Display account, roles and permissions")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        member = member or interaction.user  # type: ignore[assignment]
        roles = [role.mention for role in reversed(member.roles[1:])]
        permissions = [name.replace("_", " ").title() for name, value in member.guild_permissions if value]
        result = embed(f"User info — {member}", colour=member.colour if member.colour.value else discord.Colour(0x5865F2))
        result.set_thumbnail(url=member.display_avatar.url)
        result.add_field(name="Account created", value=f"<t:{int(member.created_at.timestamp())}:F>")
        result.add_field(name="Joined server", value=f"<t:{int(member.joined_at.timestamp())}:F>" if member.joined_at else "Unknown")
        result.add_field(name="Roles", value=shorten(" ".join(roles) or "None"))
        result.add_field(name="Key permissions", value=shorten(", ".join(permissions) or "None"), inline=False)
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="serverinfo", description="Display server statistics")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        result = embed(f"Server info — {guild.name}")
        if guild.icon:
            result.set_thumbnail(url=guild.icon.url)
        result.add_field(name="Members", value=f"{guild.member_count:,}")
        result.add_field(name="Channels", value=str(len(guild.channels)))
        result.add_field(name="Roles", value=str(len(guild.roles)))
        result.add_field(name="Boosts", value=f"Level {guild.premium_tier} • {guild.premium_subscription_count or 0}")
        result.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:F>")
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="avatar", description="Show a user's avatar")
    async def avatar(self, interaction: discord.Interaction, user: Optional[discord.User] = None) -> None:
        user = user or interaction.user
        result = embed(f"Avatar — {user}")
        result.set_image(url=user.display_avatar.replace(size=1024).url)
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="banner", description="Show a user's profile banner")
    async def banner(self, interaction: discord.Interaction, user: Optional[discord.User] = None) -> None:
        user = await self.bot.fetch_user((user or interaction.user).id)
        if not user.banner:
            await interaction.response.send_message(embed=info(f"{user} does not have a profile banner."), ephemeral=True)
            return
        result = embed(f"Banner — {user}")
        result.set_image(url=user.banner.replace(size=1024).url)
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="roleinfo", description="Display role permissions and members")
    @app_commands.guild_only()
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role) -> None:
        members = [member.mention for member in role.members]
        result = embed(f"Role info — {role.name}", colour=role.colour if role.colour.value else discord.Colour(0x5865F2))
        result.add_field(name="Members", value=f"{len(members):,}")
        result.add_field(name="Position", value=str(role.position))
        result.add_field(name="Mentionable", value=str(role.mentionable))
        result.add_field(
            name="Permissions",
            value=shorten(", ".join(p.replace("_", " ") for p, enabled in role.permissions if enabled) or "None"),
        )
        result.add_field(name="Member list", value=shorten(" ".join(members) or "None"), inline=False)
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="channelinfo", description="Display information about a channel")
    @app_commands.guild_only()
    async def channelinfo(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        channel = channel or interaction.channel  # type: ignore[assignment]
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Pick a text channel.", ephemeral=True)
            return
        result = embed(f"Channel info — {channel.name}")
        result.add_field(name="Type", value=str(channel.type).title())
        result.add_field(name="Category", value=channel.category.mention if channel.category else "None")
        result.add_field(name="Created", value=f"<t:{int(channel.created_at.timestamp())}:F>")
        result.add_field(name="Topic", value=shorten(channel.topic or "None"), inline=False)
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="botinfo", description="Show Aegis uptime and resource statistics")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        guilds = len(self.bot.guilds)
        users = sum(guild.member_count or 0 for guild in self.bot.guilds)
        result = embed(
            f"{self.bot.settings.bot_name} statistics",
            f"Uptime: **{human_duration(self.bot.uptime_seconds)}**\n"
            f"Python: **{platform.python_version()}**\n"
            f"discord.py: **{discord.__version__}**\n"
            f"Memory: **{self.bot.memory_mb:.1f} MB**",
        )
        result.add_field(name="Servers", value=f"{guilds:,}")
        result.add_field(name="Approx. users", value=f"{users:,}")
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="invite", description="Get an invite link for Aegis")
    async def invite(self, interaction: discord.Interaction) -> None:
        if not self.bot.user:
            await interaction.response.send_message("The bot is still starting up.", ephemeral=True)
            return
        perms = discord.Permissions(
            manage_guild=True,
            ban_members=True,
            kick_members=True,
            moderate_members=True,
            manage_messages=True,
            manage_channels=True,
            manage_roles=True,
            view_audit_log=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            add_reactions=True,
            connect=True,
            speak=True,
            use_voice_activation=True,
        )
        url = discord.utils.oauth_url(self.bot.user.id, permissions=perms, scopes=("bot", "applications.commands"))
        await interaction.response.send_message(embed=ok(f"[Invite Aegis]({url})"), ephemeral=True)

    @app_commands.command(name="remindme", description="Create a reminder that persists across restarts")
    async def remindme(self, interaction: discord.Interaction, duration: str, message: str, dm: bool = False) -> None:
        try:
            delta = parse_duration(duration, maximum=365 * 86400)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        run_at = discord.utils.utcnow() + delta
        reminder_id = await self.bot.db.create_reminder(
            None if dm else interaction.guild_id,
            interaction.user.id,
            None if dm else interaction.channel_id,
            message[:1000],
            run_at,
        )
        await interaction.response.send_message(
            embed=ok(f"Reminder **#{reminder_id}** set for <t:{int(run_at.timestamp())}:R>."), ephemeral=True
        )

    @app_commands.command(name="poll", description="Create a button-based poll")
    async def poll(self, interaction: discord.Interaction, question: str, options: str) -> None:
        values = [part.strip() for part in options.split(",") if part.strip()][:5]
        if len(values) < 2:
            await interaction.response.send_message("Provide at least two comma-separated options.", ephemeral=True)
            return
        view = PollView(question[:250], values)
        await interaction.response.send_message(embed=view.result_embed(), view=view)

    @app_commands.command(name="afk", description="Set or clear your AFK status")
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK") -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("AFK is a server feature.", ephemeral=True)
            return
        await self.bot.db.execute(
            "INSERT INTO afk (guild_id,user_id,reason,created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=excluded.reason, created_at=excluded.created_at",
            (interaction.guild_id, interaction.user.id, reason[:250], discord.utils.utcnow().isoformat()),
        )
        await interaction.response.send_message(embed=ok(f"AFK set: **{reason[:250]}**"), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        if not await module_enabled(self.bot, message.guild.id, "utility"):
            return
        mentioned = await self.bot.db.fetchone(
            "SELECT * FROM afk WHERE guild_id=? AND user_id=?", (message.guild.id, message.author.id)
        )
        if mentioned:
            await self.bot.db.execute(
                "DELETE FROM afk WHERE guild_id=? AND user_id=?", (message.guild.id, message.author.id)
            )
            try:
                await message.channel.send(
                    embed=info(f"Welcome back, {message.author.mention}. Your AFK status was cleared."),
                    delete_after=8,
                )
            except discord.HTTPException:
                pass
        for user in message.mentions:
            afk = await self.bot.db.fetchone(
                "SELECT * FROM afk WHERE guild_id=? AND user_id=?", (message.guild.id, user.id)
            )
            if afk:
                try:
                    await message.channel.send(embed=info(f"{user.display_name} is AFK: {afk['reason']}"), delete_after=10)
                except discord.HTTPException:
                    pass

    @app_commands.command(name="translate", description="Translate text using the configured translation service")
    async def translate(self, interaction: discord.Interaction, text: str, target: str = "en") -> None:
        await interaction.response.defer()
        url = self.bot.settings.translate_api_url or "https://translate.astian.org/translate"
        try:
            data = await self._json("POST", url, json={"q": text[:3000], "source": "auto", "target": target.lower()})
            translated = data.get("translatedText") or data.get("translation") if isinstance(data, dict) else None
            if not translated:
                raise ValueError
        except (aiohttp.ClientError, ValueError, KeyError, TypeError):
            await interaction.followup.send(embed=error("The translation service is unavailable right now."))
            return
        await interaction.followup.send(embed=embed(f"Translation → {target.lower()}", translated))

    @app_commands.command(name="weather", description="Show current weather for a city")
    async def weather(self, interaction: discord.Interaction, city: str) -> None:
        key = self.bot.settings.weather_api_key
        if not key:
            await interaction.response.send_message(
                "Weather is disabled until OPENWEATHER_API_KEY is configured.", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            data = await self._json(
                "GET",
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": key, "units": "metric"},
            )
            if not isinstance(data, dict) or data.get("cod") != 200:
                raise ValueError
        except (aiohttp.ClientError, ValueError):
            await interaction.followup.send(embed=error("I couldn't find that city."))
            return
        await interaction.followup.send(
            embed=embed(
                f"Weather — {data['name']}",
                f"**{data['weather'][0]['description'].title()}**\n"
                f"Temperature: **{data['main']['temp']:.1f}°C**\n"
                f"Feels like: **{data['main']['feels_like']:.1f}°C**\n"
                f"Humidity: **{data['main']['humidity']}%**",
            )
        )

    @app_commands.command(name="define", description="Look up a word in the dictionary")
    async def define(self, interaction: discord.Interaction, word: str) -> None:
        await interaction.response.defer()
        try:
            data = await self._json(
                "GET", f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
            )
            definition = data[0]["meanings"][0]["definitions"][0]["definition"]
            example = data[0]["meanings"][0]["definitions"][0].get("example")
        except (aiohttp.ClientError, IndexError, KeyError, TypeError):
            await interaction.followup.send(embed=error("No definition found."))
            return
        await interaction.followup.send(
            embed=embed(f"Definition — {word}", definition + (f"\n\n*Example: {example}*" if example else ""))
        )

    @app_commands.command(name="qr", description="Generate a QR code from text or a URL")
    async def qr(self, interaction: discord.Interaction, text: str) -> None:
        try:
            import qrcode

            image = qrcode.make(text[:2000])
            output = io.BytesIO()
            image.save(output, format="PNG")
            output.seek(0)
        except ImportError:
            await interaction.response.send_message("QR generation is not installed on this deployment.", ephemeral=True)
            return
        await interaction.response.send_message(file=discord.File(output, filename="aegis-qr.png"))

    @app_commands.command(name="shorten", description="Shorten a URL")
    async def shorten_url(self, interaction: discord.Interaction, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            await interaction.response.send_message("Provide a complete http(s) URL.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            shortened = await self._json("GET", "https://tinyurl.com/api-create.php", params={"url": url})
            if not isinstance(shortened, str) or not shortened.startswith("http"):
                raise ValueError
        except (aiohttp.ClientError, ValueError):
            await interaction.followup.send(embed=error("The URL shortener is unavailable."), ephemeral=True)
            return
        await interaction.followup.send(embed=ok(f"Short URL: {shortened}"))

    @app_commands.command(name="snipe", description="Retrieve the last deleted message in this channel")
    @app_commands.guild_only()
    async def snipe(self, interaction: discord.Interaction) -> None:
        data = self.bot.deleted_messages.get(interaction.channel_id)
        if not data:
            await interaction.response.send_message("Nothing to snipe here.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embed("Last deleted message", f"**{data['author']}**\n{data['content'] or '*no text*'}")
        )

    @app_commands.command(name="editsnipe", description="Retrieve the last edited message in this channel")
    @app_commands.guild_only()
    async def editsnipe(self, interaction: discord.Interaction) -> None:
        data = self.bot.edited_messages.get(interaction.channel_id)
        if not data:
            await interaction.response.send_message("Nothing to editsnipe here.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embed(
                "Last edited message",
                f"**{data['author']}**\n**Before:** {data['before']}\n**After:** {data['after']}",
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
