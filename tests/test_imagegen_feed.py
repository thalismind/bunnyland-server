"""Tests for pulling image results out of the recent-events feed."""

from __future__ import annotations

from bunnyland.imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    VideoGenerationCompletedEvent,
    VideoGenerationFailedEvent,
)
from bunnyland.imagegen.feed import (
    latest_image_completion,
    latest_image_failure,
    latest_media_event_id,
    latest_video_completion,
    latest_video_failure,
)
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


def _video_event(*, epoch: int, failed: bool = False) -> dict:
    event_type = VideoGenerationFailedEvent if failed else VideoGenerationCompletedEvent
    fields = {"reason": "encoder failed"} if failed else {"url": f"/videos/{epoch}.mp4"}
    return serialize_event(
        event_type(
            event_id=f"v{epoch}",
            world_epoch=epoch,
            created_at="2026-01-01T00:00:00Z",
            entity_id="history-1",
            **fields,
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


def test_video_completion_and_failure_use_the_same_newest_event_rules():
    messages = [_video_event(epoch=2), _video_event(epoch=7), _video_event(epoch=9, failed=True)]
    assert latest_video_completion(messages)["url"] == "/videos/7.mp4"
    assert latest_video_failure(messages)["reason"] == "encoder failed"
    assert latest_video_completion([]) is None


def test_malformed_feed_entries_are_ignored():
    malformed = [
        {"data": "not-an-object"},
        {"event_type": "VideoGenerationCompletedEvent", "event": "not-an-object"},
        {"event_type": "VideoGenerationCompletedEvent", "event": {
            "purpose": "event", "url": "/video.mp4", "world_epoch": {},
        }},
    ]
    assert latest_video_completion(malformed)["world_epoch"] == {}


def test_latest_media_event_id_accepts_only_newest_public_or_room_event():
    messages = [
        {"data": "bad"},
        {"event_type": 7, "event": {}},
        {"event_type": "ImageGenerationCompletedEvent", "event": {
            "event_id": "media", "world_epoch": 20, "visibility": "room",
        }},
        {"event_type": "SpeechToldEvent", "event": {
            "event_id": "directed", "world_epoch": 10, "visibility": "directed",
        }},
        {"event_type": "SpeechSaidEvent", "event": "bad"},
        {"event_type": "SpeechSaidEvent", "event": {
            "event_id": 4, "world_epoch": 4, "visibility": "room",
        }},
        {"event_type": "SpeechSaidEvent", "event": {
            "event_id": "bad-epoch", "world_epoch": "5", "visibility": "room",
        }},
        {"event_type": "SpeechSaidEvent", "event": {
            "event_id": "new", "world_epoch": 7, "visibility": "room",
        }},
        {"type": "event", "data": {"event_type": "DoorOpenedEvent", "event": {
            "event_id": "old", "world_epoch": 3, "visibility": "public",
        }}},
    ]
    assert latest_media_event_id(messages) == "new"
    assert latest_media_event_id(None) == ""
