"""Shared test scaffolding: a tiny two-room world with a controllable character."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from types import ModuleType

import pytest
from relics import EntityId

from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    ContainmentMode,
    Contains,
    ExitTo,
    FocusPointsComponent,
    HandlerContext,
    HandlerResult,
    IdentityComponent,
    InitiativeComponent,
    LLMControllerComponent,
    MoveHandler,
    RoomComponent,
    WorldActor,
    execute_mutation_plan,
    spawn_entity,
)
from bunnyland.plugins import Plugin, PluginRegistry, bunnyland_plugins


@dataclass
class Scenario:
    actor: WorldActor
    room_a: EntityId
    room_b: EntityId
    character: EntityId
    controller: EntityId
    generation: int

    def character_room(self) -> EntityId | None:
        from bunnyland.core import container_of

        return container_of(self.actor.world.get_entity(self.character))


def execute_handler(handler, ctx: HandlerContext, command) -> HandlerResult:
    """Execute a handler plan explicitly for standalone handler tests."""

    result = handler.execute(ctx, command)
    if not result.ok:
        return result
    assert result.plan is not None
    _summary, deferred = execute_mutation_plan(
        ctx.world,
        result.plan,
        after_apply=lambda: tuple(factory() for factory in result.event_factories),
    )
    return replace(
        result,
        events=(*result.events, *deferred),
        event_factories=(),
    )


def build_scenario(
    *,
    action_current: float = 5.0,
    focus_current: float = 3.0,
    initiative: float = 1.0,
) -> Scenario:
    actor = WorldActor()
    actor.plugins = PluginRegistry(bunnyland_plugins())
    for _owner, definition in actor.plugins.actions.values():
        actor.register_action_definition(definition)
    actor.register_handler(MoveHandler())
    world = actor.world

    room_a = spawn_entity(world, [RoomComponent(title="Mosslit Burrow")])
    room_b = spawn_entity(world, [RoomComponent(title="North Tunnel")])
    room_a.add_relationship(ExitTo(direction="north"), room_b.id)
    room_b.add_relationship(ExitTo(direction="south"), room_a.id)

    character = spawn_entity(
        world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            ActionPointsComponent(
                current=action_current,
                maximum=max(5.0, action_current),
                regen_per_hour=1.0,
            ),
            FocusPointsComponent(current=focus_current, maximum=3.0, regen_per_hour=0.5),
            InitiativeComponent(score=initiative),
        ],
    )
    room_a.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), character.id)

    controller = spawn_entity(
        world, [LLMControllerComponent(profile_name="default", model="claude")]
    )
    generation = actor.assign_controller(character.id, controller.id)

    return Scenario(
        actor=actor,
        room_a=room_a.id,
        room_b=room_b.id,
        character=character.id,
        controller=controller.id,
        generation=generation,
    )


@pytest.fixture
def scenario() -> Scenario:
    return build_scenario()


def install_plugin_module(monkeypatch, name: str, plugins: list[Plugin]) -> None:
    module = ModuleType(name)
    module.bunnyland_plugins = lambda: plugins
    monkeypatch.setitem(sys.modules, name, module)
