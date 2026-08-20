from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from bot.database import Database

log = logging.getLogger(__name__)
Handler = Callable[[dict[str, Any]], Awaitable[None]]


class PersistentScheduler:
    """A small, restart-safe task runner backed by the database.

    Handlers are registered by cogs. A claimed task is retried after its short
    database lease expires if a worker died before completion; handlers should
    therefore be idempotent.
    """
    def __init__(self, db: Database) -> None:
        self.db = db
        self.handlers: dict[str, Handler] = {}
        self._runner: asyncio.Task[None] | None = None

    def register(self, task_type: str, handler: Handler) -> None:
        self.handlers[task_type] = handler

    async def _tick(self) -> None:
        for task in await self.db.due_tasks():
            handler = self.handlers.get(task["task_type"])
            if not handler:
                log.warning("No handler registered for scheduled task %s", task["task_type"])
                await self.db.complete_task(task["id"])
                continue
            try:
                await handler(task["payload"])
            except Exception:
                log.exception("Scheduled task %s failed; it will be retried after its lease expires", task["id"])
                continue
            await self.db.complete_task(task["id"])

    async def _run(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Scheduler tick failed")
            await asyncio.sleep(15)

    def start(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run(), name="aegis-scheduler")

    async def stop(self) -> None:
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
            self._runner = None
