"""Tests for external scripting definitions and runtime execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    Lane,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.components import IdentityComponent
from bunnyland.core.events import SpeechSaidEvent
from bunnyland.plugins import ContentContribution, Plugin, apply_plugins, bunnyland_plugins
from bunnyland.plugins.builtin import CORE_VERBS
from bunnyland.scripting import (
    AddComponentPatch,
    AddEntityPatch,
    ComponentSpec,
    EntityQuery,
    FanoutMode,
    PatchWorldAction,
    ScriptBlock,
    ScriptBlockState,
    ScriptDefinition,
    ScriptRuntime,
    ScriptRuntimeError,
    SetComponentFieldsPatch,
    SubmitCommandAction,
    TargetSelector,
    Trigger,
    collect_scripts,
    load_script,
    load_script_state,
    load_scripts,
    write_script_state,
)


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
    assert load_scripts([path]) == [loaded]


def test_plugin_script_contributions_are_collectable(tmp_path: Path):
    script = ScriptDefinition(
        id="plugin.script",
        blocks=(ScriptBlock(name="tick", trigger=Trigger(tick=True)),),
    )
    path_script = ScriptDefinition(
        id="plugin.path",
        blocks=(ScriptBlock(name="tick", trigger=Trigger(tick=True)),),
    )
    plugin_path = tmp_path / "plugin-script.json"
    plugin_path.write_text(path_script.model_dump_json())
    plugin = Plugin(
        id="example",
        name="Example",
        content=ContentContribution(
            scripts=(
                script,
                plugin_path,
                {"id": "plugin.mapping", "blocks": [{"name": "tick", "trigger": {"tick": True}}]},
            )
        ),
    )

    assert [item.id for item in collect_scripts([plugin])] == [
        "plugin.script",
        "plugin.path",
        "plugin.mapping",
    ]


def test_plugin_script_contributions_reject_unsupported_values():
    plugin = Plugin(
        id="example",
        name="Example",
        content=ContentContribution(scripts=(object(),)),
    )

    with pytest.raises(ScriptRuntimeError, match="unsupported script contribution"):
        collect_scripts([plugin])


def test_script_runtime_composed_triggers_and_event_field_matching():
    scenario = build_scenario()
    runtime = ScriptRuntime(bindings={"room": str(scenario.room_a)})
    event = SpeechSaidEvent(
        event_id="speech",
        world_epoch=0,
        created_at="2026-01-01T00:00:00Z",
        actor_id=str(scenario.character),
        room_id=str(scenario.room_a),
        text="hello",
    )

    assert runtime._triggered(scenario.actor, Trigger(all=(Trigger(tick=True),)), (), {})
    assert runtime._triggered(
        scenario.actor,
        Trigger(any=(Trigger(epoch_at_least=999), Trigger(tick=True))),
        (),
        {},
    )
    assert runtime._triggered(
        scenario.actor,
        Trigger.model_validate({"not": {"epoch_at_least": 999}}),
        (),
        {},
    )
    assert runtime._triggered(
        scenario.actor,
        Trigger(
            event_type="bunnyland.core.events.SpeechSaidEvent",
            event_fields={"room_id": "$room", "text": "hello"},
        ),
        (event,),
        runtime.bindings,
    )
    assert not runtime._triggered(
        scenario.actor,
        Trigger(event_type="SpeechSaidEvent", event_fields={"text": "goodbye"}),
        (event,),
        runtime.bindings,
    )


def test_script_runtime_selector_modes_and_query_filters():
    scenario = build_scenario()
    runtime = ScriptRuntime(bindings={"room": str(scenario.room_a)})
    ally = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character", tags=("friend", "scout")),
            CharacterComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), ally.id
    )

    first = runtime._select(
        scenario.actor,
        TargetSelector(
            query=EntityQuery(components=("CharacterComponent",), in_room="$room"),
            mode=FanoutMode.FIRST,
            bind="first",
        ),
        runtime.bindings,
    )
    each = runtime._select(
        scenario.actor,
        TargetSelector(
            query=EntityQuery(components=("CharacterComponent",), in_room="$room"),
            mode=FanoutMode.EACH,
            bind="each",
        ),
        runtime.bindings,
    )
    tagged = runtime._resolve_query(
        scenario.actor,
        EntityQuery(identity_kind="character", tags=("friend",), in_room="$room"),
        runtime.bindings,
    )
    room = runtime._resolve_query(
        scenario.actor,
        EntityQuery(room_title="Mosslit Burrow", without_components=("CharacterComponent",)),
        runtime.bindings,
    )

    assert first == [scenario.actor.world.get_entity(scenario.character)]
    assert {entity.id for entity in each} == {scenario.character, ally.id}
    assert tagged == [ally]
    assert [entity.id for entity in room] == [scenario.room_a]

    with pytest.raises(ScriptRuntimeError, match="selector 'actor' expected one match, found 2"):
        runtime._select(
            scenario.actor,
            TargetSelector(query=EntityQuery(components=("CharacterComponent",))),
            runtime.bindings,
        )

    with pytest.raises(ScriptRuntimeError, match="selector 'actor' found no matches"):
        runtime._select(
            scenario.actor,
            TargetSelector(
                query=EntityQuery(identity_name="missing"),
                mode=FanoutMode.FIRST,
            ),
            runtime.bindings,
        )


async def test_script_runtime_records_block_errors_without_marking_fired():
    scenario = build_scenario()
    script = ScriptDefinition(
        id="test.errors",
        blocks=(
            ScriptBlock(
                name="bad-patch",
                trigger=Trigger(tick=True),
                actions=(
                    PatchWorldAction(
                        operations=(
                            SetComponentFieldsPatch(
                                target=TargetSelector(
                                    query=EntityQuery(identity_name="Juniper")
                                ),
                                component_type="RoomComponent",
                                fields={"title": "Wrong"},
                            ),
                        )
                    ),
                ),
            ),
        ),
    )
    runtime = ScriptRuntime([script]).install(scenario.actor)

    await scenario.actor.tick(0.0)

    assert runtime.errors == [
        f"test.errors:bad-patch: entity {scenario.character} lacks RoomComponent"
    ]
    assert "test.errors:bad-patch" not in runtime.state.blocks


async def test_script_runtime_rejects_unknown_components_and_uncontrolled_targets():
    scenario = build_scenario()
    runtime = ScriptRuntime()
    stray = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Stray", kind="character"), CharacterComponent()],
    )

    with pytest.raises(ScriptRuntimeError, match="unknown component MissingComponent"):
        runtime._component_type("MissingComponent")

    with pytest.raises(ScriptRuntimeError, match=f"character {stray.id} has no controller"):
        await runtime._submit_command(
            scenario.actor,
            SubmitCommandAction(
                target=TargetSelector(query=EntityQuery(id=str(stray.id))),
                command_type="wait",
            ),
            {},
        )


def test_script_runtime_patch_validation_errors():
    scenario = build_scenario()
    runtime = ScriptRuntime()

    with pytest.raises(ScriptRuntimeError, match="contain_in expected one match, found 0"):
        runtime._add_entity(
            scenario.actor,
            AddEntityPatch(
                contain_in=EntityQuery(identity_name="missing"),
                components=(
                    ComponentSpec(
                        type="IdentityComponent",
                        fields={"name": "lost item", "kind": "item"},
                    ),
                ),
            ),
            {},
        )

    with pytest.raises(ScriptRuntimeError, match="unknown component MissingComponent"):
        runtime._patch_world(
            scenario.actor,
            PatchWorldAction(
                operations=(
                    AddComponentPatch(
                        target=TargetSelector(query=EntityQuery(identity_name="Juniper")),
                        component=ComponentSpec(type="MissingComponent"),
                    ),
                )
            ),
            {},
        )


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
