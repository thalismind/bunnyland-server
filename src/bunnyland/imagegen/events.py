"""Domain events for image generation (spec 27).

These ride the normal event bus, so the server's admin world websocket
broadcasts them with no extra wiring: a client sees a completion event and refreshes the
affected entity or record to pick up the new image reference.
"""

from __future__ import annotations

from ..core.events import DomainEvent


class ImageGenerationStartedEvent(DomainEvent):
    """A generation job was queued for an entity or world-history record."""

    entity_id: str
    purpose: str
    generator: str = "comfyui"
    template: str = ""


class ImageGenerationCompletedEvent(DomainEvent):
    """A generation job finished and its image reference was attached."""

    entity_id: str
    purpose: str
    url: str
    alpha_url: str = ""
    generator: str = "comfyui"
    template: str = ""


class ImageGenerationFailedEvent(DomainEvent):
    """A generation job failed; nothing was attached."""

    entity_id: str
    purpose: str
    generator: str = "comfyui"
    reason: str


__all__ = [
    "ImageGenerationCompletedEvent",
    "ImageGenerationFailedEvent",
    "ImageGenerationStartedEvent",
]
