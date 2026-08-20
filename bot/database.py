"""Async SQLite persistence used by all cogs.

The class deliberately exposes small domain helpers instead of leaking SQL into
commands. SQLite is run in WAL mode and every write is committed atomically.
"""
from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

log = logging.getLogger(__name__)

DEFAULT_GUILD_SETTINGS: dict[str, Any] = {
    "log_channels": {},
    "welcome": {"channel_id": None, "message": "Welcome {user} to {server}!"},
    "leave": {"channel_id": None, "message": "{user} has left {server}."},
    "autorole_id": None,
    "suggestions_channel_id": None,
    "ticket": {"category_id": None, "support_role_id": None, "message_id": None},
    "leveling": {"enabled": True, "channel_id": None, "xp_min": 8, "xp_max": 15},
    "automod": {"enabled": False, "banned_words": [], "max_mentions": 5, "max_caps": 0.8},
    "dj_role_id": None,
    "counting_channel_id": None,
    "modules": {
        "moderation": True,
        "automod": True,
        "logging": True,
        "tickets": True,
        "giveaways": True,
        "leveling": True,
        "economy": True,
        "fun": True,
        "music": True,
        "utility": True,
        "protection": True,
        "engagement": True,
        "voice": True,
        "onboarding": True,
    },
    "starboard": {"channel_id": None, "threshold": 3, "emoji": "⭐"},
    "join_to_create_channel_id": None,
    "lockdown": False,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class Database:
    def __init__(self, url: str, schema_path: str | Path | None = None) -> None:
        if not url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// DATABASE_URL values are supported by this adapter")
        raw = url.removeprefix("sqlite:///")
        self.path = Path("/") / raw if raw.startswith("/") else Path(raw)
        self.schema_path = Path(schema_path or Path(__file__).resolve().parent.parent / "migrations/001_initial.sql")
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.conn:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(self.schema_path.read_text(encoding="utf-8"))
        # A process may have died after claiming a task. Claims are leases, not
        # permanent locks, so old work is eligible again after a short grace period.
        await self.conn.execute(
            "UPDATE scheduled_tasks SET claimed_at=NULL WHERE completed_at IS NULL AND claimed_at IS NOT NULL AND claimed_at < ?",
            (iso(utcnow() - timedelta(minutes=1)),),
        )
        await self.conn.commit()
        log.info("Database ready at %s", self.path)

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    def _require(self) -> aiosqlite.Connection:
        if not self.conn:
            raise RuntimeError("Database is not connected")
        return self.conn

    async def execute(self, sql: str, parameters: Iterable[Any] = ()) -> int:
        conn = self._require()
        cursor = await conn.execute(sql, tuple(parameters))
        await conn.commit()
        return cursor.lastrowid or cursor.rowcount

    async def fetchone(self, sql: str, parameters: Iterable[Any] = ()) -> dict[str, Any] | None:
        cursor = await self._require().execute(sql, tuple(parameters))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
        cursor = await self._require().execute(sql, tuple(parameters))
        return [dict(row) for row in await cursor.fetchall()]

    async def get_guild(self, guild_id: int) -> dict[str, Any]:
        row = await self.fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        if row:
            stored = json.loads(row.pop("settings_json") or "{}")
            defaults = copy.deepcopy(DEFAULT_GUILD_SETTINGS)
            for key, value in stored.items():
                if isinstance(value, dict) and isinstance(defaults.get(key), dict):
                    defaults[key].update(value)
                else:
                    defaults[key] = value
            row["settings"] = defaults
            return row
        await self.execute(
            "INSERT INTO guild_settings (guild_id, settings_json, updated_at) VALUES (?, ?, ?)",
            (guild_id, json.dumps(DEFAULT_GUILD_SETTINGS, ensure_ascii=False), iso()),
        )
        return await self.get_guild(guild_id)  # type: ignore[return-value]

    async def setting(self, guild_id: int, key: str, default: Any = None) -> Any:
        row = await self.get_guild(guild_id)
        if key in row:
            return row[key]
        value = row["settings"]
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    async def set_settings(self, guild_id: int, **values: Any) -> None:
        row = await self.get_guild(guild_id)
        settings = row["settings"]
        columns: dict[str, Any] = {}
        for key, value in values.items():
            if key in {"prefix", "language"}:
                columns[key] = value
                continue
            target = settings
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        assignments = ["settings_json = ?", "updated_at = ?"]
        params: list[Any] = [json.dumps(settings, ensure_ascii=False), iso()]
        for key, value in columns.items():
            assignments.append(f"{key} = ?")
            params.append(value)
        params.append(guild_id)
        await self.execute(f"UPDATE guild_settings SET {', '.join(assignments)} WHERE guild_id = ?", params)

    async def add_case(self, guild_id: int, user_id: int, moderator_id: int, action: str,
                       reason: str, duration_seconds: int | None = None) -> int:
        return await self.execute(
            "INSERT INTO moderation_cases (guild_id,user_id,moderator_id,action,reason,duration_seconds,created_at) VALUES (?,?,?,?,?,?,?)",
            (guild_id, user_id, moderator_id, action, reason, duration_seconds, iso()),
        )

    async def cases(self, guild_id: int, user_id: int, limit: int = 25) -> list[dict[str, Any]]:
        return await self.fetchall(
            "SELECT * FROM moderation_cases WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (guild_id, user_id, limit),
        )

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        return await self.execute(
            "INSERT INTO warnings (guild_id,user_id,moderator_id,reason,created_at) VALUES (?,?,?,?,?)",
            (guild_id, user_id, moderator_id, reason, iso()),
        )

    async def warnings(self, guild_id: int, user_id: int, active_only: bool = True) -> list[dict[str, Any]]:
        suffix = " AND active=1" if active_only else ""
        return await self.fetchall(
            f"SELECT * FROM warnings WHERE guild_id=? AND user_id=?{suffix} ORDER BY id DESC",
            (guild_id, user_id),
        )

    async def schedule(self, task_type: str, run_at: datetime, payload: dict[str, Any]) -> int:
        return await self.execute(
            "INSERT INTO scheduled_tasks (task_type,run_at,payload_json) VALUES (?,?,?)",
            (task_type, iso(run_at), json.dumps(payload)),
        )

    async def due_tasks(self, now: datetime | None = None) -> list[dict[str, Any]]:
        # Claim rows in one transaction so multiple shards/processes do not execute a task twice.
        conn = self._require()
        await conn.execute("BEGIN IMMEDIATE")
        current = now or utcnow()
        lease_cutoff = iso(current - timedelta(minutes=1))
        cursor = await conn.execute(
            "SELECT * FROM scheduled_tasks WHERE completed_at IS NULL AND (claimed_at IS NULL OR claimed_at <= ?) AND run_at <= ? LIMIT 50",
            (lease_cutoff, iso(current)),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        if rows:
            ids = [row["id"] for row in rows]
            await conn.executemany("UPDATE scheduled_tasks SET claimed_at=? WHERE id=?", [(iso(), i) for i in ids])
        await conn.commit()
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    async def complete_task(self, task_id: int) -> None:
        await self.execute("UPDATE scheduled_tasks SET completed_at=? WHERE id=?", (iso(), task_id))

    async def upsert_user(self, guild_id: int, user_id: int) -> dict[str, Any]:
        await self.execute("INSERT OR IGNORE INTO users (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
        return (await self.fetchone("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))) or {}

    async def update_user(self, guild_id: int, user_id: int, **values: Any) -> None:
        await self.upsert_user(guild_id, user_id)
        if not values:
            return
        fields = ", ".join(f"{key}=?" for key in values)
        await self.execute(f"UPDATE users SET {fields} WHERE guild_id=? AND user_id=?", (*values.values(), guild_id, user_id))

    async def create_reminder(self, guild_id: int | None, user_id: int, channel_id: int | None,
                              message: str, run_at: datetime) -> int:
        reminder_id = await self.execute(
            "INSERT INTO reminders (guild_id,user_id,channel_id,message,run_at) VALUES (?,?,?,?,?)",
            (guild_id, user_id, channel_id, message, iso(run_at)),
        )
        await self.schedule("reminder", run_at, {"reminder_id": reminder_id})
        return reminder_id

    async def close_reminder(self, reminder_id: int) -> dict[str, Any] | None:
        row = await self.fetchone("SELECT * FROM reminders WHERE id=? AND delivered_at IS NULL", (reminder_id,))
        if row:
            await self.execute("UPDATE reminders SET delivered_at=? WHERE id=?", (iso(), reminder_id))
        return row
