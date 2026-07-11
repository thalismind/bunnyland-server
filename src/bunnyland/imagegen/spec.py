"""Workflow templates and prompt models for ComfyUI image generation (spec 27).

These pydantic models are pure data: the workflow templates players author and the prompts
the enhancer produces. ``substitute`` is the only logic here and it never touches the
network or the ECS -- it deep-copies a template graph and fills in the prompt, seed, and
dimensions. ComfyUI graphs are JSON objects keyed by node id, so substitution supports two
modes: literal ``%TOKEN%`` replacement inside string fields, and explicit
``SubstitutionSlot`` mappings that set a node field by path (numeric-safe).
"""

from __future__ import annotations

import copy
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

#: Literal tokens recognised inside template graph strings.
PROMPT_TOKEN = "%PROMPT%"
NEGATIVE_TOKEN = "%NEGATIVE%"
SEED_TOKEN = "%SEED%"
WIDTH_TOKEN = "%WIDTH%"
HEIGHT_TOKEN = "%HEIGHT%"


class MediaKind(StrEnum):
    """What a template produces. ``VIDEO`` is reserved; only ``IMAGE`` is generated today."""

    IMAGE = "image"
    VIDEO = "video"


class PromptStyle(StrEnum):
    """The prompt format a template expects from the enhancer."""

    #: Comma-separated WD14-style danbooru tags, for SDXL-era models.
    TAG = "tag"
    #: Free-form natural-language description, for Flux/Qwen-era models.
    NATURAL = "natural"


class ImagePurpose(StrEnum):
    """Why an image is being generated, used to pick a template and example set."""

    PORTRAIT = "portrait"
    ENTITY = "entity"
    SPRITE = "sprite"
    EVENT = "event"


class SubstitutionSlot(BaseModel):
    """Set one node field to a substitution value, addressed by path.

    ``node_id`` is a key in the workflow graph; ``field_path`` walks into that node (e.g.
    ``("inputs", "text")``); ``token`` selects which value to write. Unlike literal token
    replacement, the value keeps its native type, so seed/width/height stay integers.
    """

    node_id: str
    field_path: tuple[str, ...]
    token: str


class WorkflowTemplate(BaseModel):
    """A ComfyUI workflow graph plus how to inject a generated prompt into it."""

    name: str
    purpose: ImagePurpose
    prompt_style: PromptStyle = PromptStyle.NATURAL
    media: MediaKind = MediaKind.IMAGE
    description: str = ""
    default_negative: str = ""
    width: int = 1024
    height: int = 1024
    graph: dict[str, Any] = Field(default_factory=dict)
    slots: tuple[SubstitutionSlot, ...] = ()
    #: The node whose output is the result; empty means "let the client discover it".
    output_node_id: str = ""
    #: Optional named enhancer this template prefers; empty uses the configured default.
    enhancer: str = ""


class GeneratedPrompt(BaseModel):
    """The enhancer's output: the text to inject, plus optional structured tags."""

    style: PromptStyle
    prompt: str
    negative: str = ""
    tags: tuple[str, ...] = ()


def _values(*, prompt: str, negative: str, seed: int, width: int, height: int) -> dict[str, Any]:
    return {
        PROMPT_TOKEN: prompt,
        NEGATIVE_TOKEN: negative,
        SEED_TOKEN: seed,
        WIDTH_TOKEN: width,
        HEIGHT_TOKEN: height,
    }


def _replace_tokens(value: Any, str_values: dict[str, str]) -> Any:
    """Recursively replace literal ``%TOKEN%`` substrings in every string leaf."""

    if isinstance(value, str):
        for token, replacement in str_values.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, dict):
        return {key: _replace_tokens(item, str_values) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_tokens(item, str_values) for item in value]
    return value


def _apply_slot(graph: dict[str, Any], slot: SubstitutionSlot, values: dict[str, Any]) -> None:
    """Write ``values[slot.token]`` into the addressed node field, keeping its type."""

    if slot.token not in values:
        raise ValueError(f"unknown substitution token {slot.token!r}")
    if not slot.field_path:
        raise ValueError(f"slot for node {slot.node_id!r} has an empty field path")
    if slot.node_id not in graph:
        raise ValueError(f"workflow has no node {slot.node_id!r}")
    target = graph[slot.node_id]
    *parents, last = slot.field_path
    for key in parents:
        if not isinstance(target, dict) or key not in target:
            raise ValueError(f"slot path {slot.field_path} is invalid for node {slot.node_id!r}")
        target = target[key]
    if not isinstance(target, dict) or last not in target:
        raise ValueError(f"slot path {slot.field_path} is invalid for node {slot.node_id!r}")
    target[last] = values[slot.token]


def substitute(
    template: WorkflowTemplate,
    *,
    prompt: str,
    seed: int,
    negative: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Return a runnable copy of ``template.graph`` with the prompt and seed filled in.

    Literal ``%TOKEN%`` replacement runs first over every string field; explicit
    ``SubstitutionSlot`` mappings run second and win (setting native-typed values). The
    template's own ``default_negative``/``width``/``height`` are used when not overridden.
    """

    negative = template.default_negative if negative is None else negative
    width = template.width if width is None else width
    height = template.height if height is None else height
    values = _values(prompt=prompt, negative=negative, seed=seed, width=width, height=height)
    str_values = {token: str(value) for token, value in values.items()}
    graph = _replace_tokens(copy.deepcopy(template.graph), str_values)
    for slot in template.slots:
        _apply_slot(graph, slot, values)
    return graph


__all__ = [
    "HEIGHT_TOKEN",
    "NEGATIVE_TOKEN",
    "PROMPT_TOKEN",
    "SEED_TOKEN",
    "WIDTH_TOKEN",
    "GeneratedPrompt",
    "ImagePurpose",
    "MediaKind",
    "PromptStyle",
    "SubstitutionSlot",
    "WorkflowTemplate",
    "substitute",
]
