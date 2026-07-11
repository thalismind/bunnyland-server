"""Compatibility exports for the shared media foundation plugin."""

from ..foundation.media.service import (
    ALLOWED_EXTENSIONS,
    MediaError,
    MediaService,
    MediaStore,
    content_type_for,
    extension_for,
)

SEGMENT_PORTRAITS = "portraits"
SEGMENT_ENTITIES = "entities"
SEGMENT_SPRITES = "sprites"
SEGMENT_EVENTS = "events"
SEGMENT_ALPHA = "alpha"

__all__ = [
    "ALLOWED_EXTENSIONS",
    "SEGMENT_ALPHA",
    "SEGMENT_ENTITIES",
    "SEGMENT_EVENTS",
    "SEGMENT_PORTRAITS",
    "SEGMENT_SPRITES",
    "MediaError",
    "MediaService",
    "MediaStore",
    "content_type_for",
    "extension_for",
]
