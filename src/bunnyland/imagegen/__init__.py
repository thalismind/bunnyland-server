"""Pluggable image generation (spec 27).

Turns entities and events into pictures through a purpose-selected generator, then stores the
result on disk and references it from the ECS. Network-touching pieces and raster processing
lazily import their optional dependencies, so importing this package never requires the
``imagegen`` or ``llm`` extras.
"""

from __future__ import annotations

from .affordance import (
    ACK_EMOJI,
    DELIVER_EMOJI,
    FAIL_EMOJI,
    REQUEST_COMMAND,
    REQUEST_EMOJI,
    REQUEST_LABEL,
    VIDEO_COMING_SOON,
)
from .client import (
    ComfyClient,
    ComfyError,
    ComfyTimeoutError,
    HttpComfyClient,
    WebSocketComfyClient,
    build_comfy_client,
)
from .components import (
    EventImageComponent,
    ImageRequestComponent,
    PortraitImageComponent,
)
from .config import ImageGenConfig
from .events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
)
from .feed import latest_image_completion, latest_image_failure
from .generators import (
    ImageGenerator,
    ImageGeneratorFactory,
    ImageGeneratorProfile,
    ImageGeneratorRequest,
    collect_image_generators,
)
from .in_memory import InMemoryImageGenerator
from .media import MediaError, MediaStore
from .openrouter import OpenRouterImageGenerator
from .postprocess import remove_edge_background
from .prompt import (
    CatalogExampleSource,
    ImagePromptRequest,
    LLMPromptEnhancer,
    PromptEnhancer,
    PromptExampleSource,
    StubPromptEnhancer,
    VectorExampleSource,
)
from .scene import request_scene_image
from .service import ImageGenError, ImageGenJob, ImageGenService
from .spec import (
    GeneratedPrompt,
    ImagePurpose,
    MediaKind,
    PromptStyle,
    SubstitutionSlot,
    WorkflowTemplate,
    substitute,
)
from .store import (
    WorkflowTemplateStore,
    available_families,
    default_templates,
    load_templates_from,
    resolve_family,
)
from .wiring import build_image_service, select_enhancer

__all__ = [
    "ACK_EMOJI",
    "DELIVER_EMOJI",
    "FAIL_EMOJI",
    "REQUEST_COMMAND",
    "REQUEST_EMOJI",
    "REQUEST_LABEL",
    "VIDEO_COMING_SOON",
    "CatalogExampleSource",
    "ComfyClient",
    "ComfyError",
    "ComfyTimeoutError",
    "EventImageComponent",
    "GeneratedPrompt",
    "HttpComfyClient",
    "ImageGenConfig",
    "ImageGenError",
    "ImageGenJob",
    "ImageGenService",
    "ImageGenerator",
    "ImageGeneratorFactory",
    "ImageGeneratorProfile",
    "ImageGeneratorRequest",
    "ImageGenerationCompletedEvent",
    "ImageGenerationFailedEvent",
    "ImageGenerationStartedEvent",
    "ImagePromptRequest",
    "ImagePurpose",
    "ImageRequestComponent",
    "InMemoryImageGenerator",
    "LLMPromptEnhancer",
    "MediaError",
    "MediaKind",
    "MediaStore",
    "PortraitImageComponent",
    "OpenRouterImageGenerator",
    "PromptEnhancer",
    "PromptExampleSource",
    "PromptStyle",
    "StubPromptEnhancer",
    "SubstitutionSlot",
    "VectorExampleSource",
    "WebSocketComfyClient",
    "WorkflowTemplate",
    "WorkflowTemplateStore",
    "available_families",
    "build_comfy_client",
    "build_image_service",
    "collect_image_generators",
    "default_templates",
    "latest_image_completion",
    "latest_image_failure",
    "load_templates_from",
    "resolve_family",
    "remove_edge_background",
    "request_scene_image",
    "select_enhancer",
    "substitute",
]
