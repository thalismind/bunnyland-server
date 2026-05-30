"""CLI plugin selection and metadata behavior."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from bunnyland.cli import main, select_plugins
from bunnyland.persistence import WorldMeta, load_world
from bunnyland.plugins import DependencyContribution, Plugin
from bunnyland.plugins.builtin import CORE_VERBS, WORLDGEN


def _install_module(monkeypatch, name: str, plugins: list[Plugin]) -> None:
    module = ModuleType(name)
    module.bunnyland_plugins = lambda: plugins
    monkeypatch.setitem(sys.modules, name, module)


def test_select_plugins_records_imported_module_namespace(monkeypatch):
    _install_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])

    selected = select_plugins(["module_foo"], ["bar"])

    assert [plugin.id for plugin in selected] == ["module_foo.bar"]


def test_missing_required_plugin_logs_error_and_exits(monkeypatch, caplog):
    _install_module(
        monkeypatch,
        "module_foo",
        [
            Plugin(
                id="bar",
                name="Bar",
                dependencies=DependencyContribution(requires=("missing",)),
            )
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main(["serve", "--import", "module_foo", "--plugin", "bar"])

    assert exc.value.code == 2
    assert "plugin loading failed" in caplog.text
    assert "module_foo.missing" in caplog.text


def test_world_meta_can_record_loaded_plugin_ids():
    meta = WorldMeta(plugins=(CORE_VERBS, "module_foo.bar"))

    assert meta.plugins == (CORE_VERBS, "module_foo.bar")


def test_cli_save_records_namespaced_imported_plugin(monkeypatch, tmp_path):
    _install_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])
    path = tmp_path / "world.json"

    result = main(
        [
            "serve",
            "--import",
            "module_foo",
            "--plugin",
            WORLDGEN,
            "--plugin",
            "bar",
            "--ticks",
            "1",
            "--save",
            str(path),
        ]
    )

    assert result == 0
    _actor, meta = load_world(path)
    assert meta.plugins == (WORLDGEN, "module_foo.bar")
