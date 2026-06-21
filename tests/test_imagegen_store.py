"""Tests for the ComfyUI workflow template store and shipped defaults."""

from __future__ import annotations

import json

from bunnyland.imagegen.spec import ImagePurpose, WorkflowTemplate, substitute
from bunnyland.imagegen.store import (
    WorkflowTemplateStore,
    default_templates,
    load_templates_from,
)


def _template(name: str, purpose: ImagePurpose = ImagePurpose.PORTRAIT) -> WorkflowTemplate:
    return WorkflowTemplate(
        name=name,
        purpose=purpose,
        graph={"1": {"inputs": {"text": "%PROMPT%", "seed": 0}}},
    )


def test_default_templates_ship_one_per_purpose():
    templates = default_templates()
    by_name = {t.name: t for t in templates}
    assert set(by_name) == {"portrait", "entity", "sprite", "event"}
    assert {t.purpose for t in templates} == set(ImagePurpose)
    # The shipped graphs are real and substitutable end-to-end.
    graph = substitute(by_name["portrait"], prompt="a brave rabbit", seed=7)
    assert graph["6"]["inputs"]["text"] == "a brave rabbit"
    assert graph["3"]["inputs"]["seed"] == 7


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
