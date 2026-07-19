"""Tests for the path-safe media store and the image ECS components/events."""

from __future__ import annotations

import re

import pytest

from bunnyland.imagegen.components import (
    EventImageComponent,
    ImageRequestComponent,
    PortraitImageComponent,
)
from bunnyland.imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
)
from bunnyland.imagegen.media import (
    SEGMENT_PORTRAITS,
    MediaError,
    MediaStore,
    extension_for,
)

# --- media store: happy paths --------------------------------------------------------


def test_new_name_format(tmp_path):
    store = MediaStore(tmp_path)
    name = store.new_name("png")
    assert re.fullmatch(r"[a-z0-9]+\.png", name)
    # Two calls do not collide.
    assert store.new_name("png") != name


def test_write_read_roundtrip(tmp_path):
    store = MediaStore(tmp_path)
    name = store.new_name("png")
    path = store.write(SEGMENT_PORTRAITS, name, b"PNGDATA")
    assert path == tmp_path / SEGMENT_PORTRAITS / name
    assert store.read(SEGMENT_PORTRAITS, name) == b"PNGDATA"


def test_url_helpers(tmp_path):
    store = MediaStore(tmp_path)
    name = "abc123.png"
    assert store.url_for(SEGMENT_PORTRAITS, name) == "/v1/public/media/portraits/abc123.png"
    relative = store.public_url_for(SEGMENT_PORTRAITS, name, base_url="")
    assert relative == "/v1/public/media/portraits/abc123.png"
    absolute = store.public_url_for(SEGMENT_PORTRAITS, name, base_url="https://play.example/")
    assert absolute == "https://play.example/v1/public/media/portraits/abc123.png"


def test_extension_for():
    assert extension_for("abc123.webp") == "webp"


# --- media store: validation ---------------------------------------------------------


def test_new_name_rejects_bad_extension(tmp_path):
    with pytest.raises(MediaError, match="unsupported media extension"):
        MediaStore(tmp_path).new_name("exe")


@pytest.mark.parametrize(
    "segment",
    ["..", "por traits", "portraits/", "Portraits", "por.traits", ""],
)
def test_path_for_rejects_bad_segment(tmp_path, segment):
    with pytest.raises(MediaError, match="invalid media path segment"):
        MediaStore(tmp_path).path_for(segment, "abc.png")


@pytest.mark.parametrize(
    "name",
    ["..png", "a.b.png", "../etc.png", "noext", "a.", "a.PNG", "a/b.png"],
)
def test_path_for_rejects_bad_name(tmp_path, name):
    with pytest.raises(MediaError, match="invalid media filename|unsupported media extension"):
        MediaStore(tmp_path).path_for(SEGMENT_PORTRAITS, name)


def test_path_for_rejects_unsupported_extension(tmp_path):
    with pytest.raises(MediaError, match="unsupported media extension"):
        MediaStore(tmp_path).path_for(SEGMENT_PORTRAITS, "abc.gif")


def test_read_missing_raises(tmp_path):
    with pytest.raises(MediaError, match="media not found"):
        MediaStore(tmp_path).read(SEGMENT_PORTRAITS, "missing.png")


# --- components ----------------------------------------------------------------------


def test_portrait_component_defaults():
    component = PortraitImageComponent()
    assert component.url == ""
    assert component.alpha_url == ""
    assert component.seed == 0


def test_event_component_fields():
    component = EventImageComponent(url="/public/media/events/x.png", source_event_id="evt-1")
    assert component.source_event_id == "evt-1"


def test_request_component_fields():
    component = ImageRequestComponent(purpose="portrait", requested_by="char_1")
    assert component.purpose == "portrait"
    assert component.requested_by == "char_1"


# --- events --------------------------------------------------------------------------


def _base() -> dict:
    from datetime import UTC, datetime

    return {"event_id": "e1", "world_epoch": 0, "created_at": datetime.now(UTC)}


def test_events_construct():
    started = ImageGenerationStartedEvent(entity_id="char_1", purpose="portrait", **_base())
    assert started.entity_id == "char_1"
    completed = ImageGenerationCompletedEvent(
        entity_id="char_1", purpose="portrait", url="/public/media/portraits/x.png", **_base()
    )
    assert completed.url == "/public/media/portraits/x.png"
    failed = ImageGenerationFailedEvent(
        entity_id="char_1", purpose="portrait", reason="boom", **_base()
    )
    assert failed.reason == "boom"
