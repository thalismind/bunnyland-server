"""Tests for the pluggable, few-shot image prompt enhancer and example sources."""

from __future__ import annotations

import json
import sys
import types

import pytest

from bunnyland.imagegen.prompt import (
    CatalogExampleSource,
    ImagePromptRequest,
    LLMPromptEnhancer,
    PromptEnhancer,
    PromptExampleSource,
    StructuredPromptEnhancer,
    StubPromptEnhancer,
    VectorExampleSource,
    VideoPromptRequest,
    default_catalog,
    load_catalog_from,
    normalize_tags,
)
from bunnyland.imagegen.scene_models import (
    MAX_SCENE_CONTEXT_CHARS,
    MediaEntitySnapshot,
    MediaEventSnapshot,
    MediaFact,
    MediaRoomSnapshot,
    MediaSceneSnapshot,
)
from bunnyland.imagegen.spec import (
    GeneratedPrompt,
    ImagePurpose,
    MediaKind,
    PromptStyle,
)


def _request(style: PromptStyle, purpose=ImagePurpose.PORTRAIT, **kw) -> ImagePromptRequest:
    return ImagePromptRequest(subject="a brave rabbit ranger", style=style, purpose=purpose, **kw)


def _scene() -> MediaSceneSnapshot:
    return MediaSceneSnapshot(
        captured_at_epoch=7,
        viewer_id="character:viewer",
        primary_event_id="lever",
        world_title="The Iron Marches",
        room=MediaRoomSnapshot(
            id="castle",
            title="Lower Gaol",
            description="a castle dungeon with wet stone walls",
            indoor=True,
        ),
        characters=(
            MediaEntitySnapshot(
                id="character:rabbit",
                name="Juniper",
                role="primary_actor",
                appearance="grey fur and a weathered red scarf",
            ),
        ),
        events=(
            MediaEventSnapshot(
                id="lever",
                event_type="LeverPulledEvent",
                summary="Juniper pulls the rusted gate lever",
                epoch=7,
            ),
        ),
    )


def test_scene_prompt_context_is_bounded_valid_json_and_keeps_focus():
    scene = _scene().model_copy(
        update={
            "world_description": "world " * 20_000,
            "objects": tuple(
                MediaEntitySnapshot(
                    id=f"object:{index}",
                    name=f"background object {index}",
                    description="ornate background detail " * 1_000,
                )
                for index in range(20)
            ),
        }
    )
    context = scene.prompt_context()
    decoded = json.loads(context)
    assert len(context) <= MAX_SCENE_CONTEXT_CHARS
    assert decoded["primary_event_id"] == "lever"
    assert decoded["room"]["title"] == "Lower Gaol"


def test_scene_prompt_context_bounds_room_only_scene():
    scene = MediaSceneSnapshot(
        captured_at_epoch=1,
        viewer_id="viewer",
        world_description="world " * 20_000,
        room=MediaRoomSnapshot(id="room", title="Dungeon"),
    )
    decoded = json.loads(scene.prompt_context())
    assert decoded["characters"] == []
    assert decoded["events"] == []


# --- stub enhancer -------------------------------------------------------------------


async def test_stub_enhancer_natural():
    enhancer = StubPromptEnhancer()
    assert isinstance(enhancer, PromptEnhancer)
    result = await enhancer.enhance_image(_request(PromptStyle.NATURAL))
    assert result.style is PromptStyle.NATURAL
    assert "a brave rabbit ranger" in result.prompt
    assert "portrait" in result.prompt
    assert result.tags == ()


async def test_stub_enhancer_natural_empty_subject():
    enhancer = StubPromptEnhancer()
    result = await enhancer.enhance_image(
        ImagePromptRequest(subject="   ", style=PromptStyle.NATURAL, purpose=ImagePurpose.ENTITY)
    )
    # Falls back to the bare purpose hint when there is no subject text.
    assert result.prompt == "a single object on a plain background"


async def test_stub_enhancer_tags():
    enhancer = StubPromptEnhancer()
    result = await enhancer.enhance_image(_request(PromptStyle.TAG, ImagePurpose.SPRITE))
    assert result.style is PromptStyle.TAG
    assert result.tags[0] == "sprite"
    assert "rabbit" in result.prompt
    # Deterministic, de-duplicated word tags.
    assert result.prompt == ", ".join(result.tags)


