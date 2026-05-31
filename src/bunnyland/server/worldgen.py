"""Admin world-generation helpers that produce ECS patches."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ..core.components import (
    CharacterComponent,
    ContainerComponent,
    DescriptionComponent,
    DoorComponent,
    IdentityComponent,
    LightComponent,
    LockableComponent,
    RoomComponent,
    StimulusComponent,
    SuspendedComponent,
    TemperatureComponent,
)
from ..core.controllers import LLMControllerComponent, SuspendedControllerComponent
from ..core.ecs import container_of, parse_entity_id
from ..core.edges import ContainmentMode, Contains, ControlledBy, ExitTo
from ..core.world_actor import WorldActor
from ..mechanics.storyteller import IncidentComponent
from ..worldgen import DoorProposal, GenOptions, RoomNodeProposal, StubRecursiveBuilder
from ..worldgen.instantiate import _character_components, _object_components
from ..worldgen.proposal import CharacterProposal, ItemProposal, StoryEventProposal
from ..worldgen.recursive import _opposite
from .models import (
    AddEntityPatchRequest,
    ComponentPatchSpec,
    EdgePatchSpec,
    SetComponentPatchRequest,
    SetEdgePatchRequest,
    WorldCharacterGenerationRequest,
    WorldCharacterGenerationResponse,
    WorldEventGenerationRequest,
    WorldEventGenerationResponse,
    WorldItemGenerationRequest,
    WorldItemGenerationResponse,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
    WorldRoomGenerationResponse,
)
from .patches import WorldPatchError
from .schema import dm_schema_context
from .serialization import jsonable

_DIRECTIONS = (
    "north",
    "south",
    "east",
    "west",
    "up",
    "down",
    "in",
    "out",
    "northeast",
    "northwest",
    "southeast",
    "southwest",
)


@dataclass(frozen=True)
class RoomExpansionContext:
    source_room_id: str
    door_entity_id: str
    door_name: str
    direction: str
    locked: bool
    hidden: bool
    known_rooms: Mapping[str, str]
    prompt: str
    door_component: DoorComponent


@dataclass(frozen=True)
class RoomSelectionContext:
    room_id: str
    room: RoomNodeProposal
    known_rooms: Mapping[str, str]
    prompt: str


@dataclass(frozen=True)
class ContainerSelectionContext:
    container_id: str
    container_name: str
    container_kind: str
    contain_mode: ContainmentMode
    known_rooms: Mapping[str, str]
    prompt: str


def _component_spec(component: Any) -> ComponentPatchSpec:
    return ComponentPatchSpec(type=type(component).__name__, fields=jsonable(component))


def _edge_spec(edge: Any) -> EdgePatchSpec:
    return EdgePatchSpec(type=type(edge).__name__, fields=jsonable(edge))


def _room_description(entity) -> str:
    room = entity.get_component(RoomComponent)
    parts = [room.title]
    if entity.has_component(DescriptionComponent):
        description = entity.get_component(DescriptionComponent)
        if description.long:
            parts.append(description.long)
        elif description.short:
            parts.append(description.short)
    return " - ".join(parts)


def _infer_direction(name: str) -> str | None:
    words = {
        token.strip(".,:;()[]{}").lower()
        for token in name.replace("-", " ").replace("_", " ").split()
    }
    for direction in _DIRECTIONS:
        if direction in words:
            return direction
    return None


def collect_room_expansion_context(
    actor: WorldActor, request: WorldRoomGenerationRequest
) -> RoomExpansionContext:
    door_id = parse_entity_id(request.door_entity_id)
    if door_id is None or not actor.world.has_entity(door_id):
        raise WorldPatchError(f"door entity {request.door_entity_id!r} does not exist")

    door_entity = actor.world.get_entity(door_id)
    if not door_entity.has_component(DoorComponent):
        raise WorldPatchError(f"entity {request.door_entity_id!r} is not a door")

    source_room_id = container_of(door_entity)
    if source_room_id is None or not actor.world.has_entity(source_room_id):
        raise WorldPatchError("door is not contained by a room")
    source_room = actor.world.get_entity(source_room_id)
    if not source_room.has_component(RoomComponent):
        raise WorldPatchError("door container is not a room")

    identity = (
        door_entity.get_component(IdentityComponent)
        if door_entity.has_component(IdentityComponent)
        else None
    )
    door_name = identity.name if identity is not None else str(door_id)
    direction = (request.direction or "").strip().lower() or _infer_direction(door_name)
    if not direction:
        raise WorldPatchError("direction is required when it cannot be inferred from the door name")

    known_rooms = {
        str(entity.id): _room_description(entity)
        for entity in actor.world.query().with_all([RoomComponent]).execute_entities()
    }
    locked = (
        door_entity.get_component(LockableComponent).locked
        if door_entity.has_component(LockableComponent)
        else False
    )
    return RoomExpansionContext(
        source_room_id=str(source_room_id),
        door_entity_id=str(door_id),
        door_name=door_name,
        direction=direction,
        locked=locked,
        hidden=False,
        known_rooms=known_rooms,
        prompt=request.prompt.strip(),
        door_component=door_entity.get_component(DoorComponent),
    )


def collect_room_selection_context(
    actor: WorldActor, request: WorldCharacterGenerationRequest | WorldEventGenerationRequest
) -> RoomSelectionContext:
    room_id = parse_entity_id(request.room_entity_id)
    if room_id is None or not actor.world.has_entity(room_id):
        raise WorldPatchError(f"room entity {request.room_entity_id!r} does not exist")
    room_entity = actor.world.get_entity(room_id)
    if not room_entity.has_component(RoomComponent):
        raise WorldPatchError(f"entity {request.room_entity_id!r} is not a room")
    room_component = room_entity.get_component(RoomComponent)
    description = ""
    if room_entity.has_component(DescriptionComponent):
        description = room_entity.get_component(DescriptionComponent).long
        if not description:
            description = room_entity.get_component(DescriptionComponent).short
    known_rooms = {
        str(entity.id): _room_description(entity)
        for entity in actor.world.query().with_all([RoomComponent]).execute_entities()
    }
    return RoomSelectionContext(
        room_id=str(room_id),
        room=RoomNodeProposal(
            title=room_component.title,
            biome=room_component.biome,
            indoor=room_component.indoor,
            description=description,
        ),
        known_rooms=known_rooms,
        prompt=request.prompt.strip(),
    )


def collect_container_selection_context(
    actor: WorldActor, request: WorldItemGenerationRequest
) -> ContainerSelectionContext:
    container_id = parse_entity_id(request.container_entity_id)
    if container_id is None or not actor.world.has_entity(container_id):
        raise WorldPatchError(f"container entity {request.container_entity_id!r} does not exist")
    entity = actor.world.get_entity(container_id)
    identity = (
        entity.get_component(IdentityComponent)
        if entity.has_component(IdentityComponent)
        else None
    )
    if entity.has_component(RoomComponent):
        room = entity.get_component(RoomComponent)
        name = room.title
        kind = "room"
        mode = ContainmentMode.ROOM_CONTENT
    elif entity.has_component(CharacterComponent):
        name = identity.name if identity is not None else str(container_id)
        kind = "character"
        mode = ContainmentMode.INVENTORY
    elif entity.has_component(ContainerComponent):
        name = identity.name if identity is not None else str(container_id)
        kind = identity.kind if identity is not None else "container"
        mode = ContainmentMode.CONTAINER
    else:
        raise WorldPatchError("selected entity cannot contain generated items")

    known_rooms = {
        str(room.id): _room_description(room)
        for room in actor.world.query().with_all([RoomComponent]).execute_entities()
    }
    return ContainerSelectionContext(
        container_id=str(container_id),
        container_name=name,
        container_kind=kind,
        contain_mode=mode,
        known_rooms=known_rooms,
        prompt=request.prompt.strip(),
    )


def _builder(options: GenOptions):
    if options.llm:
        from ..worldgen import OllamaRecursiveBuilder

        return OllamaRecursiveBuilder(
            model=options.model,
            host=options.host,
            api_key=options.api_key,
        )
    return StubRecursiveBuilder()


def _dm_schema_context(actor: WorldActor, options: GenOptions) -> str:
    if not options.llm:
        return ""
    return dm_schema_context(actor)


def _room_components(room: RoomNodeProposal) -> list[ComponentPatchSpec]:
    components = [
        _component_spec(RoomComponent(title=room.title, biome=room.biome, indoor=room.indoor))
    ]
    if room.description:
        components.append(
            _component_spec(
                DescriptionComponent(short=room.description, long=room.description)
            )
        )
    if room.light is not None:
        components.append(_component_spec(LightComponent(level=room.light)))
    if room.celsius is not None:
        components.append(_component_spec(TemperatureComponent(celsius=room.celsius)))
    return components


def _object_operations(room_id: str, key: str, item: ItemProposal) -> list:
    return [
        AddEntityPatchRequest(
            op="add_entity",
            client_id=key,
            components=[_component_spec(component) for component in _object_components(item)],
        ),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=room_id,
            target_id=key,
            edge=_edge_spec(Contains(mode=ContainmentMode.ROOM_CONTENT)),
        ),
    ]


def _item_operations(
    container_id: str, key: str, item: ItemProposal, mode: ContainmentMode
) -> list:
    return [
        AddEntityPatchRequest(
            op="add_entity",
            client_id=key,
            components=[_component_spec(component) for component in _object_components(item)],
        ),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=container_id,
            target_id=key,
            edge=_edge_spec(Contains(mode=mode)),
        ),
    ]


def _character_operations(
    room_id: str, key: str, controller_key: str, character: CharacterProposal, epoch: int
) -> list:
    components = [_component_spec(component) for component in _character_components(character)]
    if character.controller == "llm":
        controller_components = [
            _component_spec(
                LLMControllerComponent(
                    profile_name=character.llm_profile,
                    model=character.llm_model,
                )
            )
        ]
    else:
        components.append(
            _component_spec(
                SuspendedComponent(reason="generated", suspended_at_epoch=epoch)
            )
        )
        controller_components = [_component_spec(SuspendedControllerComponent(reason="generated"))]

    return [
        AddEntityPatchRequest(op="add_entity", client_id=key, components=components),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=room_id,
            target_id=key,
            edge=_edge_spec(Contains(mode=ContainmentMode.ROOM_CONTENT)),
        ),
        AddEntityPatchRequest(
            op="add_entity",
            client_id=controller_key,
            components=controller_components,
        ),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=key,
            target_id=controller_key,
            edge=_edge_spec(ControlledBy(generation=0, since_epoch=epoch)),
        ),
    ]


def _door_operations(room_id: str, key: str, door: DoorProposal) -> list:
    prefix = "a hidden" if door.hidden else "a sealed"
    components = [
        _component_spec(IdentityComponent(name=f"{prefix} {door.direction} door", kind="door")),
        _component_spec(DoorComponent(open=False, open_on_use=False)),
    ]
    if door.locked:
        components.append(_component_spec(LockableComponent(locked=True)))
    return [
        AddEntityPatchRequest(op="add_entity", client_id=key, components=components),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=room_id,
            target_id=key,
            edge=_edge_spec(Contains(mode=ContainmentMode.ROOM_CONTENT)),
        ),
    ]


def _event_components(
    event: StoryEventProposal, room_id: str, epoch: int
) -> list[ComponentPatchSpec]:
    summary = event.summary or event.title
    tags = tuple(dict.fromkeys((event.kind, *event.tags)))
    return [
        _component_spec(IdentityComponent(name=event.title, kind="incident", tags=tags)),
        _component_spec(DescriptionComponent(short=summary, long=summary)),
        _component_spec(
            IncidentComponent(
                kind=event.kind,
                budget_spent=max(0.0, event.budget_spent),
                started_at_epoch=epoch,
                room_id=room_id,
            )
        ),
        _component_spec(
            StimulusComponent(
                stimulus_type=event.stimulus_type or event.kind,
                source_entity_id=None,
                room_id=room_id,
                intensity=max(0.0, event.stimulus_intensity),
                created_at_epoch=epoch,
                text=summary,
            )
        ),
    ]


def build_room_generation_response(
    context: RoomExpansionContext,
    *,
    room: RoomNodeProposal,
    contents: Any,
    doors: list[DoorProposal],
    epoch: int,
) -> WorldRoomGenerationResponse:
    room_id = "$generated_room"
    operations: list[Any] = [
        AddEntityPatchRequest(
            op="add_entity",
            client_id=room_id,
            components=_room_components(room),
        ),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=context.source_room_id,
            target_id=room_id,
            edge=_edge_spec(
                ExitTo(
                    direction=context.direction,
                    label=context.door_name,
                    locked=context.locked,
                    hidden=context.hidden,
                )
            ),
        ),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=room_id,
            target_id=context.source_room_id,
            edge=_edge_spec(
                ExitTo(direction=_opposite(context.direction), label=context.door_name)
            ),
        ),
        SetComponentPatchRequest(
            op="set_component",
            entity_id=context.door_entity_id,
            component=_component_spec(
                replace(context.door_component, open=True, open_on_use=True)
            ),
        ),
    ]

    for index, item in enumerate(contents.objects):
        operations.extend(_object_operations(room_id, f"$generated_object_{index}", item))
    for index, character in enumerate(contents.characters):
        character.key = f"generated_character_{index}"
        operations.extend(
            _character_operations(
                room_id,
                f"$generated_character_{index}",
                f"$generated_controller_{index}",
                character,
                epoch,
            )
        )
    for index, door in enumerate(doors):
        operations.extend(_door_operations(room_id, f"$generated_door_{index}", door))

    return WorldRoomGenerationResponse(
        source_room_id=context.source_room_id,
        door_entity_id=context.door_entity_id,
        generated_title=room.title,
        patch=WorldPatchRequest(operations=operations),
    )


def build_character_generation_response(
    context: RoomSelectionContext, character: CharacterProposal, *, epoch: int
) -> WorldCharacterGenerationResponse:
    character.key = "generated_character"
    operations = _character_operations(
        context.room_id,
        "$generated_character",
        "$generated_controller",
        character,
        epoch,
    )
    return WorldCharacterGenerationResponse(
        room_entity_id=context.room_id,
        generated_name=character.name,
        patch=WorldPatchRequest(operations=operations),
    )


def build_item_generation_response(
    context: ContainerSelectionContext, item: ItemProposal
) -> WorldItemGenerationResponse:
    operations = _item_operations(
        context.container_id,
        "$generated_item",
        item,
        context.contain_mode,
    )
    return WorldItemGenerationResponse(
        container_entity_id=context.container_id,
        generated_name=item.name,
        patch=WorldPatchRequest(operations=operations),
    )


def build_event_generation_response(
    context: RoomSelectionContext, event: StoryEventProposal, *, epoch: int
) -> WorldEventGenerationResponse:
    event_id = "$generated_event"
    operations: list[Any] = [
        AddEntityPatchRequest(
            op="add_entity",
            client_id=event_id,
            components=_event_components(event, context.room_id, epoch),
        ),
        SetEdgePatchRequest(
            op="set_edge",
            source_id=context.room_id,
            target_id=event_id,
            edge=_edge_spec(Contains(mode=ContainmentMode.ROOM_CONTENT)),
        ),
    ]
    for index, item in enumerate(event.objects):
        operations.extend(
            _object_operations(context.room_id, f"$generated_event_object_{index}", item)
        )
    for index, character in enumerate(event.characters):
        character.key = f"generated_event_character_{index}"
        operations.extend(
            _character_operations(
                context.room_id,
                f"$generated_event_character_{index}",
                f"$generated_event_controller_{index}",
                character,
                epoch,
            )
        )
    return WorldEventGenerationResponse(
        room_entity_id=context.room_id,
        generated_title=event.title,
        generated_kind=event.kind,
        patch=WorldPatchRequest(operations=operations),
    )


def generate_room_patch(
    actor: WorldActor,
    request: WorldRoomGenerationRequest,
    *,
    options: GenOptions | None = None,
) -> WorldRoomGenerationResponse:
    context = collect_room_expansion_context(actor, request)
    options = options or GenOptions()
    builder = _builder(options)
    schema_context = _dm_schema_context(actor, options)
    door = DoorProposal(
        direction=context.direction,
        locked=context.locked,
        hidden=context.hidden,
        beyond_hint=context.prompt or context.door_name,
    )
    room = builder.propose_room(
        context.prompt or context.door_name,
        behind=door,
        known_rooms=context.known_rooms,
        schema_context=schema_context,
    )
    known_rooms = {**context.known_rooms, "$generated_room": room.description or room.title}
    contents = builder.propose_contents(
        room, known_rooms=known_rooms, schema_context=schema_context
    )
    doors = builder.propose_doors(room, schema_context=schema_context)
    return build_room_generation_response(
        context,
        room=room,
        contents=contents,
        doors=doors,
        epoch=actor.epoch,
    )


def generate_character_patch(
    actor: WorldActor,
    request: WorldCharacterGenerationRequest,
    *,
    options: GenOptions | None = None,
) -> WorldCharacterGenerationResponse:
    context = collect_room_selection_context(actor, request)
    options = options or GenOptions()
    builder = _builder(options)
    character = builder.propose_character(
        context.room,
        prompt=context.prompt,
        known_rooms=context.known_rooms,
        schema_context=_dm_schema_context(actor, options),
    )
    return build_character_generation_response(context, character, epoch=actor.epoch)


def generate_item_patch(
    actor: WorldActor,
    request: WorldItemGenerationRequest,
    *,
    options: GenOptions | None = None,
) -> WorldItemGenerationResponse:
    context = collect_container_selection_context(actor, request)
    options = options or GenOptions()
    builder = _builder(options)
    item = builder.propose_item(
        container_name=context.container_name,
        container_kind=context.container_kind,
        prompt=context.prompt,
        known_rooms=context.known_rooms,
        schema_context=_dm_schema_context(actor, options),
    )
    return build_item_generation_response(context, item)


def generate_event_patch(
    actor: WorldActor,
    request: WorldEventGenerationRequest,
    *,
    options: GenOptions | None = None,
) -> WorldEventGenerationResponse:
    context = collect_room_selection_context(actor, request)
    options = options or GenOptions()
    builder = _builder(options)
    event = builder.propose_event(
        context.room,
        prompt=context.prompt,
        known_rooms=context.known_rooms,
        schema_context=_dm_schema_context(actor, options),
    )
    return build_event_generation_response(context, event, epoch=actor.epoch)


__all__ = [
    "RoomExpansionContext",
    "RoomSelectionContext",
    "build_room_generation_response",
    "build_character_generation_response",
    "build_event_generation_response",
    "build_item_generation_response",
    "collect_container_selection_context",
    "collect_room_expansion_context",
    "collect_room_selection_context",
    "generate_character_patch",
    "generate_event_patch",
    "generate_item_patch",
    "generate_room_patch",
]
