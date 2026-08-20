from __future__ import annotations

from datetime import timedelta

import pytest

from bot.database import Database, utcnow


@pytest.fixture
async def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path}/bot.db")
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_guild_defaults_and_settings(db: Database) -> None:
    row = await db.get_guild(42)
    assert row["prefix"] == "!"
    assert row["settings"]["leveling"]["enabled"] is True
    await db.set_settings(42, prefix="?", **{"welcome.channel_id": 99, "modules.fun": False})
    row = await db.get_guild(42)
    assert row["prefix"] == "?"
    assert row["settings"]["welcome"]["channel_id"] == 99
    assert row["settings"]["modules"]["fun"] is False
    assert row["settings"]["modules"]["music"] is True


@pytest.mark.asyncio
async def test_execute_insert_vs_update_rowcount(db: Database) -> None:
    warning_id = await db.add_warning(1, 2, 3, "test")
    assert warning_id >= 1
    changed = await db.execute("UPDATE warnings SET active=0 WHERE id=?", (warning_id,))
    assert changed == 1
    missing = await db.execute("UPDATE warnings SET active=0 WHERE id=?", (999999,))
    assert missing == 0


@pytest.mark.asyncio
async def test_user_currency_and_allowlist(db: Database) -> None:
    await db.upsert_user(1, 7)
    await db.update_user(1, 7, currency=50)
    user = await db.upsert_user(1, 7)
    assert user["currency"] == 50
    with pytest.raises(ValueError):
        await db.update_user(1, 7, not_a_column=1)


@pytest.mark.asyncio
async def test_scheduler_claims_once(db: Database) -> None:
    past = utcnow() - timedelta(seconds=5)
    task_id = await db.schedule("reminder", past, {"reminder_id": 1})
    first = await db.due_tasks()
    assert [row["id"] for row in first] == [task_id]
    second = await db.due_tasks()
    assert second == []
    await db.complete_task(task_id)
    third = await db.due_tasks()
    assert third == []


@pytest.mark.asyncio
async def test_reminder_roundtrip(db: Database) -> None:
    run_at = utcnow() - timedelta(seconds=1)
    reminder_id = await db.create_reminder(1, 2, 3, "hello", run_at)
    due = await db.due_tasks()
    assert due and due[0]["payload"]["reminder_id"] == reminder_id
    row = await db.close_reminder(reminder_id)
    assert row is not None
    assert await db.close_reminder(reminder_id) is None