def test_tag_normalization_supports_weights_limits_and_rejects_bad_values():
    tags = normalize_tags(
        (
            "(Grey Fur:1.25)",
            "Grey Fur",
            "one_two_three_four_five_six_seven_eight_nine_ten_eleven",
            "!",
            *(f"tag-{index}" for index in range(140)),
        )
    )
    assert tags[0] == "(grey_fur:1.25)"
    assert "grey_fur" in tags
    assert len(tags) == 128


# --- catalog example source ----------------------------------------------------------


def test_default_catalog_ships_examples():
    catalog = default_catalog()
    assert (MediaKind.IMAGE, PromptStyle.NATURAL, ImagePurpose.PORTRAIT) in catalog
    assert (MediaKind.IMAGE, PromptStyle.TAG, ImagePurpose.SPRITE) in catalog
    assert (MediaKind.VIDEO, PromptStyle.NATURAL, ImagePurpose.EVENT) in catalog
    sprite = catalog[(MediaKind.IMAGE, PromptStyle.TAG, ImagePurpose.SPRITE)]
    assert sprite[0].tags  # tag examples carry structured tags


def test_load_catalog_from_skips_non_json(tmp_path):
    (tmp_path / "natural-entity.json").write_text(json.dumps([{"prompt": "a chest"}]))
    (tmp_path / "readme.txt").write_text("ignore")
    catalog = load_catalog_from(tmp_path)
    key = (MediaKind.IMAGE, PromptStyle.NATURAL, ImagePurpose.ENTITY)
    assert list(catalog) == [key]
    assert catalog[key][0].style is PromptStyle.NATURAL


def test_load_catalog_rejects_bad_filename_and_non_list(tmp_path):
    (tmp_path / "too-many-name-parts.json").write_text("[]")
    with pytest.raises(ValueError, match="invalid prompt-example filename"):
        load_catalog_from(tmp_path)
    (tmp_path / "too-many-name-parts.json").unlink()
    (tmp_path / "natural-event.json").write_text("{}")
    with pytest.raises(ValueError, match="must be a list"):
        load_catalog_from(tmp_path)


def test_catalog_example_source_exact_match_and_limit():
    source = CatalogExampleSource(limit=2)
    assert isinstance(source, PromptExampleSource)
    examples = source.examples_for(PromptStyle.NATURAL, ImagePurpose.PORTRAIT, "anything")
    assert len(examples) == 2
    assert all(e.style is PromptStyle.NATURAL for e in examples)


def test_catalog_example_source_style_fallback():
    # A catalog with no exact (style, purpose) entry falls back to other examples of the style.
    catalog = {
        (PromptStyle.TAG, ImagePurpose.SPRITE): [
            GeneratedPrompt(style=PromptStyle.TAG, prompt="1girl, rabbit")
        ]
    }
    source = CatalogExampleSource(catalog)
    examples = source.examples_for(PromptStyle.TAG, ImagePurpose.PORTRAIT, "anything")
    assert examples
    assert all(e.style is PromptStyle.TAG for e in examples)


def test_default_catalog_covers_both_styles_for_every_purpose():
    catalog = CatalogExampleSource()
    for purpose in ImagePurpose:
        for style in (PromptStyle.TAG, PromptStyle.NATURAL):
            assert catalog.examples_for(style, purpose, "x"), (style, purpose)


def test_catalog_example_source_empty_when_no_style():
    only = {
        (PromptStyle.NATURAL, ImagePurpose.ENTITY): [
            GeneratedPrompt(style=PromptStyle.NATURAL, prompt="x")
        ]
    }
    source = CatalogExampleSource(only)
    assert source.examples_for(PromptStyle.TAG, ImagePurpose.SPRITE, "x") == []


# --- vector example source -----------------------------------------------------------


class _FakeCollection:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    def query(self, *, query_texts, n_results, where):
        self.calls.append({"query_texts": query_texts, "n_results": n_results, "where": where})
        return self.result


def test_vector_example_source_parses_results():
    collection = _FakeCollection(
        {
            "documents": [["1girl, rabbit", "1boy, fox"]],
            "metadatas": [[{"negative": "blurry", "tags": "1girl,rabbit"}, None]],
        }
    )
    source = VectorExampleSource(collection, limit=5)
    examples = source.examples_for(PromptStyle.TAG, ImagePurpose.SPRITE, "a rabbit")
    assert collection.calls[0]["where"] == {
        "media": "image",
        "style": "tag",
        "purpose": "sprite",
    }
    assert examples[0].prompt == "1girl, rabbit"
    assert examples[0].negative == "blurry"
    assert examples[0].tags == ("1girl", "rabbit")
    # Missing metadata row is tolerated.
    assert examples[1].prompt == "1boy, fox"
    assert examples[1].tags == ()


