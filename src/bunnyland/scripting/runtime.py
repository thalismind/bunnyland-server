"""Script loading and execution runtime."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from relics import Component, Entity, EntityId

from ..core.commands import CommandCost, SubmittedCommand
from ..core.components import IdentityComponent, RoomComponent
from ..core.controllers import (
    BehaviorControllerComponent,
    DiscordControllerComponent,
    LLMControllerComponent,
    ScriptedControllerComponent,
    SuspendedControllerComponent,
)
from ..core.ecs import container_of, parse_entity_id
from ..core.edges import ContainmentMode, Contains, ControlledBy
from ..core.events import DomainEvent
from ..core.graph_query import GraphQueryError, GraphQueryExecutor
from ..core.mutations import (
    AddEdge,
    AddEntity,
    EntityReference,
    MutationPlan,
    SetComponent,
    execute_mutation_plan,
)
from ..persistence import type_registries
from ..plugins.contributions import collect_content_items
from ..plugins.registry import PluginRegistry
from .model import (
    AddComponentPatch,
    AddEntityPatch,
    EntityQuery,
    ExecutionPolicy,
    FanoutMode,
    GraphTargetSelector,
    PatchWorldAction,
    ScriptBlock,
    ScriptBlockState,
    ScriptDefinition,
    ScriptState,
    SetComponentFieldsPatch,
    SubmitCommandAction,
    TargetSelectorSpec,
    Trigger,
)

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


class ScriptRuntimeError(RuntimeError):
    pass


class ScriptRuntime:
    """Runs external scripts against a ``WorldActor``.

    The runtime captures domain events during a tick, evaluates script blocks in stable
    order at the end of the tick, and submits commands or applies admin-style patches.
    Execution state lives here, not in the ECS world.
    """

    def __init__(
        self,
        scripts: Iterable[ScriptDefinition] = (),
        *,
        registry: PluginRegistry,
        bindings: Mapping[str, str] | None = None,
        state: ScriptState | None = None,
    ) -> None:
        self.scripts = tuple(scripts)
        self.bindings: dict[str, str] = dict(bindings or {})
        for script in self.scripts:
            self.bindings.update(script.bindings)
        self.state = state or ScriptState()
        self.errors: list[str] = []
        self._events: list[DomainEvent] = []
        self._component_registry = type_registries(registry)[0]
        self._graph_queries = GraphQueryExecutor(registry)

    def install(self, actor: WorldActor) -> ScriptRuntime:
        actor.bus.subscribe(DomainEvent, self._capture_event)
        actor.register_after_tick(self.run_tick)
        return self

    def add_script(self, script: ScriptDefinition) -> None:
        self.scripts = (*self.scripts, script)
        self.bindings.update(script.bindings)

    def _capture_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    async def run_tick(self, actor: WorldActor) -> None:
        events = tuple(self._events)
        self._events.clear()
        bindings = dict(self.bindings)
        for script, block in self._ordered_blocks():
            key = _block_key(script, block)
            if not self._eligible(actor, key, block):
                continue
            if not self._triggered(actor, block.trigger, events, bindings):
                continue
            fired_bindings = dict(bindings)
            try:
                for action in block.actions:
                    await self._run_action(actor, action, fired_bindings)
            except ScriptRuntimeError as exc:
                self.errors.append(f"{key}: {exc}")
                continue
            self._mark_fired(actor, key)
            self.bindings.update(
                {name: value for name, value in fired_bindings.items() if name not in bindings}
            )
            bindings.update(fired_bindings)

    def _ordered_blocks(self) -> list[tuple[ScriptDefinition, ScriptBlock]]:
        pairs = [(script, block) for script in self.scripts for block in script.blocks]
        return sorted(pairs, key=lambda pair: (pair[1].priority, pair[0].id, pair[1].name))

    def _eligible(self, actor: WorldActor, key: str, block: ScriptBlock) -> bool:
        state = self.state.blocks.get(key)
        if block.execution is ExecutionPolicy.ONCE and state is not None and state.count > 0:
            return False
        if (
            state is not None
            and state.last_fired_epoch is not None
            and block.cooldown_seconds > 0
            and actor.epoch < state.last_fired_epoch + block.cooldown_seconds
        ):
            return False
        return True

    def _mark_fired(self, actor: WorldActor, key: str) -> None:
        existing = self.state.blocks.get(key, ScriptBlockState())
        self.state.blocks[key] = ScriptBlockState(
            count=existing.count + 1,
            last_fired_epoch=actor.epoch,
        )

    def _triggered(
        self,
        actor: WorldActor,
        trigger: Trigger,
        events: tuple[DomainEvent, ...],
        bindings: Mapping[str, str],
    ) -> bool:
        if trigger.all:
            return all(self._triggered(actor, child, events, bindings) for child in trigger.all)
        if trigger.any:
            return any(self._triggered(actor, child, events, bindings) for child in trigger.any)
        if trigger.not_ is not None:
            return not self._triggered(actor, trigger.not_, events, bindings)
        if trigger.tick:
            return True
        if trigger.epoch_at_least is not None:
            return actor.epoch >= trigger.epoch_at_least
        if trigger.event_type is not None:
            return any(self._event_matches(event, trigger, bindings) for event in events)
        return False

    def _event_matches(
        self, event: DomainEvent, trigger: Trigger, bindings: Mapping[str, str]
    ) -> bool:
        event_name = type(event).__name__
        if trigger.event_type not in (event_name, f"{type(event).__module__}.{event_name}"):
            return False
        dumped = event.model_dump()
        for field, expected in trigger.event_fields.items():
            if dumped.get(field) != self._resolve_value(expected, bindings):
                return False
        return True

    async def _run_action(
        self,
        actor: WorldActor,
        action: SubmitCommandAction | PatchWorldAction,
        bindings: dict[str, str],
    ) -> None:
        if isinstance(action, SubmitCommandAction):
            await self._submit_command(actor, action, bindings)
        elif isinstance(action, PatchWorldAction):
            self._patch_world(actor, action, bindings)
        else:
            raise ScriptRuntimeError(f"unknown action {action!r}")

    async def _submit_command(
        self, actor: WorldActor, action: SubmitCommandAction, bindings: dict[str, str]
    ) -> None:
        selections = self._selection_rows(actor, action.target, bindings)
        prepared = []
        for target, selected_bindings in selections:
            controller_id, generation = self._current_controller(target)
            if controller_id is None or generation is None:
                raise ScriptRuntimeError(f"character {target.id} has no controller")
            prepared.append((target, selected_bindings, controller_id, generation))
        for target, selected_bindings, controller_id, generation in prepared:
            bindings.update(selected_bindings)
            expires_at = (
                actor.epoch + action.expires_after_seconds
                if action.expires_after_seconds is not None
                else None
            )
            await actor.submit(
                SubmittedCommand(
                    command_id=uuid4().hex,
                    character_id=str(target.id),
                    controller_id=str(controller_id),
                    controller_generation=generation,
                    command_type=action.command_type,
                    payload=self._resolve_mapping(action.payload, bindings),
                    cost=CommandCost(action=action.cost.action, focus=action.cost.focus),
                    lane=action.lane,
                    on_insufficient_points=action.on_insufficient_points,
                    submitted_at_epoch=actor.epoch,
                    expires_at_epoch=expires_at,
                )
            )

    def _patch_world(
        self, actor: WorldActor, action: PatchWorldAction, bindings: dict[str, str]
    ) -> None:
        for operation in action.operations:
            if isinstance(operation, AddEntityPatch):
                self._add_entity(actor, operation, bindings)
            elif isinstance(operation, AddComponentPatch):
                selections = self._selection_rows(actor, operation.target, bindings)
                mutations = []
                for target, selected_bindings in selections:
                    bindings.update(selected_bindings)
                    mutations.append(
                        SetComponent(
                            target.id,
                            self._build_component(operation.component, bindings),
                        )
                    )
                execute_mutation_plan(actor.world, MutationPlan(tuple(mutations)))
            elif isinstance(operation, SetComponentFieldsPatch):
                component_type = self._component_type(operation.component_type)
                selections = self._selection_rows(actor, operation.target, bindings)
                mutations = []
                for target, selected_bindings in selections:
                    bindings.update(selected_bindings)
                    if not target.has_component(component_type):
                        raise ScriptRuntimeError(
                            f"entity {target.id} lacks {operation.component_type}"
                        )
                    current = target.get_component(component_type)
                    mutations.append(
                        SetComponent(
                            target.id,
                            replace(
                                current,
                                **self._resolve_mapping(operation.fields, bindings),
                            ),
                        )
                    )
                execute_mutation_plan(actor.world, MutationPlan(tuple(mutations)))
            else:
                raise ScriptRuntimeError(f"unknown patch operation {operation!r}")

    def _add_entity(
        self, actor: WorldActor, operation: AddEntityPatch, bindings: dict[str, str]
    ) -> None:
        components = [self._build_component(spec, bindings) for spec in operation.components]
        container_id = None
        if operation.contain_in is not None:
            containers = self._resolve_query(actor, operation.contain_in, bindings)
            if len(containers) != 1:
                raise ScriptRuntimeError(f"contain_in expected one match, found {len(containers)}")
            container_id = containers[0].id

        reference = EntityReference()
        mutations = [AddEntity(tuple(components), reference)]
        if container_id is not None:
            mutations.append(
                AddEdge(
                    container_id,
                    reference,
                    Contains(mode=ContainmentMode(operation.containment_mode)),
                )
            )
        execute_mutation_plan(actor.world, MutationPlan(tuple(mutations)))
        if operation.bind is not None:
            bindings[operation.bind] = str(reference.require())

    def _build_component(self, spec, bindings: Mapping[str, str]) -> Component:
        component_type = self._component_type(spec.type)
        fields = self._resolve_mapping(spec.fields, bindings)
        return component_type(**fields)

    def _component_type(self, name: str) -> type[Component]:
        component_type = self._component_registry.get(name)
        if component_type is None:
            raise ScriptRuntimeError(f"unknown component {name}")
        return component_type

    def _select(
        self, actor: WorldActor, selector: TargetSelectorSpec, bindings: dict[str, str]
    ) -> list[Entity]:
        return [entity for entity, _row in self._selection_rows(actor, selector, bindings)]

    def _selection_rows(
        self, actor: WorldActor, selector: TargetSelectorSpec, bindings: dict[str, str]
    ) -> list[tuple[Entity, dict[str, str]]]:
        if isinstance(selector, GraphTargetSelector):
            resolved_bindings = {
                name: str(self._resolve_value(value, bindings))
                for name, value in selector.graph.bindings.items()
            }
            spec = selector.graph.model_copy(update={"bindings": resolved_bindings})
            try:
                graph_rows = self._graph_queries.execute(actor.world, spec)
            except GraphQueryError as exc:
                raise ScriptRuntimeError(str(exc)) from exc
            rows = [
                (
                    actor.world.get_entity(parse_entity_id(row[selector.target_variable])),
                    {**row, selector.bind: row[selector.target_variable]},
                )
                for row in graph_rows
            ]
        else:
            matches = self._resolve_query(actor, selector.query, bindings)
            rows = [(entity, {selector.bind: str(entity.id)}) for entity in matches]
        if selector.mode is FanoutMode.ONE:
            if len(rows) != 1:
                raise ScriptRuntimeError(
                    f"selector {selector.bind!r} expected one match, found {len(rows)}"
                )
            bindings.update(rows[0][1])
            return rows
        if selector.mode is FanoutMode.FIRST:
            if not rows:
                raise ScriptRuntimeError(f"selector {selector.bind!r} found no matches")
            bindings.update(rows[0][1])
            return [rows[0]]
        if selector.mode is FanoutMode.EACH:
            return rows
        raise ScriptRuntimeError(f"unknown fanout mode {selector.mode}")

    def _resolve_query(
        self, actor: WorldActor, query: EntityQuery, bindings: Mapping[str, str]
    ) -> list[Entity]:
        if query.id is not None:
            entity_id = parse_entity_id(self._resolve_value(query.id, bindings))
            if entity_id is None or not actor.world.has_entity(entity_id):
                return []
            candidates = [actor.world.get_entity(entity_id)]
        else:
            candidates = list(actor.world.query().execute_entities())

        matches = []
        for entity in candidates:
            if self._matches_query(actor, entity, query, bindings):
                matches.append(entity)
        return sorted(matches, key=lambda entity: str(entity.id))

    def _matches_query(
        self,
        actor: WorldActor,
        entity: Entity,
        query: EntityQuery,
        bindings: Mapping[str, str],
    ) -> bool:
        for component_name in query.components:
            if not entity.has_component(self._component_type(component_name)):
                return False
        for component_name in query.without_components:
            if entity.has_component(self._component_type(component_name)):
                return False
        if query.identity_name is not None or query.identity_kind is not None or query.tags:
            if not entity.has_component(IdentityComponent):
                return False
            identity = entity.get_component(IdentityComponent)
            if query.identity_name is not None and identity.name != query.identity_name:
                return False
            if query.identity_kind is not None and identity.kind != query.identity_kind:
                return False
            if query.tags and not set(query.tags).issubset(identity.tags):
                return False
        if query.room_title is not None:
            if not entity.has_component(RoomComponent):
                return False
            if entity.get_component(RoomComponent).title != query.room_title:
                return False
        if query.in_room is not None:
            room_id = parse_entity_id(self._resolve_value(query.in_room, bindings))
            if room_id is None or container_of(entity) != room_id:
                return False
        if query.controller_kind is not None:
            if self._controller_kind(actor, entity) != query.controller_kind:
                return False
        return True

    def _current_controller(self, character: Entity) -> tuple[EntityId | None, int | None]:
        for edge, target_id in character.get_relationships(ControlledBy):
            return target_id, edge.generation
        return None, None

    def _controller_kind(self, actor: WorldActor, character: Entity) -> str | None:
        controller_id, _generation = self._current_controller(character)
        if controller_id is None or not actor.world.has_entity(controller_id):
            return None
        controller = actor.world.get_entity(controller_id)
        if controller.has_component(DiscordControllerComponent):
            return "discord"
        if controller.has_component(LLMControllerComponent):
            return "llm"
        if controller.has_component(BehaviorControllerComponent):
            return "behavioral"
        if controller.has_component(ScriptedControllerComponent):
            return "scripted"
        if controller.has_component(SuspendedControllerComponent):
            return "suspended"
        return "unknown"

    def _resolve_mapping(self, value: Mapping[str, Any], bindings: Mapping[str, str]) -> dict:
        return {key: self._resolve_value(item, bindings) for key, item in value.items()}

    def _resolve_value(self, value: Any, bindings: Mapping[str, str]) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            return bindings.get(value[1:], value)
        if isinstance(value, dict):
            return self._resolve_mapping(value, bindings)
        if isinstance(value, list):
            return [self._resolve_value(item, bindings) for item in value]
        return value


def _block_key(script: ScriptDefinition, block: ScriptBlock) -> str:
    return f"{script.id}:{block.name}"


def load_script(path: str | Path) -> ScriptDefinition:
    return ScriptDefinition.model_validate_json(Path(path).read_text())


def load_scripts(paths: Iterable[str | Path]) -> list[ScriptDefinition]:
    return [load_script(path) for path in paths]


def write_script_state(path: str | Path, state: ScriptState) -> None:
    Path(path).write_text(state.model_dump_json(indent=2))


def load_script_state(path: str | Path) -> ScriptState:
    return ScriptState.model_validate_json(Path(path).read_text())


def collect_scripts(plugins: Iterable) -> list[ScriptDefinition]:
    scripts: list[ScriptDefinition] = []
    for item in collect_content_items(plugins, "scripts"):
        if isinstance(item, ScriptDefinition):
            scripts.append(item)
        elif isinstance(item, (str, Path)):
            scripts.append(load_script(item))
        elif isinstance(item, Mapping):
            scripts.append(ScriptDefinition.model_validate(item))
        else:
            raise ScriptRuntimeError(f"unsupported script contribution {item!r}")
    return scripts


def install_scripting(
    actor: WorldActor,
    scripts: Iterable[ScriptDefinition],
    *,
    state: ScriptState | None = None,
    bindings: Mapping[str, str] | None = None,
) -> ScriptRuntime:
    if actor.plugins is None:
        raise ScriptRuntimeError("scripting requires an applied PluginRegistry")
    return ScriptRuntime(
        scripts,
        registry=actor.plugins,
        state=state,
        bindings=bindings,
    ).install(actor)


__all__ = [
    "ScriptRuntime",
    "ScriptRuntimeError",
    "collect_scripts",
    "install_scripting",
    "load_script",
    "load_script_state",
    "load_scripts",
    "write_script_state",
]
