"""Admin actions exposed through the optional HTTP API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ..core.components import CharacterComponent, RoomComponent
from ..core.events import (
    WorldGenerationCompletedEvent,
    WorldGenerationFailedEvent,
    WorldGenerationStartedEvent,
)
from ..core.queue import CommandQueues
from ..core.world_actor import WorldActor
from ..persistence import WorldMeta, save_world
from ..plugins import apply_plugins
from ..worldgen import GenOptions, WorldGenerator
from .models import (
    WorldGenerateResponse,
    WorldGenerationStatusResponse,
    WorldSaveResponse,
)

if TYPE_CHECKING:
    from ..plugins.model import Plugin


def save_configured_world(
    actor: WorldActor, save_path: str | Path, *, meta: WorldMeta | None = None
) -> WorldSaveResponse:
    stamped = save_world(actor, save_path, meta=meta or WorldMeta())
    return WorldSaveResponse(
        path=str(save_path),
        world_epoch=actor.epoch,
        saved_at_epoch=stamped.saved_at_epoch,
        saved_at=stamped.saved_at.isoformat() if stamped.saved_at else None,
    )


@dataclass
class WorldGenerationJob:
    job_id: str
    seed: str
    generator: str
    task: asyncio.Task | None = None
    status: str = "running"
    rooms: int = 0
    characters: int = 0
    error: str | None = None
    saved: WorldSaveResponse | None = None

    def response(self, actor: WorldActor) -> WorldGenerateResponse:
        return WorldGenerateResponse(
            job_id=self.job_id,
            status=self.status,
            seed=self.seed,
            generator=self.generator,
            world_epoch=actor.epoch,
        )

    def status_response(self, actor: WorldActor) -> WorldGenerationStatusResponse:
        return WorldGenerationStatusResponse(
            job_id=self.job_id,
            status=self.status,
            seed=self.seed,
            generator=self.generator,
            world_epoch=actor.epoch,
            rooms=self.rooms,
            characters=self.characters,
            error=self.error,
            saved=self.saved,
        )


def idle_generation_status(actor: WorldActor) -> WorldGenerationStatusResponse:
    return WorldGenerationStatusResponse(world_epoch=actor.epoch)


def _count_world(actor: WorldActor) -> tuple[int, int]:
    rooms = len(list(actor.world.query().with_all([RoomComponent]).execute_entities()))
    characters = len(
        list(actor.world.query().with_all([CharacterComponent]).execute_entities())
    )
    return rooms, characters


async def _publish_generation_started(actor: WorldActor, job: WorldGenerationJob) -> None:
    await actor.bus.publish(
        WorldGenerationStartedEvent(
            event_id=uuid4().hex,
            world_epoch=actor.epoch,
            created_at=datetime.now(UTC),
            job_id=job.job_id,
            seed=job.seed,
            generator=job.generator,
        )
    )


async def _publish_generation_completed(actor: WorldActor, job: WorldGenerationJob) -> None:
    await actor.bus.publish(
        WorldGenerationCompletedEvent(
            event_id=uuid4().hex,
            world_epoch=actor.epoch,
            created_at=datetime.now(UTC),
            job_id=job.job_id,
            seed=job.seed,
            generator=job.generator,
            room_count=job.rooms,
            character_count=job.characters,
        )
    )


async def _publish_generation_failed(actor: WorldActor, job: WorldGenerationJob) -> None:
    await actor.bus.publish(
        WorldGenerationFailedEvent(
            event_id=uuid4().hex,
            world_epoch=actor.epoch,
            created_at=datetime.now(UTC),
            job_id=job.job_id,
            seed=job.seed,
            generator=job.generator,
            error=job.error or "unknown generation error",
        )
    )


async def start_world_generation(
    actor: WorldActor,
    *,
    plugins: list[Plugin],
    generator: WorldGenerator,
    seed: str,
    options: GenOptions,
    meta: WorldMeta,
    save_path: str | Path | None = None,
    save: bool = False,
) -> WorldGenerationJob:
    """Clear the live world and schedule generation without blocking the API request."""

    if save and save_path is None:
        raise RuntimeError("server was not started with --save")

    job = WorldGenerationJob(job_id=uuid4().hex, seed=seed, generator=generator.name)
    replacement = WorldActor()
    applied_plugins = apply_plugins(plugins, replacement)

    async with actor._lock:
        actor.world = replacement.world
        actor.bind_clock()
        actor.queues = CommandQueues()
        actor._inbox = asyncio.Queue()

        meta.seed = seed
        meta.generator = generator.name
        meta.prompt = ""
        meta.plugins = tuple(plugin.id for plugin in applied_plugins)
        meta.saved_at_epoch = 0
        meta.saved_at = None

    await _publish_generation_started(actor, job)
    await asyncio.sleep(0)

    async def run() -> None:
        try:
            result = await generator.generate(actor, seed, options)
            async with actor._lock:
                job.rooms, job.characters = _count_world(actor)
                meta.prompt = result.prompt
                if save:
                    job.saved = save_configured_world(actor, save_path, meta=meta)
            job.status = "succeeded"
            await _publish_generation_completed(actor, job)
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            await _publish_generation_failed(actor, job)

    job.task = asyncio.create_task(run(), name=f"worldgen-{job.job_id}")
    return job


async def generate_replacement_world(
    actor: WorldActor,
    *,
    plugins: list[Plugin],
    generator: WorldGenerator,
    seed: str,
    options: GenOptions,
    meta: WorldMeta,
    save_path: str | Path | None = None,
    save: bool = False,
) -> WorldGenerateResponse:
    """Generate a fresh world and atomically replace the live ECS state."""

    replacement = WorldActor()
    applied_plugins = apply_plugins(plugins, replacement)
    result = await generator.generate(replacement, seed, options)

    async with actor._lock:
        actor.world = replacement.world
        actor.bind_clock()
        actor.queues = CommandQueues()
        actor._inbox = asyncio.Queue()

        meta.seed = seed
        meta.generator = generator.name
        meta.prompt = result.prompt
        meta.plugins = tuple(plugin.id for plugin in applied_plugins)
        meta.saved_at_epoch = 0
        meta.saved_at = None

        if save:
            if save_path is None:
                raise RuntimeError("server was not started with --save")
            save_configured_world(actor, save_path, meta=meta)

        return WorldGenerateResponse(
            job_id=uuid4().hex,
            status="succeeded",
            world_epoch=actor.epoch,
            seed=seed,
            generator=generator.name,
        )


__all__ = [
    "WorldGenerationJob",
    "generate_replacement_world",
    "idle_generation_status",
    "save_configured_world",
    "start_world_generation",
]
