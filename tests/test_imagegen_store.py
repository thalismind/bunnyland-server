"""Tests for the ComfyUI workflow template store and shipped defaults."""

from __future__ import annotations

import json

import pytest

from bunnyland.imagegen.spec import ImagePurpose, PromptStyle, WorkflowTemplate, substitute
from bunnyland.imagegen.store import (
    WorkflowTemplateStore,
    available_families,
    default_templates,
    load_templates_from,
    resolve_family,
)


def _template(name: str, purpose: ImagePurpose = ImagePurpose.PORTRAIT) -> WorkflowTemplate:
    return WorkflowTemplate(
        name=name,
        purpose=purpose,
        graph={"1": {"inputs": {"text": "%PROMPT%", "seed": 0}}},
    )


def test_default_templates_ship_one_per_purpose():
    templates = default_templates()  # the default family (anima)
    by_name = {t.name: t for t in templates}
    assert set(by_name) == {"portrait", "entity", "sprite", "event"}
    assert {t.purpose for t in templates} == set(ImagePurpose)


def test_sdxl_family_substitutes_prompt_and_seed():
    portrait = next(t for t in default_templates("sdxl") if t.name == "portrait")
    graph = substitute(portrait, prompt="a brave rabbit", seed=7)
    assert "a brave rabbit" in graph["50"]["inputs"]["text"]
    assert graph["87"]["inputs"]["noise_seed"] == 7


def test_every_family_ships_four_substitutable_purposes():
    for family in available_families():
        templates = default_templates(family)
        assert {t.name for t in templates} == {"portrait", "entity", "sprite", "event"}
        for template in templates:
            graph = substitute(template, prompt="a fox", seed=3)
            # Every family's output node exists in its substituted graph.
            assert template.output_node_id in graph


def test_available_families_and_resolution():
    families = available_families()
    assert {"anima", "sdxl", "klein", "flux2dev"} <= set(families)
    # A server's own label resolves to the base family by its first keyword.
    assert resolve_family("anima-my-server-foo") == "anima"
    assert resolve_family("flux2dev") == "flux2dev"
    with pytest.raises(ValueError, match="unknown workflow family"):
        resolve_family("bogus")


def test_default_templates_prompt_styles_match_family():
    assert all(t.prompt_style is PromptStyle.TAG for t in default_templates("anima"))
    assert all(t.prompt_style is PromptStyle.NATURAL for t in default_templates("klein"))


def test_load_templates_from_skips_non_json(tmp_path):
    (tmp_path / "good.json").write_text(_template("good").model_dump_json())
    (tmp_path / "notes.txt").write_text("ignore me")
    loaded = load_templates_from(tmp_path)
    assert [t.name for t in loaded] == ["good"]


def test_store_in_memory_without_path():
    store = WorkflowTemplateStore(defaults=[_template("portrait")])
    assert store.persistent is False
    assert store.load() == 0
    store.save()  # no-op, must not raise
    store.add_template(_template("custom", ImagePurpose.ENTITY))
    assert store.get("custom").purpose is ImagePurpose.ENTITY


def test_store_get_and_for_purpose_prefer_user():
    store = WorkflowTemplateStore(defaults=[_template("portrait")])
    user = _template("portrait")  # same name and purpose, shadows the default
    store.add_template(user)
    assert store.get("portrait") is user
    assert store.for_purpose(ImagePurpose.PORTRAIT) is user
    assert store.get("missing") is None
    assert store.for_purpose(ImagePurpose.EVENT) is None


def test_store_for_purpose_falls_back_to_default():
    default = _template("portrait")
    store = WorkflowTemplateStore(defaults=[default])
    assert store.for_purpose(ImagePurpose.PORTRAIT) is default


def test_store_persists_and_reloads(tmp_path):
    path = tmp_path / "nested" / "templates.json"
    store = WorkflowTemplateStore(path, defaults=[_template("portrait")])
    assert store.load() == 0  # missing file
    store.add_template(_template("custom", ImagePurpose.ENTITY))

    payload = json.loads(path.read_text())
    assert [t["name"] for t in payload["templates"]] == ["custom"]

    reloaded = WorkflowTemplateStore(path, defaults=[_template("portrait")])
    assert reloaded.load() == 1
    assert reloaded.get("custom").purpose is ImagePurpose.ENTITY
    # Defaults are not written back to the user file.
    assert reloaded.get("portrait") is not None


def test_store_load_skips_invalid_entry(tmp_path, caplog):
    path = tmp_path / "templates.json"
    path.write_text(
        json.dumps(
            {
                "templates": [
                    {"name": "ok", "purpose": "entity", "graph": {}},
                    {"name": "bad", "purpose": "not-a-purpose"},
                ]
            }
        )
    )
    store = WorkflowTemplateStore(path)
    with caplog.at_level("WARNING"):
        assert store.load() == 1
    assert "skipping invalid workflow template" in caplog.text
    assert store.get("ok") is not None
    assert store.get("bad") is None


def test_store_snapshot_unions_defaults_and_user():
    store = WorkflowTemplateStore(defaults=[_template("portrait"), _template("entity")])
    store.add_template(_template("custom", ImagePurpose.SPRITE))
    assert store.snapshot() == {"templates": ["custom", "entity", "portrait"]}
