"""Tests for pulling image results out of the recent-events feed."""

from __future__ import annotations

from bunnyland.imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
)
from bunnyland.imagegen.feed import latest_image_completion, latest_image_failure
from bunnyland.server.serialization import serialize_event


def _completed(
    *, epoch: int, url: str = "/public/media/events/a.png", purpose: str = "event"
) -> dict:
    return serialize_event(
        ImageGenerationCompletedEvent(
            event_id=f"e{epoch}",
            world_epoch=epoch,
            created_at="2026-01-01T00:00:00Z",
            entity_id="char-1",
            purpose=purpose,
            url=url,
        )
    )


def _failed(*, epoch: int, purpose: str = "event") -> dict:
    return serialize_event(
        ImageGenerationFailedEvent(
            event_id=f"f{epoch}",
            world_epoch=epoch,
            created_at="2026-01-01T00:00:00Z",
            entity_id="char-1",
            purpose=purpose,
            reason="comfyui exploded",
        )
    )


def test_no_messages_returns_none():
    assert latest_image_completion([]) is None
    assert latest_image_completion(None) is None
    assert latest_image_failure([]) is None


def test_completion_extracted_and_newest_by_epoch():
    messages = [
        _completed(epoch=3, url="/public/media/events/old.png"),
        _completed(epoch=7, url="/public/media/events/new.png"),
    ]
    result = latest_image_completion(messages)
    assert result is not None
    assert result["url"] == "/public/media/events/new.png"
    assert result["world_epoch"] == 7


def test_out_of_order_keeps_highest_epoch():
    # A later message with a lower epoch must not replace the newest.
    messages = [
        _completed(epoch=7, url="/public/media/events/new.png"),
        _completed(epoch=3, url="/public/media/events/old.png"),
    ]
    result = latest_image_completion(messages)
    assert result is not None
    assert result["url"] == "/public/media/events/new.png"


def test_websocket_wrapper_shape_is_accepted():
    wrapped = {"type": "event", "data": _completed(epoch=5)}
    result = latest_image_completion([wrapped])
    assert result is not None
    assert result["world_epoch"] == 5


def test_purpose_filter_excludes_other_purposes():
    messages = [_completed(epoch=9, purpose="portrait")]
    assert latest_image_completion(messages, purpose="event") is None
    assert latest_image_completion(messages, purpose="portrait")["world_epoch"] == 9
    # An empty purpose matches anything.
    assert latest_image_completion(messages, purpose="")["world_epoch"] == 9


def test_completion_without_url_is_ignored():
    no_url = _completed(epoch=4)
    no_url["event"]["url"] = ""
    assert latest_image_completion([no_url]) is None


def test_failed_events_are_not_treated_as_completions():
    assert latest_image_completion([_failed(epoch=2)]) is None


def test_failure_extracted_newest_and_needs_no_url():
    messages = [_failed(epoch=1), _failed(epoch=6)]
    result = latest_image_failure(messages)
    assert result is not None
    assert result["world_epoch"] == 6
    assert result["reason"] == "comfyui exploded"


def test_failure_purpose_filter():
    messages = [_failed(epoch=8, purpose="portrait")]
    assert latest_image_failure(messages, purpose="event") is None
    assert latest_image_failure(messages, purpose="portrait")["world_epoch"] == 8
