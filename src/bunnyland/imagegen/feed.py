"""Pull image-generation results out of the recent-events feed (spec 27).

Image generation completes asynchronously and announces itself with an
``ImageGenerationCompletedEvent`` (or ``...FailedEvent``) on the event bus. Those events
ride at ``SYSTEM`` visibility and carry no ``actor_id``, so the per-player perception
filter in ``EventNarrator`` deliberately drops them. Clients that want to surface "your
scene image is ready" therefore read the raw ``/world/events/recent`` feed and look for the
completion directly — exactly what the web clients' ``latestImageCompletion`` JS helper
does. These functions are the Python equivalent shared by the TUI and REPL.

Each ``message`` is a serialized event: either ``{"event_type": ..., "event": {...}}`` (the
shape returned by ``recent_events()``) or the websocket wrapper ``{"type": "event",
"data": {...}}``. Both are accepted.
"""

from __future__ import annotations

from typing import Any

from .events import ImageGenerationCompletedEvent, ImageGenerationFailedEvent

_COMPLETED = ImageGenerationCompletedEvent.__name__
_FAILED = ImageGenerationFailedEvent.__name__


def _newest(
    messages: list[dict] | None,
    *,
    event_type: str,
    purpose: str,
    require_url: bool,
) -> dict[str, Any] | None:
    """Return the newest matching event payload by ``world_epoch``, or ``None``."""

    best: dict[str, Any] | None = None
    best_epoch = -1
    for message in messages or []:
        data = message.get("data", message)
        if data.get("event_type") != event_type:
            continue
        event = data.get("event") or {}
        if require_url and not event.get("url"):
            continue
        if purpose and event.get("purpose") != purpose:
            continue
        epoch = int(event.get("world_epoch") or 0)
        if best is None or epoch >= best_epoch:
            best = event
            best_epoch = epoch
    return best


def latest_image_completion(
    messages: list[dict] | None, *, purpose: str = "event"
) -> dict[str, Any] | None:
    """Newest ``ImageGenerationCompletedEvent`` payload for ``purpose`` (empty = any)."""

    return _newest(messages, event_type=_COMPLETED, purpose=purpose, require_url=True)


def latest_image_failure(
    messages: list[dict] | None, *, purpose: str = "event"
) -> dict[str, Any] | None:
    """Newest ``ImageGenerationFailedEvent`` payload for ``purpose`` (empty = any)."""

    return _newest(messages, event_type=_FAILED, purpose=purpose, require_url=False)


__all__ = ["latest_image_completion", "latest_image_failure"]