def test_vector_example_source_uses_fallback_when_empty():
    fallback = CatalogExampleSource()
    empty = _FakeCollection({"documents": [[]], "metadatas": [[]]})
    source = VectorExampleSource(empty, fallback=fallback)
    examples = source.examples_for(PromptStyle.NATURAL, ImagePurpose.PORTRAIT, "x")
    assert examples  # came from the catalog fallback


def test_vector_example_source_empty_without_fallback():
    source = VectorExampleSource(_FakeCollection({}))
    assert source.examples_for(PromptStyle.NATURAL, ImagePurpose.PORTRAIT, "x") == []


def test_vector_example_source_ignores_non_list_and_non_string_documents():
    non_lists = VectorExampleSource(
        _FakeCollection({"documents": {}, "metadatas": {}})
    )
    assert non_lists.examples_for(PromptStyle.NATURAL, ImagePurpose.EVENT, "x") == []
    mixed = VectorExampleSource(
        _FakeCollection({"documents": [[7, "valid"]], "metadatas": [[{}, {}]]})
    )
    assert [item.prompt for item in mixed.examples_for(
        PromptStyle.NATURAL, ImagePurpose.EVENT, "x"
    )] == ["valid"]


@pytest.mark.parametrize(
    "result",
    (
        {"documents": [["valid"]], "metadatas": [{}]},
        {"documents": [{}], "metadatas": [[{}]]},
    ),
)
def test_vector_example_source_requires_parallel_result_lists(result):
    source = VectorExampleSource(_FakeCollection(result))
    assert source.examples_for(PromptStyle.NATURAL, ImagePurpose.EVENT, "x") == []


# --- LLM enhancer --------------------------------------------------------------------


class _FakeOllamaClient:
    last_messages: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs

    async def chat(self, *, model, format, messages):
        type(self).last_messages = messages
        type(self).last_model = model
        type(self).last_format = format
        content = json.dumps({"prompt": "enhanced rabbit", "negative": "blurry"})
        return {"message": {"content": content}}


def _install_fake_ollama(monkeypatch, client_cls=_FakeOllamaClient):
    module = types.ModuleType("ollama")
    module.AsyncClient = client_cls
    monkeypatch.setitem(sys.modules, "ollama", module)


async def test_llm_enhancer_includes_examples_and_validates(monkeypatch):
    _install_fake_ollama(monkeypatch)
    enhancer = LLMPromptEnhancer()
    examples = [GeneratedPrompt(style=PromptStyle.NATURAL, prompt="example portrait line")]
    request = _request(PromptStyle.NATURAL, extra="moody lighting")
    result = await enhancer.enhance_image(request, examples=examples)
    assert result.prompt == "enhanced rabbit"
    assert result.negative == "blurry"
    assert result.style is PromptStyle.NATURAL
    user_content = _FakeOllamaClient.last_messages[1]["content"]
    assert "example portrait line" in user_content
    assert "moody lighting" in user_content
    assert _FakeOllamaClient.last_format == "json"


async def test_llm_enhancer_tag_system_prompt(monkeypatch):
    _install_fake_ollama(monkeypatch)
    enhancer = LLMPromptEnhancer()
    await enhancer.enhance_image(_request(PromptStyle.TAG))
    system_content = _FakeOllamaClient.last_messages[0]["content"]
    assert "WD14" in system_content or "danbooru" in system_content


async def test_llm_enhancer_uses_host_and_api_key(monkeypatch):
    _install_fake_ollama(monkeypatch)
    enhancer = LLMPromptEnhancer(host="https://comfy.example", api_key="secret")
    assert enhancer._client._client.init_kwargs["headers"] == {
        "Authorization": "Bearer secret"
    }


async def test_llm_enhancer_receives_full_scene_and_records_grounding(monkeypatch):
    class GroundedClient(_FakeOllamaClient):
        async def chat(self, *, model, format, messages):
            type(self).last_messages = messages
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "prompt": "Juniper pulls a lever in the Lower Gaol",
                            "negative": "modern objects",
                            "grounding_fact_ids": [
                                "room:castle",
                                "event:lever",
                            ],
                        }
                    )
                }
            }

    _install_fake_ollama(monkeypatch, GroundedClient)
    result = await LLMPromptEnhancer().enhance_image(
        _request(PromptStyle.NATURAL, ImagePurpose.EVENT, scene=_scene())
    )
    user_content = GroundedClient.last_messages[1]["content"]
    assert "castle dungeon with wet stone walls" in user_content
    assert "grey fur and a weathered red scarf" in user_content
    assert result.enhancer == "llm"
    assert result.fallback is False
    assert result.grounding_fact_ids == ("room:castle", "event:lever")


