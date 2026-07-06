"""ECS components that reference generated images (spec 27).

These hold only small reference URLs (never image bytes), updated with ``replace_component``
like every other frozen component. A character can carry both a portrait and, when
toonsim is enabled, a sprite (which reuses toonsim's ``SpriteImageComponent``);
world-history record entities carry an :class:`EventImageComponent`.
:class:`ImageRequestComponent` is a transient marker placed
while a job is in flight so the backfill scan and per-event dedup can see it.
"""

from __future__ import annotations

from pydantic.dataclasses import dataclass as pydantic_dataclass
from relics import Component


@pydantic_dataclass(frozen=True)
class PortraitImageComponent(Component):
    """A character's (or single entity's) generated portrait."""

    url: str = ""
    alpha_url: str = ""
    prompt: str = ""
    seed: int = 0
    template: str = ""
    generated_at_epoch: int = 0


@pydantic_dataclass(frozen=True)
class EventImageComponent(Component):
    """A generated scene image attached to a world-history record entity."""

    url: str = ""
    alpha_url: str = ""
    prompt: str = ""
    seed: int = 0
    template: str = ""
    source_event_id: str = ""
    generated_at_epoch: int = 0


@pydantic_dataclass(frozen=True)
class ImageRequestComponent(Component):
    """Marks an entity/record with an image generation request in flight."""

    purpose: str = ""
    requested_at_epoch: int = 0
    requested_by: str = ""


__all__ = [
    "EventImageComponent",
    "ImageRequestComponent",
    "PortraitImageComponent",
]
