"""Tests for external scripting definitions and runtime execution."""

from __future__ import annotations

from pathlib import Path

from conftest import build_scenario

from bunnyland.core import CommandCost, Lane, build_submitted_command, container_of
from bunnyland.core.components import IdentityComponent
from bunnyland.core.events import SpeechSaidEvent
from bunnyland.plugins import ContentContribution, Plugin, apply_plugins, bunnyland_plugins
from bunnyland.plugins.builtin import CORE_VERBS
from bunnyland.scripting import (
    ComponentSpec,
    EntityQuery,
    ScriptBlock,
    ScriptBlockState,
    ScriptDefinition,
    ScriptRuntime,
    SubmitCommandAction,
    TargetSelector,
    Trigger,
    collect_scripts,
    load_script,
    load_script_state,
    write_script_state,
)
from bunnyland.scripting.model import AddEntityPatch, PatchWorldAction


async def test_epoch_trigger_submits_normal_command_once():
    scenario = build_scenario()
    apply_plugins([p for p in bunnyland_plugins() if p.id == CORE_VERBS], scenario.actor)
    speeches: list[SpeechSaidEvent] = []
    scenario.actor.bus.subscribe(SpeechSaidEvent, speeches.append)

    script = ScriptDefinition(
        id="test.epoch",
        blocks=(
            ScriptBlock(
                name="bell",
                trigger=Trigger(epoch_at_least=5),
                actions=(
                    SubmitCommandAction(
                        target=TargetSelector(
                            query=EntityQuery(
                                components=("CharacterComponent",),
                                identity_name="Juniper",
                            )
                        ),
                        command_type="say",
                        payload={"text": "The fifth second bell rings."},
                    ),
                ),
            ),
        ),
    )
    runtime = ScriptRuntime([script]).install(scenario.actor)

    await scenario.actor.tick(5.0)
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(5.0)

    assert [event.text for event in speeches] == ["The fifth second bell rings."]
    assert runtime.state.blocks["test.epoch:bell"].count == 1


async def test_event_trigger_can_patch_world_with_bindings():
    scenario = build_scenario()
    apply_plugins([p for p in bunnyland_plugins() if p.id == CORE_VERBS], scenario.actor)
    script = ScriptDefinition(
        id="test.move-patch",
        blocks=(
            ScriptBlock(
                name="arrival",
                trigger=Trigger(
                    event_type="ActorMovedEvent",
                    event_fields={"to_room_id": "$room_b"},
                ),
                actions=(
                    PatchWorldAction(
                        operations=(
                            AddEntityPatch(
                                bind="bell",
                                contain_in=EntityQuery(id="$room_b"),
                                components=(
                                    ComponentSpec(
                                        type="IdentityComponent",
                                        fields={"name": "arrival bell", "kind": "item"},
                                    ),
                                ),
                            ),
                        )
                    ),
                ),
            ),
        ),
    )
    runtime = ScriptRuntime([script], bindings={"room_b": str(scenario.room_b)}).install(
        scenario.actor
    )

    await scenario.actor.submit(
        build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="move",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"direction": "north"},
        )
    )
    await scenario.actor.tick(0.0)

    bell_id = runtime.bindings["bell"]
    bell = scenario.actor.world.get_entity(
        next(
            entity.id
            for entity in scenario.actor.world.query().execute_entities()
            if str(entity.id) == bell_id
        )
    )
    assert bell.get_component(IdentityComponent).name == "arrival bell"
    assert container_of(bell) == scenario.room_b


def test_standalone_script_json_and_state_round_trip(tmp_path: Path):
    script = ScriptDefinition(
        id="test.file",
        blocks=(ScriptBlock(name="tick", trigger=Trigger(tick=True)),),
    )
    path = tmp_path / "script.json"
    path.write_text(script.model_dump_json(indent=2))

    loaded = load_script(path)
    runtime = ScriptRuntime([loaded])
    runtime.state.blocks["test.file:tick"] = ScriptBlockState(count=1, last_fired_epoch=7)

    state_path = tmp_path / "script-state.json"
    write_script_state(state_path, runtime.state)
    assert load_script_state(state_path).model_dump() == runtime.state.model_dump()


def test_plugin_script_contributions_are_collectable():
    script = ScriptDefinition(
        id="plugin.script",
        blocks=(ScriptBlock(name="tick", trigger=Trigger(tick=True)),),
    )
    plugin = Plugin(
        id="example",
        name="Example",
        content=ContentContribution(scripts=(script,)),
    )

    assert collect_scripts([plugin]) == [script]


def test_example_scripts_are_valid():
    root = Path(__file__).resolve().parents[1]
    scripts = [
        load_script(root / "examples/scripts/epoch_bell.json"),
        load_script(root / "examples/scripts/move_arrival_patch.json"),
        load_script(root / "examples/scripts/llm_only_prompt.json"),
    ]

    assert [script.id for script in scripts] == [
        "examples.epoch_bell",
        "examples.move_arrival_patch",
        "examples.llm_only_prompt",
    ]
