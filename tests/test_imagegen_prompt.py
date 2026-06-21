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
    StubPromptEnhancer,
    VectorExampleSource,
    default_catalog,
    load_catalog_from,
)
from bunnyland.imagegen.spec import (
    GeneratedPrompt,
    ImagePurpose,
    PromptStyle,
)


def _request(style: PromptStyle, purpose=ImagePurpose.PORTRAIT, **kw) -> ImagePromptRequest:
    return ImagePromptRequest(subject="a brave rabbit ranger", style=style, purpose=purpose, **kw)


# --- stub enhancer -------------------------------------------------------------------


async def test_stub_enhancer_natural():
    enhancer = StubPromptEnhancer()
    assert isinstance(enhancer, PromptEnhancer)
    result = await enhancer.enhance(_request(PromptStyle.NATURAL))
    assert result.style is PromptStyle.NATURAL
    assert "a brave rabbit ranger" in result.prompt
    assert "portrait" in result.prompt
    assert result.tags == ()


async def test_stub_enhancer_natural_empty_subject():
    enhancer = StubPromptEnhancer()
    result = await enhancer.enhance(
        ImagePromptRequest(subject="   ", style=PromptStyle.NATURAL, purpose=ImagePurpose.ENTITY)
    )
    # Falls back to the bare purpose hint when there is no subject text.
    assert result.prompt == "a single object on a plain background"


async def test_stub_enhancer_tags():
    enhancer = StubPromptEnhancer()
    result = await enhancer.enhance(_request(PromptStyle.TAG, ImagePurpose.SPRITE))
    assert result.style is PromptStyle.TAG
    assert result.tags[0] == "sprite"
    assert "rabbit" in result.tags
    # Deterministic, de-duplicated word tags.
    assert result.prompt == ", ".join(result.tags)


# --- catalog example source ----------------------------------------------------------


def test_default_catalog_ships_examples():
    catalog = default_catalog()
    assert (PromptStyle.NATURAL, ImagePurpose.PORTRAIT) in catalog
    assert (PromptStyle.TAG, ImagePurpose.SPRITE) in catalog
    sprite = catalog[(PromptStyle.TAG, ImagePurpose.SPRITE)]
    assert sprite[0].tags  # tag examples carry structured tags


def test_load_catalog_from_skips_non_json(tmp_path):
    (tmp_path / "natural-entity.json").write_text(json.dumps([{"prompt": "a chest"}]))
    (tmp_path / "readme.txt").write_text("ignore")
    catalog = load_catalog_from(tmp_path)
    assert list(catalog) == [(PromptStyle.NATURAL, ImagePurpose.ENTITY)]
    assert catalog[(PromptStyle.NATURAL, ImagePurpose.ENTITY)][0].style is PromptStyle.NATURAL


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
    assert collection.calls[0]["where"] == {"style": "tag", "purpose": "sprite"}
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
    result = await enhancer.enhance(request, examples=examples)
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
    await enhancer.enhance(_request(PromptStyle.TAG))
    system_content = _FakeOllamaClient.last_messages[0]["content"]
    assert "WD14" in system_content or "danbooru" in system_content


async def test_llm_enhancer_uses_host_and_api_key(monkeypatch):
    _install_fake_ollama(monkeypatch)
    enhancer = LLMPromptEnhancer(host="https://comfy.example", api_key="secret")
    assert enhancer._client.init_kwargs["headers"] == {"Authorization": "Bearer secret"}


async def test_llm_enhancer_requires_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", None)
    with pytest.raises(RuntimeError, match="requires the 'llm' extra"):
        LLMPromptEnhancer()
