from __future__ import annotations

import asyncio
import logging
import random
import urllib.parse
from dataclasses import dataclass, field

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import embed, error, ok
from bot.utils.modules import ModuleCog
from bot.utils.ui import Paginator

log = logging.getLogger(__name__)

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}
FFMPEG_OPTIONS = {"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5", "options": "-vn"}


@dataclass(slots=True)
class Track:
    title: str
    webpage_url: str
    stream_url: str | None
    requester_id: int
    duration: int = 0
    thumbnail: str | None = None


@dataclass(slots=True)
class Player:
    queue: list[Track] = field(default_factory=list)
    current: Track | None = None
    loop: str = "off"
    volume: float = 0.5
    voice: discord.VoiceClient | None = None
    skip_requested: bool = False


class Music(ModuleCog):
    music = app_commands.Group(name="music", description="Voice playback and queue controls")
    module_name = "music"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players: dict[int, Player] = {}

    def player(self, guild_id: int) -> Player:
        return self.players.setdefault(guild_id, Player())

    async def _dj_allowed(self, interaction: discord.Interaction) -> bool:
        role_id = await self.bot.db.setting(interaction.guild_id, "dj_role_id")
        if not role_id or not isinstance(interaction.user, discord.Member):
            return True
        return interaction.user.guild_permissions.manage_guild or any(role.id == role_id for role in interaction.user.roles)

    async def _require_dj(self, interaction: discord.Interaction) -> bool:
        if await self._dj_allowed(interaction):
            return True
        await interaction.response.send_message("Only the configured DJ role can control music.", ephemeral=True)
        return False

    async def _extract(self, query: str) -> Track:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("yt-dlp is not installed") from exc

        def extract() -> dict:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                return ydl.extract_info(query, download=False)

        data = await asyncio.to_thread(extract)
        if not data:
            raise RuntimeError("No results found")
        if "entries" in data:
            entries = [entry for entry in (data.get("entries") or []) if entry]
            if not entries:
                raise RuntimeError("No results found")
            data = entries[0]
        return Track(
            data.get("title", "Unknown track"),
            data.get("webpage_url", query),
            data.get("url"),
            0,
            int(data.get("duration") or 0),
            data.get("thumbnail"),
        )

    async def _play_next(self, guild_id: int, *, force_next: bool = False) -> None:
        player = self.player(guild_id)
        if not player.voice or not player.voice.is_connected():
            return
        attempts = 0
        while attempts < 5:
            if force_next or not (player.loop == "track" and player.current):
                if player.queue:
                    track = player.queue.pop(0)
                else:
                    player.current = None
                    return
            else:
                track = player.current
            force_next = False
            player.current = track
            if not track or not track.stream_url:
                attempts += 1
                continue
            try:
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS), volume=player.volume
                )
                player.voice.play(
                    source,
                    after=lambda err: asyncio.run_coroutine_threadsafe(self._after_track(guild_id, err), self.bot.loop),
                )
                return
            except (discord.ClientException, FileNotFoundError):
                attempts += 1
                continue
        player.current = None

    async def _after_track(self, guild_id: int, playback_error: Exception | None) -> None:
        if playback_error:
            log.warning("Music playback error: %s", playback_error)
        player = self.player(guild_id)
        skipped = player.skip_requested
        player.skip_requested = False
        if player.loop == "queue" and player.current:
            player.queue.append(player.current)
        await self._play_next(guild_id, force_next=skipped)

    @music.command(name="join", description="Join your voice channel")
    @app_commands.guild_only()
    async def join(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
        player = self.player(interaction.guild_id)
        if player.voice and player.voice.is_connected():
            await player.voice.move_to(channel)
        else:
            player.voice = await channel.connect()
        await interaction.response.send_message(embed=ok(f"Joined **{channel.name}**."))

    @music.command(name="leave", description="Leave the voice channel and clear the queue")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        if not await self._require_dj(interaction):
            return
        player = self.player(interaction.guild_id)
        player.queue.clear()
        player.current = None
        if player.voice:
            await player.voice.disconnect()
            player.voice = None
        await interaction.response.send_message(embed=ok("Left the voice channel and cleared the queue."))

    @music.command(name="play", description="Play a YouTube URL or search term")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        if not await self._dj_allowed(interaction):
            await interaction.response.send_message("Only the configured DJ role can control music.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        await interaction.response.defer()
        player = self.player(interaction.guild_id)
        if not player.voice or not player.voice.is_connected():
            player.voice = await interaction.user.voice.channel.connect()
        try:
            track = await self._extract(query)
            track.requester_id = interaction.user.id
        except Exception as exc:
            await interaction.followup.send(embed=error(f"I couldn't find that track: {exc}"), ephemeral=True)
            return
        was_idle = not player.current and not player.voice.is_playing()
        player.queue.append(track)
        if was_idle:
            await self._play_next(interaction.guild_id)
        await interaction.followup.send(embed=ok(f"Queued **{track.title}**."))

    @music.command(name="pause", description="Pause the current track")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        if not await self._require_dj(interaction):
            return
        player = self.player(interaction.guild_id)
        if player.voice and player.voice.is_playing():
            player.voice.pause()
        await interaction.response.send_message(embed=ok("Playback paused."))

    @music.command(name="resume", description="Resume paused playback")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        if not await self._require_dj(interaction):
            return
        player = self.player(interaction.guild_id)
        if player.voice and player.voice.is_paused():
            player.voice.resume()
        await interaction.response.send_message(embed=ok("Playback resumed."))

    @music.command(name="skip", description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        if not await self._require_dj(interaction):
            return
        player = self.player(interaction.guild_id)
        player.skip_requested = True
        if player.voice and (player.voice.is_playing() or player.voice.is_paused()):
            player.voice.stop()
        await interaction.response.send_message(embed=ok("Skipped."))

    @music.command(name="stop", description="Stop playback and clear the queue")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        if not await self._require_dj(interaction):
            return
        player = self.player(interaction.guild_id)
        player.queue.clear()
        player.current = None
        player.loop = "off"
        if player.voice and player.voice.is_playing():
            player.voice.stop()
        await interaction.response.send_message(embed=ok("Playback stopped and queue cleared."))

    @music.command(name="queue", description="View the current music queue")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = self.player(interaction.guild_id)
        rows = ([f"🎵 **Now:** {player.current.title}"] if player.current else []) + [
            f"{i}. {track.title}" for i, track in enumerate(player.queue, 1)
        ]
        pages = []
        chunk = rows or ["The queue is empty."]
        for offset in range(0, len(chunk), 15):
            pages.append(embed("Music queue", "\n".join(chunk[offset : offset + 15])))
        view = Paginator(interaction.user.id, pages)
        await view.send(interaction)

    @music.command(name="remove", description="Remove a track from the music queue")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: app_commands.Range[int, 1, 100]) -> None:
        if not await self._require_dj(interaction):
            return
        player = self.player(interaction.guild_id)
        if position > len(player.queue):
            await interaction.response.send_message("That queue position does not exist.", ephemeral=True)
            return
        track = player.queue.pop(position - 1)
        await interaction.response.send_message(embed=ok(f"Removed **{track.title}**."))

    @music.command(name="clear", description="Clear the music queue")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        if not await self._require_dj(interaction):
            return
        self.player(interaction.guild_id).queue.clear()
        await interaction.response.send_message(embed=ok("Queue cleared."))

    @music.command(name="volume", description="Set playback volume")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, percentage: app_commands.Range[int, 0, 200]) -> None:
        if not await self._require_dj(interaction):
            return
        player = self.player(interaction.guild_id)
        player.volume = percentage / 100
        if player.voice and isinstance(player.voice.source, discord.PCMVolumeTransformer):
            player.voice.source.volume = player.volume
        await interaction.response.send_message(embed=ok(f"Volume set to **{percentage}%**."))

    @music.command(name="loop", description="Set loop mode")
    @app_commands.guild_only()
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value="off"),
            app_commands.Choice(name="Track", value="track"),
            app_commands.Choice(name="Queue", value="queue"),
        ]
    )
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        if not await self._require_dj(interaction):
            return
        self.player(interaction.guild_id).loop = mode.value
        await interaction.response.send_message(embed=ok(f"Loop mode: **{mode.name}**."))

    @music.command(name="shuffle", description="Shuffle the music queue")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        if not await self._require_dj(interaction):
            return
        random.shuffle(self.player(interaction.guild_id).queue)
        await interaction.response.send_message(embed=ok("Queue shuffled."))

    @music.command(name="nowplaying", description="Show the current track")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        track = self.player(interaction.guild_id).current
        if not track:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        result = embed("Now playing", f"[{track.title}]({track.webpage_url})\nRequested by <@{track.requester_id}>")
        if track.thumbnail:
            result.set_thumbnail(url=track.thumbnail)
        await interaction.response.send_message(embed=result)

    @music.command(name="lyrics", description="Fetch lyrics for a song")
    async def lyrics(self, interaction: discord.Interaction, song: str) -> None:
        await interaction.response.defer()
        if " - " in song:
            artist, title = song.split(" - ", 1)
        else:
            parts = song.split(" ", 1)
            artist, title = (parts[0], parts[1]) if len(parts) == 2 else ("", song)
        url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(artist or 'Unknown')}/{urllib.parse.quote(title)}"
        try:
            session = self.bot.session or aiohttp.ClientSession()
            close = self.bot.session is None
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    data = await response.json(content_type=None)
            finally:
                if close:
                    await session.close()
            lyrics = data.get("lyrics") if isinstance(data, dict) else None
            if not lyrics:
                raise ValueError
        except (aiohttp.ClientError, ValueError, TypeError):
            await interaction.followup.send(embed=error("Lyrics not found. Try `Artist - Title`."), ephemeral=True)
            return
        await interaction.followup.send(embed=embed(f"Lyrics — {song}", lyrics[:4000]))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
