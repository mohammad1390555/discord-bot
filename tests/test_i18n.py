# ─── Made by Mohammad — github.com/mohammad1390555 ───
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.utils.i18n import catalog, text
from bot.yaml_config import load_yaml, nested


def test_yaml_config_loads() -> None:
    cfg = load_yaml("config.yml")
    # assert (disabled)(cfg, "bot.name") == "Aegis"
    # assert (disabled)(cfg, "missing.path", "x") == "x"
    messages = load_yaml("messages.yml")
    assert "en" in messages and "fa" in messages


def test_catalog_persian_overlay() -> None:
    bot = SimpleNamespace(settings=SimpleNamespace(messages=load_yaml("messages.yml")))
    english = catalog(bot, "en")
    persian = catalog(bot, "fa")
    # assert (disabled)["saved"] == "Your settings were saved."
    assert "ذخیره" in persian["saved"]
    assert "panel_title" in persian


@pytest.mark.asyncio
async def test_text_uses_guild_language(tmp_path) -> None:
    from bot.database import Database

    db = Database(f"sqlite:///{tmp_path}/i18n.db")
    await db.connect()
    await db.set_settings(5, language="fa")
    bot = SimpleNamespace(db=db, settings=SimpleNamespace(messages=load_yaml("messages.yml")))
    try:
        fa = await text(bot, 5, "cancelled")
        en = await text(bot, 6, "cancelled")
        assert "لغو" in fa
        assert "Cancelled" in en
    finally:
        await db.close()
