"""Admin actions exposed through the optional HTTP API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.components import CharacterComponent, RoomComponent
from ..core.queue import CommandQueues
from ..core.world_actor import WorldActor
from ..persistence import WorldMeta, save_world
from ..plugins import apply_plugins
from ..worldgen import GenOptions, WorldGenerator
from .models import (
    WorldGenerateResponse,
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

        saved = None
        if save:
            if save_path is None:
                raise RuntimeError("server was not started with --save")
            saved = save_configured_world(actor, save_path, meta=meta)

        rooms = len(list(actor.world.query().with_all([RoomComponent]).execute_entities()))
        characters = len(
            list(actor.world.query().with_all([CharacterComponent]).execute_entities())
        )
        return WorldGenerateResponse(
            world_epoch=actor.epoch,
            seed=seed,
            generator=generator.name,
            rooms=rooms,
            characters=characters,
            saved=saved,
        )


__all__ = ["generate_replacement_world", "save_configured_world"]
