"""Throttled producer for missing portrait and sprite image jobs."""

from __future__ import annotations

import asyncio
import contextlib

from ..core.components import CharacterComponent
from ..core.world_actor import WorldActor
from ..simpacks.toonsim.mechanics import SpriteImageComponent
from .components import ImageRequestComponent, PortraitImageComponent
from .service import ImageGenJob, ImageGenService
from .spec import ImagePurpose


class ImageBackfillScheduler:
    """Finds missing images at a configured cadence and submits normal image jobs."""

    def __init__(
        self, actor: WorldActor, service: ImageGenService, interval_seconds: float
    ) -> None:
        self._actor = actor
        self._service = service
        self._interval_seconds = interval_seconds
        self._failed: set[str] = set()
        self._pending: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="imagegen-backfill")

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def enqueue_one_missing(self) -> ImageGenJob | None:
        self._reconcile()
        if not self._service.idle or self._pending:
            return None
        async with self._actor._lock:
            target = _first_missing_portrait(self._actor, self._failed) or _first_missing_sprite(
                self._actor, self._failed
            )
        if target is None:
            return None
        entity_id, purpose = target
        job = await self._service.start(entity_id, purpose)
        if job.status == "queued":
            self._pending[job.job_id] = entity_id
        elif job.status == "failed":
            self._failed.add(entity_id)
        return job

    def _reconcile(self) -> None:
        for job_id, entity_id in tuple(self._pending.items()):
            job = self._service.job(job_id)
            if job is None or job.status in {"queued", "running"}:
                continue
            if job.status == "failed":
                self._failed.add(entity_id)
            else:
                self._failed.discard(entity_id)
            del self._pending[job_id]

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self.enqueue_one_missing()


def _first_missing_portrait(
    actor: WorldActor, skip: set[str]
) -> tuple[str, ImagePurpose] | None:
    for entity in (
        actor.world.query()
        .with_all([CharacterComponent])
        .with_none([PortraitImageComponent, ImageRequestComponent])
        .execute_entities()
    ):
        if str(entity.id) not in skip:
            return (str(entity.id), ImagePurpose.PORTRAIT)
    return None


def _first_missing_sprite(
    actor: WorldActor, skip: set[str]
) -> tuple[str, ImagePurpose] | None:
    for entity in (
        actor.world.query()
        .with_all([CharacterComponent, SpriteImageComponent])
        .with_none([ImageRequestComponent])
        .execute_entities()
    ):
        if str(entity.id) not in skip and not entity.get_component(SpriteImageComponent).url:
            return (str(entity.id), ImagePurpose.SPRITE)
    return None


__all__ = ["ImageBackfillScheduler"]
