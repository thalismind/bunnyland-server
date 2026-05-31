"""Admin actions exposed through the optional HTTP API."""

from __future__ import annotations

from pathlib import Path

from ..core.world_actor import WorldActor
from ..persistence import WorldMeta, save_world
from .models import WorldSaveResponse


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


__all__ = ["save_configured_world"]
