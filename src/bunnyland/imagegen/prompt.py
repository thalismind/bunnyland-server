"""Prompt enhancement for image generation (spec 27).

An *enhancer* turns a plain subject description into a model-ready prompt in the format a
workflow template expects: WD14-style tags for SDXL models, or a natural-language sentence
for Flux/Qwen. Enhancers are pluggable -- plugins can provide their own -- and are *few-shot*:
they pull a handful of format exemplars from an :class:`PromptExampleSource` (a local catalog,
or optionally the vector store) and include them so the output keeps the right shape. The
built-in :class:`StubPromptEnhancer` is deterministic and network-free; :class:`LLMPromptEnhancer`
calls an Ollama model and is only constructed when the ``llm`` extra is installed.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from importlib import resources
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from .. import telemetry
from ..llm_agents.agent import (
    DEFAULT_MODEL,
    _llm_request_attrs,
    _ollama_usage,
    _record_llm_usage,
    normalize_model,
)
from .spec import GeneratedPrompt, ImagePurpose, MediaKind, PromptStyle

logger = logging.getLogger("bunnyland.imagegen")

#: How many format exemplars to feed an enhancer by default.
DEFAULT_EXAMPLE_LIMIT = 3
#: The name of the always-available built-in enhancer.
STUB_ENHANCER_NAME = "stub"

_WORD = re.compile(r"[a-z0-9]+")

#: A catalog of few-shot examples keyed by ``(style, purpose)``.
ExamplePromptCatalog = dict[tuple[PromptStyle, ImagePurpose], list[GeneratedPrompt]]

#: Short purpose framing reused by the stub and the LLM system prompt.
_PURPOSE_HINT: dict[ImagePurpose, str] = {
    ImagePurpose.PORTRAIT: "a character portrait, head and shoulders",
    ImagePurpose.ENTITY: "a single object on a plain background",
    ImagePurpose.SPRITE: "a full-body game sprite on a plain background",
    ImagePurpose.EVENT: "a scene with a room and the characters and items in it",
}


class ImagePromptRequest(BaseModel):
    """The subject and format an enhancer should produce a prompt for."""

    subject: str
    style: PromptStyle
    purpose: ImagePurpose
    media: MediaKind = MediaKind.IMAGE
    extra: str = ""


@runtime_checkable
class PromptEnhancer(Protocol):
    """Turns a subject description into a model-ready prompt."""

    name: str

    async def enhance(
        self, request: ImagePromptRequest, *, examples: Sequence[GeneratedPrompt] = ()
    ) -> GeneratedPrompt: ...


@runtime_checkable
class PromptExampleSource(Protocol):
    """Supplies a few format exemplars for a given style/purpose/subject."""

    def examples_for(
        self, style: PromptStyle, purpose: ImagePurpose, subject: str
    ) -> list[GeneratedPrompt]: ...


def _subject_tags(subject: str) -> list[str]:
    """Unique, order-preserving lowercase word tags from a subject description."""
    seen: dict[str, None] = {}
    for word in _WORD.findall(subject.lower()):
        seen.setdefault(word, None)
    return list(seen)


class StubPromptEnhancer:
    """Deterministic, network-free enhancer. The default when no LLM is configured."""

    name = STUB_ENHANCER_NAME

    async def enhance(
        self, request: ImagePromptRequest, *, examples: Sequence[GeneratedPrompt] = ()
    ) -> GeneratedPrompt:
        del examples  # the stub is deterministic and ignores exemplars
        hint = _PURPOSE_HINT[request.purpose]
        if request.style is PromptStyle.TAG:
            tags = [request.purpose.value, *_subject_tags(request.subject)]
            return GeneratedPrompt(style=PromptStyle.TAG, prompt=", ".join(tags), tags=tuple(tags))
        subject = request.subject.strip()
        prompt = f"{hint}: {subject}" if subject else hint
        return GeneratedPrompt(style=PromptStyle.NATURAL, prompt=prompt)


def _system_prompt(style: PromptStyle) -> str:
    if style is PromptStyle.TAG:
        return (
            "You write image prompts as comma-separated WD14/danbooru tags for an SDXL model. "
            'Return ONLY JSON: {"prompt": "tag1, tag2, ...", "negative": "...", '
            '"tags": ["tag1", "tag2"]}. No prose.'
        )
    return (
        "You write concise natural-language image prompts for a diffusion model. "
        'Return ONLY JSON: {"prompt": "...", "negative": "..."}. No prose.'
    )


def _user_prompt(request: ImagePromptRequest, examples: Sequence[GeneratedPrompt]) -> str:
    lines: list[str] = []
    if examples:
        lines.append("Match the format of these examples:")
        lines.extend(f"- {example.prompt}" for example in examples)
    lines.append(f"Purpose: {_PURPOSE_HINT[request.purpose]}")
    lines.append(f"Subject: {request.subject}")
    if request.extra:
        lines.append(f"Extra direction: {request.extra}")
    return "\n".join(lines)


class LLMPromptEnhancer:
    """Asks an Ollama model for a formatted prompt. ``ollama`` is imported lazily."""

    name = "llm"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        host: str | None = None,
        api_key: str | None = None,
    ) -> None:
        try:
            import ollama
        except ImportError as exc:
            raise RuntimeError(
                "LLMPromptEnhancer requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        client_cls = ollama.AsyncClient
        self._client = client_cls(host=host, headers=headers) if host else client_cls()
        self._model = model

    async def enhance(
        self, request: ImagePromptRequest, *, examples: Sequence[GeneratedPrompt] = ()
    ) -> GeneratedPrompt:
        model = normalize_model(self._model)
        system_prompt = _system_prompt(request.style)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _user_prompt(request, examples)},
        ]
        with telemetry.span(
            "llm.provider.attempt",
            {
                "provider": "ollama",
                "llm.attempt": 0,
                **_llm_request_attrs(
                    "image_prompt", model, messages, None, system_prompt=system_prompt
                ),
                "image.purpose": request.purpose.value,
                "image.prompt.style": request.style.value,
                "image.examples.count": len(examples),
            },
        ) as provider_span:
            response = await self._client.chat(
                model=model,
                format="json",
                messages=messages,
            )
            _record_llm_usage("ollama", model, _ollama_usage(response))
            telemetry.mark_span_ok(provider_span)
        data = json.loads(response["message"]["content"])
        data.setdefault("style", request.style.value)
        return GeneratedPrompt.model_validate(data)


def load_catalog_from(directory: Any) -> ExamplePromptCatalog:
    """Load ``{style}-{purpose}.json`` example files from a directory into a keyed catalog."""
    catalog: ExamplePromptCatalog = {}
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".json"):
            continue
        style_name, _, purpose_name = entry.name[:-5].partition("-")
        style = PromptStyle(style_name)
        purpose = ImagePurpose(purpose_name)
        raw = json.loads(entry.read_text())
        catalog[(style, purpose)] = [GeneratedPrompt(style=style, **item) for item in raw]
    return catalog


def default_catalog() -> ExamplePromptCatalog:
    """The built-in example catalog shipped as package data."""
    return load_catalog_from(resources.files("bunnyland.imagegen").joinpath("examples"))


class CatalogExampleSource:
    """Few-shot examples from a fixed local catalog (the default source)."""

    def __init__(
        self,
        catalog: ExamplePromptCatalog | None = None,
        *,
        limit: int = DEFAULT_EXAMPLE_LIMIT,
    ) -> None:
        self._catalog = dict(catalog) if catalog is not None else default_catalog()
        self._limit = limit

    def examples_for(
        self, style: PromptStyle, purpose: ImagePurpose, subject: str
    ) -> list[GeneratedPrompt]:
        del subject  # the catalog is keyed by style/purpose, not subject similarity
        exact = self._catalog.get((style, purpose))
        if exact:
            return list(exact[: self._limit])
        pooled = [
            example
            for (entry_style, _), examples in self._catalog.items()
            if entry_style == style
            for example in examples
        ]
        return pooled[: self._limit]


class VectorExampleSource:
    """Few-shot examples ranked by subject similarity from an injected vector collection.

    The ChromaDB collection is duck-typed (``query(query_texts, n_results, where)``), so this
    works with any compatible store and is mockable. When the query returns nothing and a
    ``fallback`` source is given, the fallback is used.
    """

    def __init__(
        self,
        collection: Any,
        *,
        limit: int = DEFAULT_EXAMPLE_LIMIT,
        fallback: PromptExampleSource | None = None,
    ) -> None:
        self._collection = collection
        self._limit = limit
        self._fallback = fallback

    def examples_for(
        self, style: PromptStyle, purpose: ImagePurpose, subject: str
    ) -> list[GeneratedPrompt]:
        result = self._collection.query(
            query_texts=[subject],
            n_results=self._limit,
            where={"style": style.value, "purpose": purpose.value},
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        examples: list[GeneratedPrompt] = []
        for document, metadata in zip(documents, metadatas, strict=False):
            metadata = metadata or {}
            tags = metadata.get("tags", "")
            examples.append(
                GeneratedPrompt(
                    style=style,
                    prompt=document,
                    negative=metadata.get("negative", ""),
                    tags=tuple(tag for tag in tags.split(",") if tag),
                )
            )
        if not examples and self._fallback is not None:
            return self._fallback.examples_for(style, purpose, subject)
        return examples


__all__ = [
    "DEFAULT_EXAMPLE_LIMIT",
    "STUB_ENHANCER_NAME",
    "CatalogExampleSource",
    "ExamplePromptCatalog",
    "ImagePromptRequest",
    "LLMPromptEnhancer",
    "PromptEnhancer",
    "PromptExampleSource",
    "StubPromptEnhancer",
    "VectorExampleSource",
    "default_catalog",
    "load_catalog_from",
]
