"""Tests for imagegen workflow templates and prompt substitution."""

from __future__ import annotations

import pytest

from bunnyland.imagegen.spec import (
    GeneratedPrompt,
    ImagePurpose,
    MediaKind,
    PromptStyle,
    SubstitutionSlot,
    WorkflowTemplate,
    substitute,
)


def _template(**overrides) -> WorkflowTemplate:
    base = {
        "name": "portrait",
        "purpose": ImagePurpose.PORTRAIT,
        "graph": {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a %PROMPT%, masterpiece"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "%NEGATIVE%"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 0, "height": 0}},
        },
        "slots": (
            SubstitutionSlot(node_id="3", field_path=("inputs", "seed"), token="%SEED%"),
            SubstitutionSlot(node_id="4", field_path=("inputs", "width"), token="%WIDTH%"),
            SubstitutionSlot(node_id="4", field_path=("inputs", "height"), token="%HEIGHT%"),
        ),
        "default_negative": "blurry",
        "width": 512,
        "height": 768,
    }
    base.update(overrides)
    return WorkflowTemplate(**base)


def test_template_defaults():
    template = WorkflowTemplate(name="t", purpose=ImagePurpose.ENTITY)
    assert template.prompt_style is PromptStyle.NATURAL
    assert template.media is MediaKind.IMAGE
    assert template.width == 1024
    assert template.height == 1024
    assert template.graph == {}
    assert template.slots == ()
    assert template.output_node_id == ""
    assert template.enhancer == ""


def test_field_path_coerced_to_tuple():
    slot = SubstitutionSlot(node_id="1", field_path=["inputs", "text"], token="%PROMPT%")
    assert slot.field_path == ("inputs", "text")


def test_substitute_replaces_literal_tokens_and_slots():
    template = _template()
    graph = substitute(template, prompt="rabbit knight", seed=42)
    # Literal token inside a string field.
    assert graph["1"]["inputs"]["text"] == "a rabbit knight, masterpiece"
    # Negative falls back to the template default.
    assert graph["2"]["inputs"]["text"] == "blurry"
    # Slots set native-typed values.
    assert graph["3"]["inputs"]["seed"] == 42
    assert graph["4"]["inputs"]["width"] == 512
    assert graph["4"]["inputs"]["height"] == 768
    assert isinstance(graph["3"]["inputs"]["seed"], int)


def test_substitute_does_not_mutate_template_graph():
    template = _template()
    substitute(template, prompt="x", seed=1)
    assert template.graph["1"]["inputs"]["text"] == "a %PROMPT%, masterpiece"
    assert template.graph["3"]["inputs"]["seed"] == 0


def test_substitute_overrides_negative_and_dimensions():
    template = _template()
    graph = substitute(template, prompt="x", seed=1, negative="ugly", width=256, height=256)
    assert graph["2"]["inputs"]["text"] == "ugly"
    assert graph["4"]["inputs"]["width"] == 256
    assert graph["4"]["inputs"]["height"] == 256


def test_substitute_replaces_tokens_in_lists():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": {"tags": ["%PROMPT%", "extra"], "count": 3}}},
    )
    graph = substitute(template, prompt="fox", seed=1)
    assert graph["1"]["inputs"]["tags"] == ["fox", "extra"]
    # Non-string leaves pass through untouched.
    assert graph["1"]["inputs"]["count"] == 3


def test_substitute_literal_seed_in_string():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": {"note": "seed=%SEED%"}}},
    )
    graph = substitute(template, prompt="x", seed=99)
    assert graph["1"]["inputs"]["note"] == "seed=99"


def test_substitute_rejects_unknown_token():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": {"text": ""}}},
        slots=(SubstitutionSlot(node_id="1", field_path=("inputs", "text"), token="%NOPE%"),),
    )
    with pytest.raises(ValueError, match="unknown substitution token"):
        substitute(template, prompt="x", seed=1)


def test_substitute_rejects_empty_field_path():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": {"text": ""}}},
        slots=(SubstitutionSlot(node_id="1", field_path=(), token="%PROMPT%"),),
    )
    with pytest.raises(ValueError, match="empty field path"):
        substitute(template, prompt="x", seed=1)


def test_substitute_rejects_missing_node():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": {"text": ""}}},
        slots=(SubstitutionSlot(node_id="9", field_path=("inputs", "text"), token="%PROMPT%"),),
    )
    with pytest.raises(ValueError, match="no node '9'"):
        substitute(template, prompt="x", seed=1)


def test_substitute_rejects_missing_intermediate_key():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": {"text": ""}}},
        slots=(SubstitutionSlot(node_id="1", field_path=("missing", "text"), token="%PROMPT%"),),
    )
    with pytest.raises(ValueError, match="invalid for node '1'"):
        substitute(template, prompt="x", seed=1)


def test_substitute_rejects_non_dict_intermediate():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": "not-a-dict"}},
        slots=(SubstitutionSlot(node_id="1", field_path=("inputs", "text"), token="%PROMPT%"),),
    )
    with pytest.raises(ValueError, match="invalid for node '1'"):
        substitute(template, prompt="x", seed=1)


def test_substitute_rejects_missing_final_key():
    template = WorkflowTemplate(
        name="t",
        purpose=ImagePurpose.ENTITY,
        graph={"1": {"inputs": {"other": ""}}},
        slots=(SubstitutionSlot(node_id="1", field_path=("inputs", "text"), token="%PROMPT%"),),
    )
    with pytest.raises(ValueError, match="invalid for node '1'"):
        substitute(template, prompt="x", seed=1)


def test_generated_prompt_defaults():
    prompt = GeneratedPrompt(style=PromptStyle.TAG, prompt="1girl, rabbit")
    assert prompt.negative == ""
    assert prompt.tags == ()
