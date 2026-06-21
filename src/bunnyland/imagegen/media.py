"""On-disk media store for generated images (spec 27).

Generated image bytes live on disk; the ECS only ever stores a small reference URL. To keep
that safe, this store never accepts an uncontrolled path: filenames are server-generated
lowercase-alphanumeric tokens plus an allow-listed extension, and every path segment is
validated against the same strict pattern before it touches the filesystem. There is no way
to pass a ``.`` (so no ``..`` traversal) or a slash through these inputs -- two-segment paths
are taken as two separate, individually-validated arguments and joined here.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

#: Extensions we are willing to write/serve. Video extensions are reserved for the stub.
ALLOWED_EXTENSIONS = frozenset({"png", "jpg", "webp", "mp4", "webm"})

#: Server-chosen subdirectories (segments) for each kind of media.
SEGMENT_PORTRAITS = "portraits"
SEGMENT_ENTITIES = "entities"
SEGMENT_SPRITES = "sprites"
SEGMENT_EVENTS = "events"
SEGMENT_ALPHA = "alpha"

_SEGMENT = re.compile(r"^[a-z0-9]+$")


class MediaError(ValueError):
    """A media path or extension failed validation, or a file was missing."""


def _check_segment(segment: str) -> str:
    if not _SEGMENT.fullmatch(segment):
        raise MediaError(f"invalid media path segment {segment!r}")
    return segment


def _check_extension(extension: str) -> str:
    if extension not in ALLOWED_EXTENSIONS:
        raise MediaError(f"unsupported media extension {extension!r}")
    return extension


def _check_name(name: str) -> tuple[str, str]:
    """Split ``<token>.<ext>`` and validate both halves; reject anything else."""
    stem, dot, extension = name.partition(".")
    if not dot or not _SEGMENT.fullmatch(stem) or "." in extension:
        raise MediaError(f"invalid media filename {name!r}")
    _check_extension(extension)
    return stem, extension


class MediaStore:
    """Reads and writes generated media under a fixed root, with strict path validation."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def new_name(self, extension: str) -> str:
        """A fresh, collision-resistant ``<token>.<ext>`` filename (server-generated)."""
        _check_extension(extension)
        return f"{uuid4().hex}.{extension}"

    def path_for(self, segment: str, name: str) -> Path:
        """The validated absolute path for a media file (no traversal possible)."""
        _check_segment(segment)
        _check_name(name)
        return self.root / segment / name

    def write(self, segment: str, name: str, data: bytes) -> Path:
        """Write bytes to ``segment/name``, creating the directory as needed."""
        path = self.path_for(segment, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def read(self, segment: str, name: str) -> bytes:
        """Read the bytes at ``segment/name``; raises :class:`MediaError` when absent."""
        path = self.path_for(segment, name)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise MediaError(f"media not found: {segment}/{name}") from exc

    def url_for(self, segment: str, name: str) -> str:
        """The relative URL the web client uses to fetch this media."""
        self.path_for(segment, name)  # validate before handing out a URL
        return f"/media/{segment}/{name}"

    def public_url_for(self, segment: str, name: str, *, base_url: str) -> str:
        """An absolute URL (for Discord etc.), or the relative URL when no base is set."""
        relative = self.url_for(segment, name)
        if not base_url:
            return relative
        return f"{base_url.rstrip('/')}{relative}"


#: Content types for the extensions we serve.
_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
}


def extension_for(name: str) -> str:
    """Return the validated extension of a media filename."""
    return _check_name(name)[1]


def content_type_for(name: str) -> str:
    """Return the HTTP content type for a validated media filename."""
    return _CONTENT_TYPES[extension_for(name)]


__all__ = [
    "ALLOWED_EXTENSIONS",
    "SEGMENT_ALPHA",
    "SEGMENT_ENTITIES",
    "SEGMENT_EVENTS",
    "SEGMENT_PORTRAITS",
    "SEGMENT_SPRITES",
    "MediaError",
    "MediaStore",
    "content_type_for",
    "extension_for",
]
