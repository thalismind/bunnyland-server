"""Provider-neutral image generator contracts and plugin collection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

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

    def __call__(self, config: Any, plugin_config: Any) -> ImageGenerator: ...


def collect_image_generators(
    plugins: Sequence[Plugin],
    config: Any,
    plugin_config: Mapping[str, Any] | None = None,
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


__all__ = [
    "ImageGenerator",
    "ImageGeneratorFactory",
    "ImageGeneratorProfile",
    "ImageGeneratorRequest",
    "collect_image_generators",
]