async def test_llm_enhancer_accepts_prompt_when_grounding_metadata_is_missing(monkeypatch):
    _install_fake_ollama(monkeypatch)
    result = await LLMPromptEnhancer().enhance_image(
        _request(PromptStyle.NATURAL, ImagePurpose.EVENT, scene=_scene())
    )
    assert result.prompt == "enhanced rabbit"
    assert result.fallback is False
    assert result.enhancer == "llm"
    assert result.grounding_fact_ids == ()


async def test_structured_scene_renderers_cover_prose_context_tags_and_adapters():
    scene = _scene().model_copy(
        update={
            "world_description": "a low-magic frontier realm",
            "characters": (
                *_scene().characters,
                MediaEntitySnapshot(
                    id="witness",
                    name="Witness",
                    role="background",
                    species="fox",
                ),
            ),
            "objects": (
                MediaEntitySnapshot(id="torch", name="Wall Torch", kind="prop"),
            ),
            "events": (
                MediaEventSnapshot(
                    id="lead-in",
                    event_type="DoorOpenedEvent",
                    summary="The gate begins to rise",
                    epoch=6,
                ),
                *_scene().events,
            ),
        }
    )
    enhancer = StructuredPromptEnhancer()
    image = await enhancer.enhance(
        ImagePromptRequest(
            subject="ignored",
            style=PromptStyle.NATURAL,
            purpose=ImagePurpose.EVENT,
            scene=scene,
            extra="low angle",
        )
    )
    video = await enhancer.enhance_video(
        VideoPromptRequest(
            subject="ignored",
            style=PromptStyle.NATURAL,
            scene=scene,
            extra="slow dolly",
        )
    )
    tag_video = await enhancer.enhance_video(
        VideoPromptRequest(
            subject="rabbit opens gate",
            style=PromptStyle.TAG,
            extra="rain streaks",
        )
    )
    assert "World context" in image.prompt
    assert "Other visible characters: Witness" in image.prompt
    assert "Wall Torch" in image.prompt
    assert "low angle" in image.prompt
    assert "Lead-in: The gate begins to rise" in video.prompt
    assert "slow dolly" in video.prompt
    assert "rain_streaks" in tag_video.tags


async def test_scene_tag_renderer_can_drop_excess_background_entities():
    scene = _scene().model_copy(
        update={
            "room": _scene().room.model_copy(
                update={
                    "facts": tuple(
                        MediaFact(
                            id=f"fact-{index}",
                            category="visual",
                            text=f"room detail {index}",
                        )
                        for index in range(80)
                    )
                }
            ),
            "characters": (
                *_scene().characters,
                MediaEntitySnapshot(id="background", name="Background", role="background"),
            ),
        }
    )
    result = await StructuredPromptEnhancer().enhance_image(
        ImagePromptRequest(
            subject="ignored",
            style=PromptStyle.TAG,
            purpose=ImagePurpose.EVENT,
            scene=scene,
        )
    )
    assert "multiple_characters" in result.tags
    assert "background" not in result.tags


class _ContentClient(_FakeOllamaClient):
    content = "{}"
    object_response = False

    async def chat(self, *, model, format, messages):
        type(self).last_messages = messages
        if self.object_response:
            return types.SimpleNamespace(message=types.SimpleNamespace(content=self.content))
        return {"message": {"content": self.content}}


@pytest.mark.parametrize(
    "content",
    (
        "not json",
        json.dumps({"prompt": ""}),
        json.dumps({"prompt": "valid", "negative": []}),
        json.dumps({"prompt": "x" * 4_001}),
    ),
)
async def test_llm_natural_validation_failures_use_structured_fallback(
    monkeypatch, content
):
    _ContentClient.content = content
    _ContentClient.object_response = False
    _install_fake_ollama(monkeypatch, _ContentClient)
    result = await LLMPromptEnhancer().enhance_image(_request(PromptStyle.NATURAL))
    assert result.fallback is True


