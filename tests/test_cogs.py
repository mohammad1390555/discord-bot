from __future__ import annotations

from dataclasses import replace

import pytest
from discord import app_commands

from bot.config import Settings
from bot.core.bot import AegisBot
from bot.core.extensions import EXTENSIONS


def _walk(commands, prefix: str = "") -> list[str]:
    names: list[str] = []
    for command in commands:
        if isinstance(command, app_commands.Group):
            names.append(prefix + command.name)
            names.extend(_walk(command.commands, prefix + command.name + " "))
        else:
            names.append(prefix + command.name)
    return names


@pytest.mark.asyncio
async def test_all_extensions_load_under_command_limit(tmp_path) -> None:
    settings = replace(Settings.from_env(), database_url=f"sqlite:///{tmp_path}/bot.db", token="test")
    bot = AegisBot(settings)
    try:
        await bot.db.connect()
        for extension in EXTENSIONS:
            await bot.load_extension(extension)
        top_level = [command.name for command in bot.tree.get_commands()]
        assert len(top_level) == len(set(top_level)), sorted(n for n in top_level if top_level.count(n) > 1)
        assert len(top_level) <= 100
        for required in ("config", "owner", "giveaway", "ticket", "music", "tag", "panel", "help", "lockdown"):
            assert required in top_level
        assert top_level.count("lockdown") == 1
        names = _walk(bot.tree.get_commands())
        assert "config prefix" in names
        assert "giveaway create" in names
        assert "owner shutdown" in names
        assert "music play" in names
        assert "ticket close" in names
    finally:
        await bot.close()


def test_main_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "")
    from bot.config import Settings as SettingsCls

    empty = replace(Settings.from_env(), token="")
    monkeypatch.setattr("bot.__main__.settings", empty)
    from bot.__main__ import main

    with pytest.raises(SystemExit, match="DISCORD_TOKEN"):
        main()
