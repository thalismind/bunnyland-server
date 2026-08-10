"""Local sandbox LLM launcher tests."""

from __future__ import annotations

import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

from bunnyland.core import CharacterComponent, IdentityComponent, SuspendedComponent
from bunnyland.core.controllers import LLMControllerComponent
from bunnyland.core.edges import ControlledBy
from bunnyland.persistence import load_world
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.sandbox.generation import REPRESENTATIVE_LLM_ACT_EVERY_TICKS

SCRIPT = Path(__file__).parents[1] / "scripts" / "launch_sandbox_llm.py"
REPRESENTATIVES = {
    "Yarrow the Steward",
    "Clover the Neighbor",
    "Kestrel the Trainer",
    "Moth the Rumormonger",
    "Button the Juvenile",
}


def _load_launcher() -> ModuleType:
    loader = SourceFileLoader("bunnyland_sandbox_launcher_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


LAUNCHER = _load_launcher()


@pytest.mark.asyncio
async def test_prepare_sandbox_world_assigns_only_representatives(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.json"

    prepared = await LAUNCHER.prepare_sandbox_world(
        path,
        seed="launcher test",
        provider="openrouter",
        model="example/model",
    )

    actor, meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    assert meta.generator == "bunnyland-sandbox"
    assert set(prepared.representative_names) == REPRESENTATIVES
    assert path.with_suffix(".json.sha256").is_file()

    assigned_controller_ids = set()
    arrivals = []
    for character in actor.world.query().with_all([CharacterComponent]).execute_entities():
        identity = character.get_component(IdentityComponent)
        if identity.name in REPRESENTATIVES:
            _edge, controller_id = character.get_relationships(ControlledBy)[0]
            controller = actor.world.get_entity(controller_id)
            llm = controller.get_component(LLMControllerComponent)
            assigned_controller_ids.add(controller_id)
            assert llm.provider == "openrouter"
            assert llm.model == "example/model"
            assert llm.act_every_ticks == REPRESENTATIVE_LLM_ACT_EVERY_TICKS
            assert not character.has_component(SuspendedComponent)
        elif identity.name.startswith("New Arrival "):
            arrivals.append(character)

    assert len(assigned_controller_ids) == len(REPRESENTATIVES)
    assert len(arrivals) == 4
    assert all(character.has_component(SuspendedComponent) for character in arrivals)


@pytest.mark.asyncio
async def test_prepare_sandbox_world_refuses_existing_output(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.json"
    path.write_text("existing")

    with pytest.raises(FileExistsError):
        await LAUNCHER.prepare_sandbox_world(
            path,
            seed="launcher test",
            provider="openrouter",
            model="example/model",
        )


def test_launcher_prepare_only_reuse_and_argument_validation(tmp_path: Path) -> None:
    path = tmp_path / "prepared.json"
    path.write_text("existing")

    assert LAUNCHER.main(
        [
            "--world",
            str(path),
            "--character-model",
            "example/model",
            "--reuse",
            "--prepare-only",
        ]
    ) == 0

    with pytest.raises(SystemExit) as missing:
        LAUNCHER.main(
            [
                "--world",
                str(tmp_path / "missing.json"),
                "--character-model",
                "example/model",
                "--reuse",
            ]
        )
    assert missing.value.code == 2


def test_launcher_builds_bounded_local_server_arguments(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "prepared.json"
    path.write_text("existing")
    seen = []

    def fake_main(arguments):
        seen.extend(arguments)
        return 17

    monkeypatch.setattr(LAUNCHER, "bunnyland_main", fake_main)

    result = LAUNCHER.main(
        [
            "--world",
            str(path),
            "--character-model",
            "example/model",
            "--reuse",
            "--character-chat",
            "--quiet",
            "--ticks",
            "2",
        ]
    )

    assert result == 17
    assert seen[:5] == ["serve", "--load", str(path), "--save", str(path)]
    assert "--llm" in seen
    assert "--character-chat" in seen
    assert "--verbose" not in seen
    assert seen[seen.index("--ticks") + 1] == "2"


def test_launcher_refuses_existing_output_without_explicit_policy(tmp_path: Path) -> None:
    path = tmp_path / "prepared.json"
    path.write_text("existing")

    with pytest.raises(SystemExit) as existing:
        LAUNCHER.main(
            [
                "--world",
                str(path),
                "--character-model",
                "example/model",
            ]
        )
    assert existing.value.code == 2
