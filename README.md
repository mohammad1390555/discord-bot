# Aegis — full-featured Discord bot

Aegis is a modular `discord.py 2.x` bot combining moderation, community tooling,
utility, tickets, giveaways, leveling, economy, fun, logging and music. It uses
slash commands through Discord's Application Commands API, with an optional,
per-guild legacy prefix.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# edit .env and set DISCORD_TOKEN and OWNER_IDS
# optional: edit config/config.yml and config/messages.yml
python main.py
```

Or build the included image (FFmpeg is installed for music):

```bash
docker build -t aegis-discord-bot .
docker run --env-file .env -v aegis-data:/app/data aegis-discord-bot
```

Invite the application with the `bot` and `applications.commands` scopes. The bot
needs the permissions for the features you enable. For development, set
`SYNC_GUILD_ID` to a guild ID: commands then appear immediately instead of waiting
for global command propagation.

## Architecture

```
bot/
  __main__.py             validated startup and logging
  config.py               environment-only secrets and deployment settings
  database.py             async SQLite/WAL persistence and domain helpers
  core/
    bot.py                intents, extension loading, error boundary, prefixes
    scheduler.py          persistent restart-safe task scheduler
  cogs/
    admin.py              owner-only operations and safe expression evaluator
    configuration.py      setup wizard, language/prefix/log/welcome/config backup
    moderation.py         cases, warnings, actions, confirmation views
    automod.py            filters, spam checks, anti-raid and autorole/welcome
    logging_events.py     message/member/channel/voice audit events
    utility.py            profiles, polls, reminders, AFK, APIs and sniping
    tickets.py            private ticket panel and transcript close flow
    giveaways.py          persistent button giveaways and rerolls
    leveling.py           cooldown XP, ranks, leaderboards and role rewards
    economy.py            wallet, rewards, shop, inventory and mini-games
    fun.py                games, APIs, tags, counting and image captions
    music.py              voice queue with yt-dlp/FFmpeg controls
  utils/
    embeds.py             consistent brand embeds
    checks.py             hierarchy and user-facing error helpers
    time.py               safe duration parsing
    ui.py                 confirmation, pagination and interactive help
migrations/001_initial.sql persistent schema
```

### Persistence and scaling

All time-based actions are stored in `scheduled_tasks` with UTC ISO timestamps.
The scheduler claims due work transactionally, so reminders, temporary bans/timeouts
and giveaways survive restarts and do not execute twice when multiple workers are
used. SQLite is configured for WAL mode and is suitable for a small deployment.
The `Database` interface is deliberately isolated so an async PostgreSQL adapter
can replace it for a sharded deployment without changing cogs.

Guild settings are namespaced JSON with safe defaults. `/exportconfig` and
`/importconfig` provide backup/restore without storing secrets. Sensitive commands
use Discord's built-in default permissions, role hierarchy checks and confirmation
buttons where appropriate. All responses share a brand colour, timestamp and
version footer; `/help` uses a category select menu and long lists use pagination.

## Operational notes

- Enable **Server Members Intent** and **Message Content Intent** in the Developer
  Portal; the code requests both because automod, welcome, XP and prefix commands
  require them.
- Music also needs FFmpeg installed on the host. Spotify links are resolved by
  yt-dlp's search fallback; Spotify itself does not provide audio streams.
- External commands (`weather`, `translate`, `define`, `meme`, etc.) fail softly and
  never block moderation. Set API keys only in `.env`.
- `evalexec` is intentionally expression-only: imports, attribute access, calls and
  arbitrary `exec` are blocked. Keep `OWNER_IDS` tightly controlled.
- Never commit `.env`, database files or bot tokens. See `.env.example`.
