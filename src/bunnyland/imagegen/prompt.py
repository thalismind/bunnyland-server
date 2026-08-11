"""Style-aware image and video prompt enhancement over structured scene context."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from .. import telemetry
from ..llm_agents.agent import (
    DEFAULT_MODEL,
    _llm_request_attrs,
    _ollama_usage,
    _record_llm_usage,
    normalize_model,
)
from .scene_models import MediaEntitySnapshot, MediaSceneSnapshot
from .spec import GeneratedPrompt, ImagePurpose, MediaKind, PromptStyle

logger = logging.getLogger("bunnyland.imagegen")

DEFAULT_EXAMPLE_LIMIT = 3
STRUCTURED_ENHANCER_NAME = "structured"
STUB_ENHANCER_NAME = "stub"
MAX_TAGS = 128
MAX_TAG_CHARS = 80
MAX_PROMPT_CHARS = 4000
ANIMA_PROMPT_MODEL = "anima"
LTX_2_3_PROMPT_MODEL = "ltx-2.3"

_ANIMA_POSITIVE_PREFIX = ("masterpiece", "best quality", "score_7", "safe")
_ANIMA_NEGATIVE_PREFIX = (
    "worst quality",
    "low quality",
    "score_1",
    "score_2",
    "score_3",
    "artist name",
    "blurry",
    "jpeg artifacts",
    "chromatic aberration",
)

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_TAG_CHARS = re.compile(r"[^a-z0-9_]+")
_UNDERSCORES = re.compile(r"_+")
_WEIGHTED_TAG = re.compile(r"^\((.+):([0-9]+(?:\.[0-9]+)?)\)$")
_TAG_BREAK_WORDS = frozenset(
    {"a", "an", "the", "and", "or", "with", "without", "in", "on", "at", "of", "to"}
)

ExamplePromptCatalog = dict[
    tuple[str, MediaKind, PromptStyle, ImagePurpose], list[GeneratedPrompt]
]
ExamplePromptKey = (
    tuple[str, MediaKind, PromptStyle, ImagePurpose]
    | tuple[MediaKind, PromptStyle, ImagePurpose]
    | tuple[PromptStyle, ImagePurpose]
)

_PURPOSE_HINT: dict[ImagePurpose, str] = {
    ImagePurpose.PORTRAIT: "a character portrait, head and shoulders",
    ImagePurpose.ENTITY: "a single object on a plain background",
    ImagePurpose.SPRITE: "a full-body game sprite on a plain background",
    ImagePurpose.EVENT: "the triggering event in its consistent room setting",
}


class ImagePromptRequest(BaseModel):
    """Structured input and target format for a still-image prompt."""

    model_config = ConfigDict(frozen=True)

    subject: str
    style: PromptStyle
    purpose: ImagePurpose
    scene: MediaSceneSnapshot | None = None
    extra: str = ""
    prompt_model: str = ""


class VideoPromptRequest(BaseModel):
    """Structured input and target format for a temporal video prompt."""

    model_config = ConfigDict(frozen=True)

    subject: str
    style: PromptStyle
    scene: MediaSceneSnapshot | None = None
    extra: str = ""
    prompt_model: str = ""


@runtime_checkable
class ImagePromptEnhancer(Protocol):
    name: str

    async def enhance_image(
        self,
        request: ImagePromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt: ...


@runtime_checkable
class VideoPromptEnhancer(Protocol):
    name: str

    async def enhance_video(
        self,
        request: VideoPromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt: ...


@runtime_checkable
class MediaPromptEnhancer(ImagePromptEnhancer, VideoPromptEnhancer, Protocol):
    """One implementation may provide both modality-specific contracts."""


# Compatibility name for plugin imports written before the modality split.
PromptEnhancer = MediaPromptEnhancer


@runtime_checkable
class PromptExampleSource(Protocol):
    def examples_for(
        self,
        style: PromptStyle,
        purpose: ImagePurpose,
        subject: str,
        *,
        media: MediaKind = MediaKind.IMAGE,
        prompt_model: str = "",
    ) -> list[GeneratedPrompt]: ...


class PromptEnhancementError(RuntimeError):
    """An expected provider or validation failure eligible for structured fallback."""


def _grounding_ids(scene: MediaSceneSnapshot | None) -> tuple[str, ...]:
    if scene is None:
        return ()
    values = [f"room:{scene.room.id}"]
    if scene.primary_event_id:
        values.append(f"event:{scene.primary_event_id}")
    return tuple(values)


def _normalize_tag(value: str) -> str:
    raw = value.strip().lower()
    weighted = _WEIGHTED_TAG.fullmatch(raw)
    weight = ""
    if weighted is not None:
        raw, weight = weighted.groups()
    raw = raw.replace("'", "").replace("-", "_")
    normalized = _UNDERSCORES.sub("_", _TAG_CHARS.sub("_", raw)).strip("_")
    if not normalized or len(normalized) > MAX_TAG_CHARS:
        return ""
    if normalized.count("_") >= 10:
        return ""
    return f"({normalized}:{weight})" if weight else normalized


def normalize_tags(values: Sequence[str]) -> tuple[str, ...]:
    """Normalize ordered WD14-style tags without imposing a closed vocabulary."""

    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = _normalize_tag(value)
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tuple(tags)


def _model_tags(
    tags: Sequence[str], *, prompt_model: str, negative: bool = False
) -> tuple[str, ...]:
    if prompt_model != ANIMA_PROMPT_MODEL:
        return normalize_tags(tags)
    prefix = _ANIMA_NEGATIVE_PREFIX if negative else _ANIMA_POSITIVE_PREFIX
    return normalize_tags((*prefix, *tags))


def _render_tag(tag: str, prompt_model: str) -> str:
    if prompt_model != ANIMA_PROMPT_MODEL:
        return tag
    weighted = _WEIGHTED_TAG.fullmatch(tag)
    if weighted is not None:
        value, weight = weighted.groups()
        return f"({value.replace('_', ' ')}:{weight})"
    if tag.startswith("score_"):
        return tag
    return tag.replace("_", " ")


def _render_tags(tags: Sequence[str], prompt_model: str) -> str:
    return ", ".join(_render_tag(tag, prompt_model) for tag in tags)


def _append_direction(prompt: str, extra: str) -> str:
    """Preserve an explicit direction verbatim when the model did not do so."""

    direction = extra.strip()
    if not direction:
        return prompt[:MAX_PROMPT_CHARS]
    if direction.casefold().rstrip(".") in prompt.casefold():
        return prompt[:MAX_PROMPT_CHARS]
    direction = direction[: MAX_PROMPT_CHARS - 1].rstrip()
    if direction[-1] not in ".!?":
        direction += "."
    available = max(0, MAX_PROMPT_CHARS - len(direction) - 1)
    return f"{prompt[:available].rstrip()} {direction}".strip()


def _phrases(text: str) -> tuple[str, ...]:
    values = [part.strip() for part in re.split(r"[,;:.]", text) if part.strip()]
    return tuple(values[:8])


def _tag_phrases(text: str) -> tuple[str, ...]:
    """Split prose into short descriptive WD14-compatible tag phrases."""

    groups: list[str] = []
    current: list[str] = []
    for word in re.findall(r"[A-Za-z0-9']+", text):
        if word.lower() in _TAG_BREAK_WORDS:
            if current:
                groups.append(" ".join(current))
                current = []
            continue
        current.append(word)
        if len(current) == 4:
            groups.append(" ".join(current))
            current = []
    if current:
        groups.append(" ".join(current))
    return tuple(groups[:16])


def _entity_phrases(entity: MediaEntitySnapshot) -> tuple[str, ...]:
    values = [
        entity.name,
        entity.species,
        entity.kind,
        *entity.tags,
        *entity.states,
        *entity.held,
        *entity.worn,
        *(fact.text for fact in entity.facts),
        *_phrases(entity.appearance),
        *_tag_phrases(entity.description),
    ]
    return tuple(value for value in values if value)


def _scene_tags(scene: MediaSceneSnapshot) -> tuple[str, ...]:
    primary = next(
        (event for event in scene.events if event.id == scene.primary_event_id),
        scene.events[-1] if scene.events else None,
    )
    values: list[str] = [
        "event_scene",
        scene.room.title,
        scene.room.biome,
        scene.room.region,
        "interior" if scene.room.indoor else "exterior",
        scene.room.light,
        scene.room.time_of_day,
        scene.room.weather,
        *_phrases(scene.room.appearance),
        *(fact.text for fact in scene.room.facts),
        *_tag_phrases(scene.room.description),
    ]
    if len(scene.characters) > 1:
        values.append("multiple_characters")
    if primary is not None:
        values.extend((primary.event_type.removesuffix("Event"), *_phrases(primary.summary)))
        values.extend(primary.details)
    for entity in (*scene.characters, *scene.objects):
        if entity.role != "background" or len(values) < 72:
            values.extend(_entity_phrases(entity))
    return normalize_tags(values)


def _describe_entity(entity: MediaEntitySnapshot) -> str:
    details = [
        entity.species,
        entity.kind,
        entity.appearance,
        entity.description,
        entity.biography,
        f"visual tags: {', '.join(entity.tags)}" if entity.tags else "",
        f"state: {', '.join(entity.states)}" if entity.states else "",
        f"holding {', '.join(entity.held)}" if entity.held else "",
        f"wearing {', '.join(entity.worn)}" if entity.worn else "",
        (
            f"position x={entity.position.x}, y={entity.position.y}, "
            f"layer={entity.position.layer}"
            if entity.position is not None
            else ""
        ),
        *(fact.text for fact in entity.facts),
    ]
    rendered = "; ".join(value for value in details if value)
    return f"{entity.name} ({rendered})" if rendered else entity.name


def _scene_prose(scene: MediaSceneSnapshot, *, video: bool) -> str:
    primary = next(
        (event for event in scene.events if event.id == scene.primary_event_id),
        scene.events[-1] if scene.events else None,
    )
    event_text = primary.summary if primary is not None else "the current scene"
    setting = ", ".join(
        value
        for value in (
            scene.room.title,
            scene.room.description,
            scene.room.appearance,
            scene.room.biome,
            scene.room.region,
            scene.room.light,
            scene.room.time_of_day,
            scene.room.weather,
            *(fact.text for fact in scene.room.facts),
        )
        if value
    )
    foreground = [
        _describe_entity(entity)
        for entity in scene.characters
        if entity.role != "background"
    ]
    background = [
        _describe_entity(entity)
        for entity in scene.characters
        if entity.role == "background"
    ]
    props = [_describe_entity(entity) for entity in scene.objects]
    event_details = (
        "; ".join(primary.details) if primary is not None and primary.details else ""
    )
    parts = [f"Foreground event: {event_text}."]
    if event_details:
        parts.append(f"Event details: {event_details}.")
    if scene.world_title or scene.world_description:
        parts.append(
            "World context: "
            + "; ".join(
                value for value in (scene.world_title, scene.world_description) if value
            )
            + "."
        )
    parts.append(f"Setting: {setting}.")
    if foreground:
        parts.append("Primary subjects: " + "; ".join(foreground) + ".")
    if background:
        parts.append("Other visible characters: " + "; ".join(background) + ".")
    if props:
        parts.append("Visible props and background objects: " + "; ".join(props) + ".")
    if video:
        lead_in = " Then ".join(event.summary for event in scene.events[:-1])
        if lead_in:
            parts.append(f"Lead-in: {lead_in}.")
        parts.append(
            "Show the foreground action unfolding through clear subject and object motion, "
            "a stable establishing-to-medium camera move, environmental motion, and matching "
            "ambient and action audio."
        )
    else:
        parts.append(
            "Compose a clear cinematic still with the foreground action dominant and the "
            "setting readable enough to maintain continuity with other scenes."
        )
    return " ".join(parts)[:MAX_PROMPT_CHARS]


class StructuredPromptEnhancer:
    """Deterministic grounded renderer used offline and as the LLM fallback."""

    name = STRUCTURED_ENHANCER_NAME

    async def enhance_image(
        self,
        request: ImagePromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt:
        del examples
        grounding = _grounding_ids(request.scene)
        if request.style is PromptStyle.TAG:
            tags = (
                _scene_tags(request.scene)
                if request.scene is not None
                else normalize_tags((request.purpose.value, *_tag_phrases(request.subject)))
            )
            tags = _model_tags(
                (*tags, *_tag_phrases(request.extra)),
                prompt_model=request.prompt_model,
            )
            return GeneratedPrompt(
                style=PromptStyle.TAG,
                prompt=_render_tags(tags, request.prompt_model),
                tags=tags,
                enhancer=self.name,
                fallback=False,
                grounding_fact_ids=grounding,
            )
        prompt = (
            _scene_prose(request.scene, video=False)
            if request.scene is not None
            else f"{_PURPOSE_HINT[request.purpose]}: {request.subject.strip()}".rstrip(": ")
        )
        prompt = _append_direction(prompt, request.extra)
        return GeneratedPrompt(
            style=PromptStyle.NATURAL,
            prompt=prompt,
            enhancer=self.name,
            fallback=False,
            grounding_fact_ids=grounding,
        )

    async def enhance_video(
        self,
        request: VideoPromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt:
        del examples
        grounding = _grounding_ids(request.scene)
        if request.style is PromptStyle.TAG:
            base_tags = (
                _scene_tags(request.scene)
                if request.scene is not None
                else normalize_tags(("event_video", *_tag_phrases(request.subject)))
            )
            tags = _model_tags(
                (*base_tags, "motion", "cinematic_camera", *_tag_phrases(request.extra)),
                prompt_model=request.prompt_model,
            )
            return GeneratedPrompt(
                style=PromptStyle.TAG,
                prompt=_render_tags(tags, request.prompt_model),
                tags=tags,
                enhancer=self.name,
                fallback=False,
                grounding_fact_ids=grounding,
            )
        prompt = (
            _scene_prose(request.scene, video=True)
            if request.scene is not None
            else (
                f"A cinematic shot of {request.subject}. Show the action unfolding with "
                "clear motion, a stable camera move, environmental movement, and matching audio."
            )
        )
        prompt = _append_direction(prompt, request.extra)
        return GeneratedPrompt(
            style=PromptStyle.NATURAL,
            prompt=prompt,
            enhancer=self.name,
            fallback=False,
            grounding_fact_ids=grounding,
        )

    async def enhance(
        self,
        request: ImagePromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt:
        """Compatibility adapter for pre-split image enhancer callers."""

        return await self.enhance_image(request, examples=examples)


class StubPromptEnhancer(StructuredPromptEnhancer):
    """Compatibility name for the former deterministic image enhancer."""

    name = STUB_ENHANCER_NAME


def _system_prompt(style: PromptStyle, media: MediaKind, prompt_model: str) -> str:
    direction_rule = (
        "If an Additional direction is present, it is mandatory: preserve every requested "
        "visible, motion, camera, or audio detail and never negate or replace it. "
    )
    if prompt_model == ANIMA_PROMPT_MODEL:
        return (
            "Convert the structured game-world facts into an ordered Anima tag prompt. "
            "Use lowercase Danbooru/Gelbooru-style tags with spaces rather than underscores, "
            "except score tags. Order tags as quality/meta/safety, character counts and "
            "identities, then general scene tags. Begin positive tags with masterpiece, best "
            "quality, score_7, safe. Begin negative tags with worst quality, low quality, "
            "score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic "
            "aberration. Preserve the primary event, room, visible appearances, composition, "
            f"and lighting. {direction_rule}Return ONLY JSON with keys tags (string array) "
            "and negative_tags (string array). No prose."
        )
    if prompt_model == LTX_2_3_PROMPT_MODEL:
        return (
            "Write one continuous English paragraph for LTX 2.3 text-to-video. Strictly "
            "include every requested visual, action, motion, camera, and audio element. Start "
            "with the visual style only when known, then describe the scene chronologically "
            "using active present-progressive verbs and temporal connectors such as as, then, "
            "and while. Integrate specific ambient sounds and action audio alongside the "
            "corresponding motion. Do not invent dialogue, characters, camera motion, cuts, or "
            f"timestamps. {direction_rule}Return ONLY JSON with keys prompt and negative."
        )
    if style is PromptStyle.TAG:
        return (
            "Convert structured game-world scene facts into ordered WD14/Danbooru-style "
            "image tags. Preserve the primary event, room setting, visible appearances, "
            f"composition, and lighting. {direction_rule}Return ONLY JSON with keys tags "
            "(string array) and negative_tags (string array). No prose."
        )
    if media is MediaKind.VIDEO:
        return (
            "Write a concise natural-language text-to-video prompt grounded only in the "
            "structured game-world facts. Foreground the primary event and describe temporal "
            "progression, subject/object motion, camera movement, environmental motion, and "
            "matching audio while preserving room and character continuity. "
            f"{direction_rule}Return ONLY JSON with prompt and negative."
        )
    return (
        "Write a concise natural-language diffusion image prompt grounded only in the "
        "structured game-world facts. Foreground the primary event while preserving the room "
        "setting, visible appearances, relevant props, composition, and lighting. "
        f"{direction_rule}Return ONLY JSON with prompt and negative."
    )


def _example_output(example: GeneratedPrompt, style: PromptStyle) -> str:
    if style is PromptStyle.TAG:
        tags = example.tags or tuple(
            value.strip() for value in example.prompt.split(",") if value.strip()
        )
        negative_tags = tuple(
            value.strip() for value in example.negative.split(",") if value.strip()
        )
        value: dict[str, JsonValue] = {
            "tags": list(tags),
            "negative_tags": list(negative_tags),
        }
    else:
        value = {"prompt": example.prompt, "negative": example.negative}
    return json.dumps(value, ensure_ascii=True)


def _user_prompt(
    *,
    subject: str,
    scene: MediaSceneSnapshot | None,
    purpose: ImagePurpose,
    media: MediaKind,
    style: PromptStyle,
    extra: str,
    examples: Sequence[GeneratedPrompt],
) -> str:
    lines = [f"Media: {media.value}", f"Purpose: {_PURPOSE_HINT[purpose]}"]
    if examples:
        lines.append("Example outputs in the required JSON shape:")
        lines.extend(_example_output(example, style) for example in examples)
    if scene is not None:
        lines.append(
            "Provenance IDs (metadata only; never render them in the prompt): "
            + ", ".join(_grounding_ids(scene))
        )
        lines.append("Structured scene:")
        lines.append(scene.prompt_context())
    else:
        lines.append(f"Subject: {subject}")
    if extra:
        lines.append(f"Additional direction (mandatory): {extra}")
    return "\n".join(lines)


def _response_content(response: object) -> str:
    message = getattr(response, "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(response, Mapping):
        mapped_message = response.get("message")
        if isinstance(mapped_message, Mapping):
            mapped_content = mapped_message.get("content")
            if isinstance(mapped_content, str):
                return mapped_content
    raise PromptEnhancementError("Ollama response did not contain message content")


class OllamaMediaPromptClient:
    """Small shared Ollama JSON client used by both modality adapters."""

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
                "LLMMediaPromptEnhancer requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        options: dict[str, object] = {}
        if host:
            options["host"] = host
        if api_key:
            options["headers"] = {"Authorization": f"Bearer {api_key}"}
        self._client = ollama.AsyncClient(**options)
        self.model = normalize_model(model)

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        request_kind: str,
        style: PromptStyle,
        purpose: ImagePurpose,
        example_count: int,
    ) -> dict[str, JsonValue]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            with telemetry.span(
                "llm.provider.attempt",
                {
                    "provider": "ollama",
                    "llm.attempt": 0,
                    **_llm_request_attrs(
                        request_kind,
                        self.model,
                        messages,
                        None,
                        system_prompt=system_prompt,
                    ),
                    "image.purpose": purpose.value,
                    "media.prompt.style": style.value,
                    "media.examples.count": example_count,
                },
            ) as provider_span:
                response: object = await self._client.chat(
                    model=self.model,
                    format="json",
                    messages=messages,
                )
                _record_llm_usage("ollama", self.model, _ollama_usage(response))
                telemetry.mark_span_ok(provider_span)
        except Exception as exc:  # noqa: BLE001 - provider failures use structured fallback.
            raise PromptEnhancementError(f"Ollama prompt enhancement failed: {exc}") from exc
        try:
            return _JSON_OBJECT.validate_python(json.loads(_response_content(response)))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise PromptEnhancementError(f"invalid prompt-enhancement JSON: {exc}") from exc


class LLMMediaPromptEnhancer:
    """LLM image/video adapters with style-matched structured fallback."""

    name = "llm"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        host: str | None = None,
        api_key: str | None = None,
        client: OllamaMediaPromptClient | None = None,
        fallback: MediaPromptEnhancer | None = None,
    ) -> None:
        self._client = client or OllamaMediaPromptClient(
            model=model,
            host=host,
            api_key=api_key,
        )
        self._fallback = fallback or StructuredPromptEnhancer()

    async def enhance_image(
        self,
        request: ImagePromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt:
        try:
            return await self._enhance(
                subject=request.subject,
                scene=request.scene,
                style=request.style,
                purpose=request.purpose,
                media=MediaKind.IMAGE,
                extra=request.extra,
                prompt_model=request.prompt_model,
                examples=examples,
            )
        except PromptEnhancementError as exc:
            logger.warning("image prompt enhancement failed; using structured fallback: %s", exc)
            fallback = await self._fallback.enhance_image(request, examples=examples)
            return fallback.model_copy(update={"fallback": True})

    async def enhance_video(
        self,
        request: VideoPromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt:
        try:
            return await self._enhance(
                subject=request.subject,
                scene=request.scene,
                style=request.style,
                purpose=ImagePurpose.EVENT,
                media=MediaKind.VIDEO,
                extra=request.extra,
                prompt_model=request.prompt_model,
                examples=examples,
            )
        except PromptEnhancementError as exc:
            logger.warning("video prompt enhancement failed; using structured fallback: %s", exc)
            fallback = await self._fallback.enhance_video(request, examples=examples)
            return fallback.model_copy(update={"fallback": True})

    async def enhance(
        self,
        request: ImagePromptRequest,
        *,
        examples: Sequence[GeneratedPrompt] = (),
    ) -> GeneratedPrompt:
        """Compatibility adapter for pre-split image enhancer callers."""

        return await self.enhance_image(request, examples=examples)

    async def _enhance(
        self,
        *,
        subject: str,
        scene: MediaSceneSnapshot | None,
        style: PromptStyle,
        purpose: ImagePurpose,
        media: MediaKind,
        extra: str,
        prompt_model: str,
        examples: Sequence[GeneratedPrompt],
    ) -> GeneratedPrompt:
        data = await self._client.complete(
            system_prompt=_system_prompt(style, media, prompt_model),
            user_prompt=_user_prompt(
                subject=subject,
                scene=scene,
                purpose=purpose,
                media=media,
                style=style,
                extra=extra,
                examples=examples,
            ),
            request_kind="video_prompt" if media is MediaKind.VIDEO else "image_prompt",
            style=style,
            purpose=purpose,
            example_count=len(examples),
        )
        raw_grounding = data.get("grounding_fact_ids", [])
        grounding = (
            tuple(value for value in raw_grounding if isinstance(value, str))
            if isinstance(raw_grounding, list)
            else ()
        )
        if style is PromptStyle.TAG:
            raw_tags = data.get("tags", [])
            raw_negative = data.get("negative_tags", [])
            if not isinstance(raw_tags, list) or not isinstance(raw_negative, list):
                raise PromptEnhancementError("tag response requires tag arrays")
            tags = _model_tags(
                (
                    *(value for value in raw_tags if isinstance(value, str)),
                    *_tag_phrases(extra),
                ),
                prompt_model=prompt_model,
            )
            negative_tags = _model_tags(
                tuple(value for value in raw_negative if isinstance(value, str)),
                prompt_model=prompt_model,
                negative=True,
            )
            if not tags:
                raise PromptEnhancementError("tag response contained no valid tags")
            return GeneratedPrompt(
                style=style,
                prompt=_render_tags(tags, prompt_model),
                negative=_render_tags(negative_tags, prompt_model),
                tags=tags,
                enhancer=self.name,
                grounding_fact_ids=grounding,
            )
        prompt = data.get("prompt")
        negative = data.get("negative", "")
        if not isinstance(prompt, str) or not prompt.strip():
            raise PromptEnhancementError("natural response requires a non-empty prompt")
        if not isinstance(negative, str):
            raise PromptEnhancementError("natural response negative must be text")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise PromptEnhancementError("natural response exceeds the prompt limit")
        prompt = _append_direction(prompt.strip(), extra)
        return GeneratedPrompt(
            style=style,
            prompt=prompt,
            negative=negative.strip(),
            enhancer=self.name,
            grounding_fact_ids=grounding,
        )


# Compatibility name used by existing imports and configurations.
LLMPromptEnhancer = LLMMediaPromptEnhancer


def _load_catalog_directory(
    directory: Traversable,
    *,
    prompt_model: str,
    catalog: ExamplePromptCatalog,
) -> None:
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".json"):
            continue
        parts = entry.name[:-5].split("-")
        if len(parts) == 2:
            media = MediaKind.IMAGE
            style_name, purpose_name = parts
        elif len(parts) == 3:
            media = MediaKind(parts[0])
            style_name, purpose_name = parts[1:]
        else:
            raise ValueError(f"invalid prompt-example filename {entry.name!r}")
        style = PromptStyle(style_name)
        purpose = ImagePurpose(purpose_name)
        raw = _JSON_OBJECT.validate_python({"items": json.loads(entry.read_text())})["items"]
        if not isinstance(raw, list):
            raise ValueError(f"prompt examples in {entry.name!r} must be a list")
        catalog[(prompt_model, media, style, purpose)] = [
            GeneratedPrompt.model_validate({"style": style.value, **item})
            for item in raw
            if isinstance(item, dict)
        ]


def load_catalog_from(directory: Traversable) -> ExamplePromptCatalog:
    """Load generic examples plus one model-specific level of subdirectories."""

    catalog: ExamplePromptCatalog = {}
    _load_catalog_directory(directory, prompt_model="", catalog=catalog)
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.is_dir():
            _load_catalog_directory(entry, prompt_model=entry.name, catalog=catalog)
    return catalog


def default_catalog() -> ExamplePromptCatalog:
    return load_catalog_from(resources.files("bunnyland.imagegen").joinpath("examples"))


class CatalogExampleSource:
    def __init__(
        self,
        catalog: Mapping[ExamplePromptKey, Sequence[GeneratedPrompt]] | None = None,
        *,
        limit: int = DEFAULT_EXAMPLE_LIMIT,
    ) -> None:
        if catalog is None:
            self._catalog = default_catalog()
        else:
            self._catalog: ExamplePromptCatalog = {}
            for key, values in catalog.items():
                if len(key) == 2:
                    normalized_key = ("", MediaKind.IMAGE, key[0], key[1])
                elif len(key) == 3:
                    normalized_key = ("", key[0], key[1], key[2])
                else:
                    normalized_key = (key[0], key[1], key[2], key[3])
                self._catalog[normalized_key] = list(values)
        self._limit = limit

    def examples_for(
        self,
        style: PromptStyle,
        purpose: ImagePurpose,
        subject: str,
        *,
        media: MediaKind = MediaKind.IMAGE,
        prompt_model: str = "",
    ) -> list[GeneratedPrompt]:
        del subject
        prompt_models = (prompt_model, "") if prompt_model else ("",)
        for candidate_model in prompt_models:
            exact = self._catalog.get((candidate_model, media, style, purpose))
            if exact:
                return list(exact[: self._limit])
            image_fallback = self._catalog.get(
                (candidate_model, MediaKind.IMAGE, style, purpose), ()
            )
            if image_fallback:
                return list(image_fallback[: self._limit])
            style_fallback = next(
                (
                    values
                    for (
                        catalog_model,
                        candidate_media,
                        candidate_style,
                        _candidate_purpose,
                    ), values in sorted(
                        self._catalog.items(),
                        key=lambda item: tuple(str(part) for part in item[0]),
                    )
                    if catalog_model == candidate_model
                    and candidate_media is media
                    and candidate_style is style
                    and values
                ),
                (),
            )
            if style_fallback:
                return list(style_fallback[: self._limit])
        return []


class VectorCollection(Protocol):
    def query(
        self,
        *,
        query_texts: list[str],
        n_results: int,
        where: dict[str, str],
    ) -> object: ...


class VectorExampleSource:
    def __init__(
        self,
        collection: VectorCollection,
        *,
        limit: int = DEFAULT_EXAMPLE_LIMIT,
        fallback: PromptExampleSource | None = None,
    ) -> None:
        self._collection = collection
        self._limit = limit
        self._fallback = fallback

    def examples_for(
        self,
        style: PromptStyle,
        purpose: ImagePurpose,
        subject: str,
        *,
        media: MediaKind = MediaKind.IMAGE,
        prompt_model: str = "",
    ) -> list[GeneratedPrompt]:
        where = {
            "media": media.value,
            "style": style.value,
            "purpose": purpose.value,
        }
        if prompt_model:
            where["prompt_model"] = prompt_model
        result = _JSON_OBJECT.validate_python(
            self._collection.query(
                query_texts=[subject],
                n_results=self._limit,
                where=where,
            )
        )
        raw_documents = result.get("documents", [[]])
        raw_metadatas = result.get("metadatas", [[]])
        documents = raw_documents[0] if isinstance(raw_documents, list) and raw_documents else []
        metadatas = raw_metadatas[0] if isinstance(raw_metadatas, list) and raw_metadatas else []
        examples: list[GeneratedPrompt] = []
        if isinstance(documents, list) and isinstance(metadatas, list):
            for document, metadata in zip(documents, metadatas, strict=False):
                if not isinstance(document, str):
                    continue
                metadata = metadata if isinstance(metadata, dict) else {}
                negative = metadata.get("negative", "")
                raw_tags = metadata.get("tags", "")
                examples.append(
                    GeneratedPrompt(
                        style=style,
                        prompt=document,
                        negative=negative if isinstance(negative, str) else "",
                        tags=(
                            tuple(tag for tag in raw_tags.split(",") if tag)
                            if isinstance(raw_tags, str)
                            else ()
                        ),
                    )
                )
        if not examples and self._fallback is not None:
            return self._fallback.examples_for(
                style,
                purpose,
                subject,
                media=media,
                prompt_model=prompt_model,
            )
        return examples


__all__ = [
    "DEFAULT_EXAMPLE_LIMIT",
    "MAX_PROMPT_CHARS",
    "MAX_TAGS",
    "STUB_ENHANCER_NAME",
    "STRUCTURED_ENHANCER_NAME",
    "CatalogExampleSource",
    "ExamplePromptCatalog",
    "ImagePromptEnhancer",
    "ImagePromptRequest",
    "LLMMediaPromptEnhancer",
    "LLMPromptEnhancer",
    "MediaPromptEnhancer",
    "OllamaMediaPromptClient",
    "PromptEnhancementError",
    "PromptEnhancer",
    "PromptExampleSource",
    "StructuredPromptEnhancer",
    "StubPromptEnhancer",
    "VectorCollection",
    "VectorExampleSource",
    "VideoPromptEnhancer",
    "VideoPromptRequest",
    "default_catalog",
    "load_catalog_from",
    "normalize_tags",
]
