"""Build a configured :class:`ImageGenService` from runtime config (spec 27).

The service depends on runtime settings (the ComfyUI URL, the media directory, the chosen
enhancer) that are only known at serve time, so it is assembled here rather than in a plugin.
The enhancer is resolved by name: the built-in ``stub``/``llm`` enhancers, or any enhancer a
plugin contributes via ``ContentContribution.prompt_enhancers``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from ..core.world_actor import WorldActor
from ..plugins.loader import collect_prompt_enhancers
from ..plugins.model import Plugin
from .client import build_comfy_client
from .comfyui import ComfyUIImageGenerator
from .config import ImageGenConfig
from .generators import ImageGenerator, collect_image_generators
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
from .spec import ImagePurpose, MediaKind
from .store import WorkflowTemplateStore, default_templates


def select_enhancer(config: ImageGenConfig, plugins: Sequence[Plugin] = ()) -> PromptEnhancer:
    """Resolve the configured enhancer by name (built-in or plugin-provided)."""
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
    raise ValueError(f"unknown image enhancer {name!r}")


def build_image_service(
    actor: WorldActor,
    config: ImageGenConfig,
    *,
    plugins: Sequence[Plugin] = (),
    plugin_config: Mapping[str, JsonValue] | None = None,
) -> ImageGenService:
    """Assemble the full image generation service from config and plugins."""
    selected_names = {config.generator_for(purpose.value) for purpose in ImagePurpose}
    if config.video_template:
        selected_names.add("comfyui")
    registry: dict[str, ImageGenerator] = collect_image_generators(plugins, config, plugin_config)

    for builtin in ("comfyui", "in-memory", "openrouter"):
        if builtin in registry:
            raise ValueError(f"duplicate image generator {builtin!r}")

    templates = None
    client = None
    if "comfyui" in selected_names:
        if not config.server_url:
            raise ValueError("comfyui image generation requires COMFYUI_SERVER_URL")
        templates = WorkflowTemplateStore(
            config.templates_path or None, defaults=default_templates(config.workflows)
        )
        templates.load()
        client = build_comfy_client(config)
        registry["comfyui"] = ComfyUIImageGenerator(client, templates)
    if "in-memory" in selected_names:
        registry["in-memory"] = InMemoryImageGenerator()
    if "openrouter" in selected_names:
        registry["openrouter"] = OpenRouterImageGenerator(
            model=config.openrouter_image_model,
            api_key=config.openrouter_api_key,
            server_url=config.openrouter_server_url,
        )

    unknown = sorted(selected_names - registry.keys())
    if unknown:
        raise ValueError(f"unknown image generator {unknown[0]!r}")
    routed = {
        purpose: registry[config.generator_for(purpose.value)] for purpose in ImagePurpose
    }
    video_generator = None
    if config.video_template:
        assert templates is not None
        video_template = templates.get(config.video_template)
        if video_template is None:
            raise ValueError(f"unknown video workflow template {config.video_template!r}")
        if video_template.purpose is not ImagePurpose.EVENT:
            raise ValueError("video workflow template must have purpose 'event'")
        if video_template.media is not MediaKind.VIDEO:
            raise ValueError("video workflow template must declare media 'video'")
        video_generator = registry["comfyui"]
    media = MediaStore(config.media_root)
    actor.media_service = media
    return ImageGenService(
        actor,
        config,
        generators=routed,
        video_generator=video_generator,
        client=client,
        templates=templates,
        enhancer=select_enhancer(config, plugins),
        examples=CatalogExampleSource(),
        media=media,
        alpha=remove_edge_background,
    )


__all__ = ["build_image_service", "select_enhancer"]
