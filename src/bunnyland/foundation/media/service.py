"""Safe, namespaced storage for server-generated and plugin-provided media."""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

ALLOWED_EXTENSIONS = frozenset({"png", "jpg", "webp", "mp4", "webm", "glb"})
_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "glb": "model/gltf-binary",
}
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
    stem, dot, extension = name.partition(".")
    if not dot or not _SEGMENT.fullmatch(stem) or "." in extension:
        raise MediaError(f"invalid media filename {name!r}")
    _check_extension(extension)
    return stem, extension


class MediaService:
    """Read and write immutable media beneath a fixed root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def new_name(self, extension: str) -> str:
        _check_extension(extension)
        return f"{uuid4().hex}.{extension}"

    def content_name(self, data: bytes, extension: str) -> str:
        """Return the stable filename used for immutable, content-addressed assets."""
        _check_extension(extension)
        return f"{sha256(data).hexdigest()}.{extension}"

    def path_for(self, namespace: str, name: str) -> Path:
        _check_segment(namespace)
        _check_name(name)
        return self.root / namespace / name

    def write(self, namespace: str, name: str, data: bytes) -> Path:
        path = self.path_for(namespace, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def put_content(self, namespace: str, data: bytes, extension: str) -> tuple[str, Path]:
        name = self.content_name(data, extension)
        path = self.path_for(namespace, name)
        if not path.exists():
            self.write(namespace, name, data)
        return name, path

    def read(self, namespace: str, name: str) -> bytes:
        path = self.path_for(namespace, name)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise MediaError(f"media not found: {namespace}/{name}") from exc

    def url_for(self, namespace: str, name: str) -> str:
        self.path_for(namespace, name)
        return f"/media/{namespace}/{name}"

    def public_url_for(self, namespace: str, name: str, *, base_url: str) -> str:
        relative = self.url_for(namespace, name)
        return relative if not base_url else f"{base_url.rstrip('/')}{relative}"


# Compatibility name retained for existing image generation consumers.
MediaStore = MediaService


def extension_for(name: str) -> str:
    return _check_name(name)[1]


def content_type_for(name: str) -> str:
    return _CONTENT_TYPES[extension_for(name)]


def require_media_service(actor) -> MediaService:
    service = getattr(actor, "media_service", None)
    if not isinstance(service, MediaService):
        raise RuntimeError("bunnyland.media is not installed")
    return service


__all__ = [
    "ALLOWED_EXTENSIONS",
    "MediaError",
    "MediaService",
    "MediaStore",
    "content_type_for",
    "extension_for",
    "require_media_service",
]