@pytest.mark.parametrize(
    "content",
    (
        json.dumps({"tags": "rabbit", "negative_tags": []}),
        json.dumps({"tags": [], "negative_tags": []}),
    ),
)
async def test_llm_tag_validation_failures_use_tag_fallback(monkeypatch, content):
    _ContentClient.content = content
    _ContentClient.object_response = False
    _install_fake_ollama(monkeypatch, _ContentClient)
    result = await LLMPromptEnhancer().enhance_image(_request(PromptStyle.TAG))
    assert result.style is PromptStyle.TAG
    assert result.fallback is True


async def test_llm_tag_and_video_success_and_object_response(monkeypatch):
    _ContentClient.content = json.dumps(
        {
            "tags": ["Grey Fur", 7],
            "negative_tags": ["blurry"],
            "grounding_fact_ids": [],
        }
    )
    _ContentClient.object_response = True
    _install_fake_ollama(monkeypatch, _ContentClient)
    enhancer = LLMPromptEnhancer()
    tag = await enhancer.enhance_image(_request(PromptStyle.TAG))
    assert tag.tags == ("grey_fur",)
    assert tag.negative == "blurry"

    _ContentClient.content = json.dumps(
        {"prompt": "A gate rises through the rain", "negative": "jitter"}
    )
    video = await enhancer.enhance_video(
        VideoPromptRequest(subject="a gate rises", style=PromptStyle.NATURAL)
    )
    assert video.prompt == "A gate rises through the rain"
    assert "text-to-video" in _ContentClient.last_messages[0]["content"]


async def test_llm_missing_response_content_uses_fallback(monkeypatch):
    class MissingContent(_FakeOllamaClient):
        async def chat(self, *, model, format, messages):
            del model, format, messages
            return {"message": {}}

    _install_fake_ollama(monkeypatch, MissingContent)
    result = await LLMPromptEnhancer().enhance_image(_request(PromptStyle.NATURAL))
    assert result.fallback is True


@pytest.mark.parametrize(
    "response",
    (
        {"message": "not-an-object"},
        {"message": {"content": 7}},
    ),
)
async def test_llm_malformed_response_shapes_use_fallback(monkeypatch, response):
    class MalformedResponse(_FakeOllamaClient):
        async def chat(self, *, model, format, messages):
            del model, format, messages
            return response

    _install_fake_ollama(monkeypatch, MalformedResponse)
    result = await LLMPromptEnhancer().enhance_image(_request(PromptStyle.NATURAL))
    assert result.fallback is True


async def test_llm_non_mapping_response_without_content_uses_fallback(monkeypatch):
    class MissingObjectContent(_FakeOllamaClient):
        async def chat(self, *, model, format, messages):
            del model, format, messages
            return types.SimpleNamespace()

    _install_fake_ollama(monkeypatch, MissingObjectContent)
    result = await LLMPromptEnhancer().enhance_image(_request(PromptStyle.NATURAL))
    assert result.fallback is True


async def test_llm_provider_failure_and_video_validation_use_fallback(monkeypatch):
    class FailedProvider(_FakeOllamaClient):
        async def chat(self, *, model, format, messages):
            del model, format, messages
            raise RuntimeError("provider unavailable")

    _install_fake_ollama(monkeypatch, FailedProvider)
    enhancer = LLMPromptEnhancer()
    image = await enhancer.enhance(_request(PromptStyle.NATURAL))
    assert image.fallback is True

    _ContentClient.content = "not json"
    _ContentClient.object_response = False
    _install_fake_ollama(monkeypatch, _ContentClient)
    video = await LLMPromptEnhancer().enhance_video(
        VideoPromptRequest(subject="a gate rises", style=PromptStyle.NATURAL)
    )
    assert video.fallback is True
    assert "action unfolding" in video.prompt


async def test_structured_enhancer_has_distinct_video_motion_prompt():
    enhancer = StructuredPromptEnhancer()
    result = await enhancer.enhance_video(
        VideoPromptRequest(
            subject="a rabbit opens a dungeon gate",
            style=PromptStyle.NATURAL,
        )
    )
    assert "action unfolding" in result.prompt
    assert "camera" in result.prompt
    assert result.enhancer == "structured"


async def test_structured_tag_scene_without_primary_event_uses_room_context():
    scene = _scene().model_copy(update={"primary_event_id": "", "events": ()})
    result = await StructuredPromptEnhancer().enhance_image(
        ImagePromptRequest(
            subject="the room",
            style=PromptStyle.TAG,
            purpose=ImagePurpose.EVENT,
            scene=scene,
        )
    )
    assert "lower_gaol" in result.tags


async def test_llm_enhancer_requires_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", None)
    with pytest.raises(RuntimeError, match="requires the 'llm' extra"):
        LLMPromptEnhancer()
