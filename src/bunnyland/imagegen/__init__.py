"""ComfyUI image generation (spec 27).

Turns entities and events into pictures via a ComfyUI server: an LLM enhancer writes a
prompt, a workflow template is filled in, the job runs on ComfyUI, and the result is stored
on disk and referenced from the ECS. Network-touching pieces (the client, the LLM enhancer,
the alpha post-process) lazily import their optional dependencies, so importing this package
never requires the ``imagegen`` extra.
"""

from __future__ import annotations

from .client import (
    ComfyClient,
    ComfyError,
    ComfyTimeoutError,
    HttpComfyClient,
    WebSocketComfyClient,
    build_comfy_client,
)
from .config import ImageGenConfig
from .prompt import (
    CatalogExampleSource,
    ImagePromptRequest,
    LLMPromptEnhancer,
    PromptEnhancer,
    PromptExampleSource,
    StubPromptEnhancer,
    VectorExampleSource,
)
from .spec import (
    GeneratedPrompt,
    ImagePurpose,
    MediaKind,
    PromptStyle,
    SubstitutionSlot,
    WorkflowTemplate,
    substitute,
)
from .store import WorkflowTemplateStore, default_templates, load_templates_from

__all__ = [
    "CatalogExampleSource",
    "ComfyClient",
    "ComfyError",
    "ComfyTimeoutError",
    "GeneratedPrompt",
    "HttpComfyClient",
    "ImageGenConfig",
    "ImagePromptRequest",
    "ImagePurpose",
    "LLMPromptEnhancer",
    "MediaKind",
    "PromptEnhancer",
    "PromptExampleSource",
    "PromptStyle",
    "StubPromptEnhancer",
    "SubstitutionSlot",
    "VectorExampleSource",
    "WebSocketComfyClient",
    "WorkflowTemplate",
    "WorkflowTemplateStore",
    "build_comfy_client",
    "default_templates",
    "load_templates_from",
    "substitute",
]
