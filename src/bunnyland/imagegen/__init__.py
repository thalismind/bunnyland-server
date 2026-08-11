"""Pluggable image and video generation."""

from .affordance import (
    ACK_EMOJI,
    DELIVER_EMOJI,
    FAIL_EMOJI,
    REQUEST_COMMAND,
    REQUEST_EMOJI,
    REQUEST_LABEL,
    VIDEO_DELIVER_EMOJI,
    VIDEO_REQUEST_COMMAND,
    VIDEO_REQUEST_EMOJI,
    VIDEO_REQUEST_LABEL,
)
from .backfill import ImageBackfillScheduler
from .client import (
    ComfyClient,
    ComfyError,
    ComfyTimeoutError,
    HttpComfyClient,
    WebSocketComfyClient,
    build_comfy_client,
)
from .comfyui import ComfyUIGenerator
from .components import (
    EventImageComponent,
    EventVideoComponent,
    ImageRequestComponent,
    PortraitImageComponent,
    VideoRequestComponent,
)
from .config import ComfyUIConfig, ImageGenConfig, MediaGenConfig, VideoGenConfig
from .events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
    VideoGenerationCompletedEvent,
    VideoGenerationFailedEvent,
    VideoGenerationStartedEvent,
)
from .feed import latest_image_completion, latest_image_failure
from .generators import (
    ImageGenerator,
    ImageGeneratorFactory,
    ImageGeneratorProfile,
    ImageGeneratorRequest,
    VideoGenerator,
    VideoGeneratorFactory,
    VideoGeneratorProfile,
    VideoGeneratorRequest,
    collect_image_generators,
    collect_video_generators,
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
from .scene import request_scene_image, request_scene_video
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
from .video_service import VideoGenError, VideoGenJob, VideoGenService
from .wiring import MediaGenerationServices, build_media_services, select_enhancer

__all__ = [
    "ACK_EMOJI",
    "CatalogExampleSource",
    "ComfyClient",
    "ComfyError",
    "ComfyTimeoutError",
    "ComfyUIConfig",
    "ComfyUIGenerator",
    "DELIVER_EMOJI",
    "EventImageComponent",
    "EventVideoComponent",
    "FAIL_EMOJI",
    "GeneratedPrompt",
    "HttpComfyClient",
    "ImageBackfillScheduler",
    "ImageGenConfig",
    "ImageGenError",
    "ImageGenJob",
    "ImageGenService",
    "ImageGenerationCompletedEvent",
    "ImageGenerationFailedEvent",
    "ImageGenerationStartedEvent",
    "ImageGenerator",
    "ImageGeneratorFactory",
    "ImageGeneratorProfile",
    "ImageGeneratorRequest",
    "ImagePromptRequest",
    "ImagePurpose",
    "ImageRequestComponent",
    "InMemoryImageGenerator",
    "LLMPromptEnhancer",
    "MediaError",
    "MediaGenConfig",
    "MediaGenerationServices",
    "MediaKind",
    "MediaStore",
    "OpenRouterImageGenerator",
    "PortraitImageComponent",
    "PromptEnhancer",
    "PromptExampleSource",
    "PromptStyle",
    "REQUEST_COMMAND",
    "REQUEST_EMOJI",
    "REQUEST_LABEL",
    "StubPromptEnhancer",
    "SubstitutionSlot",
    "VIDEO_DELIVER_EMOJI",
    "VIDEO_REQUEST_COMMAND",
    "VIDEO_REQUEST_EMOJI",
    "VIDEO_REQUEST_LABEL",
    "VectorExampleSource",
    "VideoGenConfig",
    "VideoGenError",
    "VideoGenJob",
    "VideoGenService",
    "VideoGenerationCompletedEvent",
    "VideoGenerationFailedEvent",
    "VideoGenerationStartedEvent",
    "VideoGenerator",
    "VideoGeneratorFactory",
    "VideoGeneratorProfile",
    "VideoGeneratorRequest",
    "VideoRequestComponent",
    "WebSocketComfyClient",
    "WorkflowTemplate",
    "WorkflowTemplateStore",
    "available_families",
    "build_comfy_client",
    "build_media_services",
    "collect_image_generators",
    "collect_video_generators",
    "default_templates",
    "latest_image_completion",
    "latest_image_failure",
    "load_templates_from",
    "remove_edge_background",
    "request_scene_image",
    "request_scene_video",
    "resolve_family",
    "select_enhancer",
    "substitute",
]
