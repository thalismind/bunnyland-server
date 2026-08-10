"""Provider-neutral image generator contracts and plugin collection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, JsonValue

from ..plugins.model import Plugin
from .spec import ImagePurpose, MediaKind, PromptStyle


class ImageGeneratorProfile(BaseModel):
    """One named set of prompt and output settings supported by a generator."""

    name: str
    purpose: ImagePurpose
    prompt_style: PromptStyle = PromptStyle.NATURAL
    media: MediaKind = MediaKind.IMAGE
    default_negative: str = ""
    width: int = 1024
    height: int = 1024


class ImageGeneratorRequest(BaseModel):
    """Provider-neutral input passed to an image generator."""

    purpose: ImagePurpose
    prompt: str
    negative: str = ""
    seed: int
    width: int
    height: int
    profile_name: str


class VideoGeneratorProfile(BaseModel):
    """One named set of prompt and output settings supported by a video generator."""

    name: str
    prompt_style: PromptStyle = PromptStyle.NATURAL
    default_negative: str = ""
    width: int = 1024
    height: int = 576


class VideoGeneratorRequest(BaseModel):
    """Provider-neutral input passed to a video generator."""

    prompt: str
    negative: str = ""
    seed: int
    width: int
    height: int
    profile_name: str


@runtime_checkable
class ImageGenerator(Protocol):
    """Async provider contract. Implementations return one PNG image."""

    name: str

    def resolve_profile(
        self, purpose: ImagePurpose, profile_name: str = ""
    ) -> ImageGeneratorProfile: ...

    async def generate(self, request: ImageGeneratorRequest) -> bytes: ...


@runtime_checkable
class ImageGeneratorFactory(Protocol):
    """Plugin factory for a named image generator."""

    name: str

    def __call__(self, config: object, plugin_config: JsonValue | None) -> ImageGenerator: ...


@runtime_checkable
class VideoGenerator(Protocol):
    """Async provider contract. Implementations return one encoded video."""

    name: str

    def resolve_video_profile(self, profile_name: str = "") -> VideoGeneratorProfile: ...

    async def generate_video(self, request: VideoGeneratorRequest) -> bytes: ...


@runtime_checkable
class VideoGeneratorFactory(Protocol):
    """Plugin factory for a named video generator."""

    name: str

    def __call__(self, config: object, plugin_config: JsonValue | None) -> VideoGenerator: ...


def collect_image_generators(
    plugins: Sequence[Plugin],
    config: object,
    plugin_config: Mapping[str, JsonValue] | None = None,
) -> dict[str, ImageGenerator]:
    """Instantiate plugin generators with global and validated owner configuration.

    Duplicate names are rejected even when that generator is not selected, so registration
    mistakes fail deterministically during startup.
    """

    validated = plugin_config or {}
    generators: dict[str, ImageGenerator] = {}
    for plugin in plugins:
        owner_config = validated.get(plugin.id)
        for factory in plugin.content.image_generators:
            name = str(getattr(factory, "name", "")).strip()
            if not name:
                raise ValueError(f"image generator factory from {plugin.id!r} has no name")
            if name in generators:
                raise ValueError(f"duplicate image generator {name!r}")
            create = getattr(factory, "create", None)
            generator = (
                create(config, owner_config) if callable(create) else factory(config, owner_config)
            )
            if not isinstance(generator, ImageGenerator):
                raise TypeError(f"image generator factory {name!r} returned an invalid generator")
            if generator.name != name:
                raise ValueError(
                    f"image generator factory {name!r} returned generator {generator.name!r}"
                )
            generators[name] = generator
    return generators


def collect_video_generators(
    plugins: Sequence[Plugin],
    config: object,
    plugin_config: Mapping[str, JsonValue] | None = None,
) -> dict[str, VideoGenerator]:
    """Instantiate and validate plugin-contributed video generators."""

    validated = plugin_config or {}
    generators: dict[str, VideoGenerator] = {}
    for plugin in plugins:
        owner_config = validated.get(plugin.id)
        for factory in plugin.content.video_generators:
            name = str(getattr(factory, "name", "")).strip()
            if not name:
                raise ValueError(f"video generator factory from {plugin.id!r} has no name")
            if name in generators:
                raise ValueError(f"duplicate video generator {name!r}")
            create = getattr(factory, "create", None)
            generator = (
                create(config, owner_config) if callable(create) else factory(config, owner_config)
            )
            if not isinstance(generator, VideoGenerator):
                raise TypeError(f"video generator factory {name!r} returned an invalid generator")
            if generator.name != name:
                raise ValueError(
                    f"video generator factory {name!r} returned generator {generator.name!r}"
                )
            generators[name] = generator
    return generators


__all__ = [
    "ImageGenerator",
    "ImageGeneratorFactory",
    "ImageGeneratorProfile",
    "ImageGeneratorRequest",
    "collect_image_generators",
    "VideoGenerator",
    "VideoGeneratorFactory",
    "VideoGeneratorProfile",
    "VideoGeneratorRequest",
    "collect_video_generators",
]
