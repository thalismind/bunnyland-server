"""Build a configured :class:`ImageGenService` from runtime config (spec 27).

The service depends on runtime settings (the ComfyUI URL, the media directory, the chosen
enhancer) that are only known at serve time, so it is assembled here rather than in a plugin.
The enhancer is resolved by name: the built-in ``stub``/``llm`` enhancers, or any enhancer a
plugin contributes via ``ContentContribution.prompt_enhancers``.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.world_actor import WorldActor
from ..plugins.loader import collect_prompt_enhancers
from ..plugins.model import Plugin
from .client import build_comfy_client
from .config import ImageGenConfig
from .media import MediaStore
from .postprocess import remove_edge_background
from .prompt import (
    CatalogExampleSource,
    LLMPromptEnhancer,
    PromptEnhancer,
    StubPromptEnhancer,
)
from .service import ImageGenService
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
) -> ImageGenService:
    """Assemble the full image generation service from config and plugins."""
    templates = WorkflowTemplateStore(
        config.templates_path or None, defaults=default_templates()
    )
    templates.load()
    return ImageGenService(
        actor,
        config,
        client=build_comfy_client(config),
        templates=templates,
        enhancer=select_enhancer(config, plugins),
        examples=CatalogExampleSource(),
        media=MediaStore(config.media_root),
        alpha=remove_edge_background,
    )


__all__ = ["build_image_service", "select_enhancer"]
