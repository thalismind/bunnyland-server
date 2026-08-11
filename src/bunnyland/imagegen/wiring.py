"""Build independent image and video services with shared media-provider resources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from ..core.world_actor import WorldActor
from ..plugins.loader import collect_prompt_enhancers
from ..plugins.model import Plugin
from .backfill import ImageBackfillScheduler
from .client import build_comfy_client
from .comfyui import ComfyUIGenerator
from .config import MediaGenConfig
from .generators import (
    ImageGenerator,
    VideoGenerator,
    collect_image_generators,
    collect_video_generators,
)
from .in_memory import InMemoryImageGenerator
from .media import MediaStore
from .openrouter import OpenRouterImageGenerator
from .postprocess import remove_edge_background
from .prompt import (
    CatalogExampleSource,
    LLMPromptEnhancer,
    PromptEnhancer,
    StubPromptEnhancer,
)
from .service import ImageGenService
from .spec import ImagePurpose
from .store import WorkflowTemplateStore, default_comfy_templates
from .video_service import VideoGenService


@dataclass(frozen=True)
class MediaGenerationServices:
    """Configured generation services and their optional backfill producer."""

    media: MediaStore
    image: ImageGenService | None = None
    video: VideoGenService | None = None
    backfill: ImageBackfillScheduler | None = None


def select_enhancer(config: MediaGenConfig, plugins: Sequence[Plugin] = ()) -> PromptEnhancer:
    name = config.enhancer
    if name in ("", "stub"):
        return StubPromptEnhancer()
    if name == "llm":
        return LLMPromptEnhancer(
            model=config.model,
            host=config.host or None,
            api_key=config.api_key or None,
        )
    for enhancer in collect_prompt_enhancers(plugins):
        if getattr(enhancer, "name", "") == name:
            return enhancer
    raise ValueError(f"unknown media enhancer {name!r}")


def build_media_services(
    actor: WorldActor,
    config: MediaGenConfig,
    *,
    plugins: Sequence[Plugin] = (),
    plugin_config: Mapping[str, JsonValue] | None = None,
) -> MediaGenerationServices:
    """Assemble independently selected image and video services."""

    image_names = {
        config.image.generator_for(purpose.value)
        for purpose in ImagePurpose
        if config.image.generator_for(purpose.value)
    }
    if image_names and any(
        not config.image.generator_for(purpose.value) for purpose in ImagePurpose
    ):
        raise ValueError("image generation requires a generator for every image purpose")
    video_name = config.video.generator.strip()

    image_registry: dict[str, ImageGenerator] = (
        collect_image_generators(plugins, config, plugin_config) if image_names else {}
    )
    video_registry: dict[str, VideoGenerator] = (
        collect_video_generators(plugins, config, plugin_config) if video_name else {}
    )
    for builtin in ("comfyui", "in-memory", "openrouter"):
        if builtin in image_registry:
            raise ValueError(f"duplicate image generator {builtin!r}")
    if "comfyui" in video_registry:
        raise ValueError("duplicate video generator 'comfyui'")

    if "comfyui" in image_names or video_name == "comfyui":
        if not config.comfyui.server_url:
            raise ValueError("comfyui generation requires COMFYUI_SERVER_URL")
        templates = WorkflowTemplateStore(
            config.comfyui.templates_path or None,
            defaults=default_comfy_templates(config.comfyui.workflows),
        )
        templates.load()
        comfy = ComfyUIGenerator(build_comfy_client(config.comfyui), templates)
        image_registry["comfyui"] = comfy
        video_registry["comfyui"] = comfy
    if "in-memory" in image_names:
        image_registry["in-memory"] = InMemoryImageGenerator()
    if "openrouter" in image_names:
        image_registry["openrouter"] = OpenRouterImageGenerator(
            model=config.image.openrouter_image_model,
            api_key=config.image.openrouter_api_key,
            server_url=config.image.openrouter_server_url,
        )

    unknown_images = sorted(image_names - image_registry.keys())
    if unknown_images:
        raise ValueError(f"unknown image generator {unknown_images[0]!r}")
    if video_name and video_name not in video_registry:
        raise ValueError(f"unknown video generator {video_name!r}")

    media = MediaStore(config.media_root)
    actor.media_service = media
    enhancer = select_enhancer(config, plugins)
    examples = CatalogExampleSource()
    image = None
    backfill = None
    if image_names:
        image = ImageGenService(
            actor,
            config,
            generators={
                purpose: image_registry[config.image.generator_for(purpose.value)]
                for purpose in ImagePurpose
            },
            enhancer=enhancer,
            examples=examples,
            media=media,
            alpha=remove_edge_background,
        )
        backfill = ImageBackfillScheduler(
            actor, image, config.image.backfill_interval_seconds
        )
    video = None
    if video_name:
        video_registry[video_name].resolve_video_profile(config.video.profile)
        video = VideoGenService(
            actor,
            config,
            generator=video_registry[video_name],
            profile_name=config.video.profile,
            enhancer=enhancer,
            examples=examples,
            media=media,
        )
    return MediaGenerationServices(media=media, image=image, video=video, backfill=backfill)


__all__ = ["MediaGenerationServices", "build_media_services", "select_enhancer"]
