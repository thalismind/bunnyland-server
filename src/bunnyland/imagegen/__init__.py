"""ComfyUI image generation (spec 27).

Turns entities and events into pictures via a ComfyUI server: an LLM enhancer writes a
prompt, a workflow template is filled in, the job runs on ComfyUI, and the result is stored
on disk and referenced from the ECS. Network-touching pieces (the client, the LLM enhancer,
the alpha post-process) lazily import their optional dependencies, so importing this package
never requires the ``imagegen`` extra.
"""

from __future__ import annotations

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
    "GeneratedPrompt",
    "ImagePurpose",
    "MediaKind",
    "PromptStyle",
    "SubstitutionSlot",
    "WorkflowTemplate",
    "WorkflowTemplateStore",
    "default_templates",
    "load_templates_from",
    "substitute",
]
