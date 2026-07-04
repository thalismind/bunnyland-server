"""JSON-safe world and event serialization for client APIs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import is_dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from ..core.actions import ActionDefinition, action_definitions, action_icon_for
from ..core.availability import (
    AvailabilityResult,
    evaluate_availability,
    target_group_for_argument,
)
from ..core.commands import Lane, SubmittedCommand
from ..core.components import (
    ActionPointsComponent,
    AffectComponent,
    BleedingComponent,
    BodyPlanComponent,
    CharacterComponent,
    ContainerComponent,
    DeadComponent,
    DescriptionComponent,
    DoorComponent,
    DownedComponent,
    EditorDisplayComponent,
    EncumbranceComponent,
    FocusPointsComponent,
    HealthComponent,
    IdentityComponent,
    InitiativeComponent,
    InjuryComponent,
    LightComponent,
    PainComponent,
    PortableComponent,
    RoomComponent,
    SleepingComponent,
    StealthComponent,
    SuspendedComponent,
    ThoughtComponent,
    WeightComponent,
)
from ..core.controllers import (
    BehaviorControllerComponent,
    DiscordControllerComponent,
    LLMControllerComponent,
    MCPControllerComponent,
    ScriptedControllerComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
)
from ..core.ecs import container_of, contents, entity_name, parse_entity_id
from ..core.edges import Contains, ControlledBy, ExitTo, HasInjury, HasThought, Holding, Wearing
from ..core.events import DomainEvent
from ..core.world_actor import WorldActor
from ..imagegen.components import PortraitImageComponent
from ..mechanics.consumables import DrinkableComponent, FoodComponent
from ..mechanics.lifesim import (
    AgeComponent,
    AspirationComponent,
    CareerComponent,
    CharacterProfileComponent,
    HouseholdComponent,
    LifeStageComponent,
    PregnancyComponent,
    ReputationComponent,
    SkillSetComponent,
    WellRestedComponent,
    WhimComponent,
)
from ..mechanics.meter import band as meter_band
from ..mechanics.needs import (
    ComfortNeedComponent,
    FatigueComponent,
    FunNeedComponent,
    HungerComponent,
    HygieneComponent,
    PrivacyNeedComponent,
    SafetyNeedComponent,
    SocialNeedComponent,
    ThirstComponent,
)
from ..mechanics.persona import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
)
from ..mechanics.toonsim import (
    ROOM_HEIGHT,
    ROOM_WIDTH,
    SpriteBounds,
    SpriteImage,
    SpriteLayer,
    SpritePosition,
    SpriteScale,
    ToonRoomComponent,
    default_bounds_for,
    default_layer_for,
)
from ..persistence import WorldMeta
from ..projections import PerceivedEntity, build_room_facts, perceive
from .action_search import smart_action_search
from .models import (
    ActionSearchResponse,
    CharacterListResponse,
    CharacterProjectionResponse,
    CharacterQueuedCommandsResponse,
    CharacterSummaryView,
    ClientActionArgumentView,
    ClientActionView,
    ClientCharacterSheetView,
    ClientChecklistItemView,
    ClientControllerView,
    ClientEntityView,
    ClientExitView,
    ClientImageView,
    ClientPointsView,
    ClientRoomView,
    ClientSheetEntryView,
    ClientSheetMetricView,
    ClientSpriteBoundsView,
    ClientSpritePositionView,
    ClientSpriteView,
    ClientTargetView,
    CommandCostRequest,
    DmProjectionResponse,
    DmRoomProjectionView,
    ExamineResponse,
    RoomProjectionEntityView,
    RoomProjectionResponse,
    RoomProjectionRoomView,
    WorldOverviewResponse,
    WorldOverviewRoomView,
)


def jsonable(value: Any) -> Any:
    """Recursively convert known value objects into JSON-native structures."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        fields = getattr(value, "__pydantic_fields__", None) or getattr(
            value, "__dataclass_fields__", {}
        )
        return {
            name: jsonable(getattr(value, name))
            for name in fields
            if not name.startswith("_")
        }
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(item) for item in value]
    return value


def _sorted_entities(actor: WorldActor) -> Iterable:
    return sorted(actor.world.query().execute_entities(), key=lambda entity: str(entity.id))


def serialize_entity(actor: WorldActor, entity) -> dict[str, Any]:
    """Return a client-facing snapshot of one ECS entity."""

    exported = actor.world.export_entity(entity.id)
    identity = (
        entity.get_component(IdentityComponent)
        if entity.has_component(IdentityComponent)
        else None
    )
    relationships: dict[str, list[dict[str, Any]]] = {}
    for edge_name, edges in exported.get("relationships", {}).items():
        relationships[edge_name] = [
            {"target_id": str(edge["target"]), "edge": jsonable(edge["edge"])}
            for edge in edges
        ]
    return {
        "id": str(entity.id),
        "prefab": entity.id.prefab,
        "sequence": entity.id.sequence,
        "name": identity.name if identity is not None else None,
        "kind": identity.kind if identity is not None else None,
        "tags": list(identity.tags) if identity is not None else [],
        "components": {
            type_name: jsonable(fields)
            for type_name, fields in exported.get("components", {}).items()
        },
        "relationships": relationships,
    }


def serialize_queued_command(command: SubmittedCommand) -> dict[str, Any]:
    """Return the client-facing fields for one volatile queued command."""

    return {
        "command_id": command.command_id,
        "character_id": command.character_id,
        "command_type": command.command_type,
        "payload": jsonable(command.payload),
        "cost": jsonable(command.cost),
        "lane": command.lane.value,
        "submitted_at_epoch": command.submitted_at_epoch,
        "expires_at_epoch": command.expires_at_epoch,
    }


def _character_entity(actor: WorldActor, character_id: str):
    parsed = parse_entity_id(character_id)
    if parsed is None or not actor.world.has_entity(parsed):
        raise ValueError("character does not exist")
    character = actor.world.get_entity(parsed)
    if not character.has_component(CharacterComponent):
        raise ValueError("entity is not a character")
    return character


def serialize_queued_commands(actor: WorldActor) -> list[dict[str, Any]]:
    """Return volatile queued commands grouped by character and lane."""

    return [
        serialize_queued_command(command)
        for command in actor.pending_submissions()
    ] + [
        serialize_queued_command(command)
        for character_id in sorted(actor.queues.characters_with_pending())
        for lane in Lane
        for command in actor.queues.pending(character_id, lane)
    ]


def serialize_character_queued_commands(
    actor: WorldActor,
    character_id: str,
    *,
    generated_at_unix: float | None = None,
    next_tick_at_unix: float | None = None,
    tick_seconds: float | None = None,
    time_scale: float | None = None,
    game_seconds_per_tick: float | None = None,
) -> CharacterQueuedCommandsResponse:
    """Return queued commands attached to one acting character."""

    character = _character_entity(actor, character_id)
    command_dicts = [
        serialize_queued_command(command)
        for command in actor.pending_submissions()
        if command.character_id == str(character.id)
    ] + [
        serialize_queued_command(command)
        for lane in Lane
        for command in actor.queues.pending(str(character.id), lane)
    ]
    return CharacterQueuedCommandsResponse(
        world_epoch=actor.epoch,
        character_id=str(character.id),
        generated_at_unix=generated_at_unix,
        next_tick_at_unix=next_tick_at_unix,
        tick_seconds=tick_seconds,
        time_scale=time_scale,
        game_seconds_per_tick=game_seconds_per_tick,
        commands=command_dicts,
    )


def serialize_character_list(actor: WorldActor) -> CharacterListResponse:
    """Return the claim lobby: every character's id, name, kind, and suspended flag.

    This is the player-facing replacement for scanning the full snapshot to populate a
    character picker. It deliberately exposes no per-character state (position, points,
    inventory); a client claims a character and then reads its own ``character_view``.
    """

    summaries = [
        CharacterSummaryView(
            character_id=str(character.id),
            name=character.get_component(IdentityComponent).name,
            kind=character.get_component(IdentityComponent).kind or "character",
            suspended=character.has_component(SuspendedComponent),
        )
        for character in actor.world.query()
        .with_all([CharacterComponent, IdentityComponent])
        .execute_entities()
    ]
    summaries.sort(key=lambda summary: summary.name.lower())
    return CharacterListResponse(world_epoch=actor.epoch, characters=summaries)


def serialize_world(actor: WorldActor, meta: WorldMeta | None = None) -> dict[str, Any]:
    """Return the initial snapshot payload expected by web/admin/TUI clients."""

    return {
        "schema_version": 1,
        "world_epoch": actor.epoch,
        "metadata": meta.model_dump(mode="json") if meta is not None else None,
        "entities": [serialize_entity(actor, entity) for entity in _sorted_entities(actor)],
        "queued_commands": serialize_queued_commands(actor),
    }


def _entity_kind(entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).kind or "other"
    if entity.has_component(RoomComponent):
        return "room"
    if entity.has_component(CharacterComponent):
        return "character"
    if entity.has_component(PortableComponent):
        return "item"
    return "other"


def _is_hidden(entity) -> bool:
    if not entity.has_component(StealthComponent):
        return False
    stealth = entity.get_component(StealthComponent)
    return stealth.hiding and stealth.visibility_level <= stealth.hidden_threshold


def _perceived_entity_view(entity: PerceivedEntity) -> ClientEntityView:
    return ClientEntityView(
        id=entity.id,
        name=entity.name,
        kind="character" if entity.is_character else "object",
        is_character=entity.is_character,
        contents=[_perceived_entity_view(child) for child in entity.contents],
    )


def _sprite_position_view(entity) -> ClientSpritePositionView:
    if entity.has_component(SpritePosition):
        position = entity.get_component(SpritePosition)
        return ClientSpritePositionView(x=position.x, y=position.y)
    return ClientSpritePositionView(x=ROOM_WIDTH / 2, y=ROOM_HEIGHT / 2)


def _sprite_bounds_view(entity) -> ClientSpriteBoundsView:
    bounds = entity.get_component(SpriteBounds) if entity.has_component(SpriteBounds) else None
    if bounds is None:
        bounds = default_bounds_for(entity)
    if bounds is None:
        bounds = SpriteBounds()
    return ClientSpriteBoundsView(
        width=bounds.width,
        height=bounds.height,
        solid=bounds.solid,
    )


def _sprite_view(entity) -> ClientSpriteView:
    image = entity.get_component(SpriteImage) if entity.has_component(SpriteImage) else None
    layer = entity.get_component(SpriteLayer).layer if entity.has_component(SpriteLayer) else None
    scale = entity.get_component(SpriteScale).scale if entity.has_component(SpriteScale) else 1.0
    display = (
        entity.get_component(EditorDisplayComponent)
        if entity.has_component(EditorDisplayComponent)
        else None
    )
    return ClientSpriteView(
        position=_sprite_position_view(entity),
        image_url=image.url if image is not None else "",
        image_data=image.data if image is not None else "",
        layer=layer if layer is not None else (default_layer_for(entity) or 20),
        scale=scale,
        bounds=_sprite_bounds_view(entity),
        emoji=display.emoji if display is not None else "",
    )


def _portrait_view(entity) -> ClientImageView:
    if entity.has_component(PortraitImageComponent):
        portrait = entity.get_component(PortraitImageComponent)
        return ClientImageView(url=portrait.url, alpha_url=portrait.alpha_url)
    return ClientImageView()


def _room_projection_entity(entity) -> RoomProjectionEntityView:
    return RoomProjectionEntityView(
        id=str(entity.id),
        name=entity_name(entity),
        kind=_entity_kind(entity),
        is_character=entity.has_component(CharacterComponent),
        sprite=_sprite_view(entity),
        portrait=_portrait_view(entity),
    )


def _room_exits(room) -> list[ClientExitView]:
    exits = [
        ClientExitView(
            id=str(target),
            direction=edge.direction,
            label=f"{edge.direction}: {target}" if edge.direction else str(target),
            locked=edge.locked,
        )
        for edge, target in room.get_relationships(ExitTo)
        if not edge.hidden
    ]
    return sorted(exits, key=lambda exit: (exit.direction, exit.id))


def serialize_room_projection(actor: WorldActor, room_id: str) -> RoomProjectionResponse:
    """Return a play-facing room view without raw ECS components or hidden state."""

    parsed = parse_entity_id(room_id)
    if parsed is None or not actor.world.has_entity(parsed):
        raise ValueError("room does not exist")
    room = actor.world.get_entity(parsed)
    if not room.has_component(RoomComponent):
        raise ValueError("entity is not a room")

    entities = []
    for edge, child_id in room.get_relationships(Contains):
        if not edge.visible or not actor.world.has_entity(child_id):
            continue
        child = actor.world.get_entity(child_id)
        if _is_hidden(child):
            continue
        entities.append(_room_projection_entity(child))

    room_component = room.get_component(RoomComponent)
    toon = room.get_component(ToonRoomComponent) if room.has_component(ToonRoomComponent) else None
    return RoomProjectionResponse(
        world_epoch=actor.epoch,
        room=RoomProjectionRoomView(
            id=str(room.id),
            title=room_component.title,
            default_start=toon.default_start if toon is not None else False,
            sprite=_sprite_view(room),
            entities=sorted(
                entities,
                key=lambda entity: (entity.sprite.layer, entity.name.lower()),
            ),
            exits=_room_exits(room),
        ),
    )


def _overview_room(actor: WorldActor, room) -> WorldOverviewRoomView:
    room_component = room.get_component(RoomComponent)
    occupant_count = 0
    item_count = 0
    for edge, child_id in room.get_relationships(Contains):
        if not edge.visible or not actor.world.has_entity(child_id):
            continue
        child = actor.world.get_entity(child_id)
        if _is_hidden(child):
            continue
        if child.has_component(CharacterComponent):
            occupant_count += 1
        elif child.has_component(PortableComponent):
            item_count += 1
    return WorldOverviewRoomView(
        id=str(room.id),
        title=room_component.title,
        biome=room_component.biome,
        indoor=room_component.indoor,
        private=room_component.private,
        occupant_count=occupant_count,
        item_count=item_count,
        exits=_room_exits(room),
    )


def serialize_world_overview(actor: WorldActor) -> WorldOverviewResponse:
    """Return a slim, admin-only map of the whole world: the full room network.

    Unlike ``serialize_world`` (a raw ECS dump) this exposes only the room graph -- ids,
    titles, exits, and occupant/item counts -- so admin and graph clients can render the
    network without the heavy snapshot. It is privileged: a regular player seeing every
    room would be cheating, so callers must enforce a permission check first.
    """

    rooms = sorted(
        actor.world.query().with_all([RoomComponent]).execute_entities(),
        key=lambda room: room.get_component(RoomComponent).title.lower(),
    )
    character_count = len(
        list(actor.world.query().with_all([CharacterComponent]).execute_entities())
    )
    return WorldOverviewResponse(
        world_epoch=actor.epoch,
        room_count=len(rooms),
        character_count=character_count,
        rooms=[_overview_room(actor, room) for room in rooms],
    )


def _target_for_entity(entity) -> ClientTargetView:
    return ClientTargetView(
        id=str(entity.id),
        label=entity_name(entity),
        kind=_entity_kind(entity),
    )


def _target_for_perceived(entity: PerceivedEntity) -> ClientTargetView:
    return ClientTargetView(
        id=entity.id,
        label=entity.name,
        kind="character" if entity.is_character else "object",
    )


def _inventory_targets(actor: WorldActor, character) -> list[ClientTargetView]:
    seen: set[str] = set()
    targets: list[ClientTargetView] = []
    # ``contents`` returns each Contains target once (the ECS keys relationships by target and
    # drops them when the target is removed), so no dangling/duplicate guard is needed here.
    for item_id in contents(character):
        item_key = str(item_id)
        seen.add(item_key)
        targets.append(_target_for_entity(actor.world.get_entity(item_id)))
    for edge_type in (Holding, Wearing):
        for _edge, item_id in character.get_relationships(edge_type):
            item_key = str(item_id)
            if item_key in seen:
                continue
            seen.add(item_key)
            targets.append(_target_for_entity(actor.world.get_entity(item_id)))
    return sorted(targets, key=lambda target: target.label.lower())


def _controller_display(controller) -> tuple[str, str, str]:
    if controller.has_component(DiscordControllerComponent):
        discord = controller.get_component(DiscordControllerComponent)
        return (
            "discord",
            f"Discord user {discord.discord_user_id}",
            f"channel {discord.default_channel_id}",
        )
    if controller.has_component(WebControllerComponent):
        web = controller.get_component(WebControllerComponent)
        label = web.label or web.client_id or "web"
        return ("web", label, web.client_id if web.client_id and web.client_id != label else "")
    if controller.has_component(MCPControllerComponent):
        mcp = controller.get_component(MCPControllerComponent)
        label = mcp.label or mcp.client_id or "MCP client"
        return ("mcp", label, mcp.client_id if mcp.client_id and mcp.client_id != label else "")
    if controller.has_component(LLMControllerComponent):
        llm = controller.get_component(LLMControllerComponent)
        detail = f"{llm.provider}/{llm.model}" if llm.model else llm.provider
        return ("llm", llm.profile_name, detail)
    if controller.has_component(BehaviorControllerComponent):
        behavior = controller.get_component(BehaviorControllerComponent)
        return ("behavior", behavior.behavior_name, f"every {behavior.act_every_ticks:g} tick(s)")
    if controller.has_component(ScriptedControllerComponent):
        scripted = controller.get_component(ScriptedControllerComponent)
        detail = "looping" if scripted.loop else ""
        return ("scripted", scripted.script_name or "scripted", detail)
    if controller.has_component(SuspendedControllerComponent):
        suspended = controller.get_component(SuspendedControllerComponent)
        return ("suspended", "Suspended", suspended.reason)
    return ("", entity_name(controller), "")


def _controller_view(actor: WorldActor, character) -> ClientControllerView | None:
    for edge, controller_id in character.get_relationships(ControlledBy):
        kind, name, detail = _controller_display(actor.world.get_entity(controller_id))
        return ClientControllerView(
            controller_id=str(controller_id),
            generation=edge.generation,
            kind=kind,
            name=name,
            detail=detail,
        )
    return None


def _points_view(character) -> ClientPointsView:
    action = (
        character.get_component(ActionPointsComponent)
        if character.has_component(ActionPointsComponent)
        else None
    )
    focus = (
        character.get_component(FocusPointsComponent)
        if character.has_component(FocusPointsComponent)
        else None
    )
    return ClientPointsView(
        action=action.current if action is not None else 0.0,
        action_max=action.maximum if action is not None else 0.0,
        focus=focus.current if focus is not None else 0.0,
        focus_max=focus.maximum if focus is not None else 0.0,
    )


_FIRST_RUN_CHECKLIST = (
    ("claim", "Claim a character."),
    ("look", "Look around."),
    ("room-action", "Use one available room action."),
    ("move", "Move once."),
    ("say", "Say something."),
    ("help-courier", "Help Moss the hungry courier."),
    ("watch-courier", "Watch Moss act through world rules."),
    ("inspect-consequence", "Check the activity feed, memory, or history."),
)


def _current_goal(character) -> str:
    if not character.has_component(GoalComponent):
        return ""
    goals = character.get_component(GoalComponent).active_goals
    return goals[0] if goals else ""


def _first_run_checklist() -> list[ClientChecklistItemView]:
    return [
        ClientChecklistItemView(id=item_id, text=text)
        for item_id, text in _FIRST_RUN_CHECKLIST
    ]


def _has_named_inventory(actor: WorldActor, character, query: str) -> bool:
    needle = query.lower()
    for item_id in contents(character):
        if not actor.world.has_entity(item_id):
            continue
        if needle in entity_name(actor.world.get_entity(item_id)).lower():
            return True
    return False


def _room_has_named_entity(actor: WorldActor, room_id, query: str) -> bool:
    needle = query.lower()
    if room_id is None or not actor.world.has_entity(room_id):
        return False
    for entity_id in contents(actor.world.get_entity(room_id)):
        if not actor.world.has_entity(entity_id):
            continue
        if needle in entity_name(actor.world.get_entity(entity_id)).lower():
            return True
    return False


def _first_run_suggestions(actor: WorldActor, character, room: ClientRoomView) -> list[str]:
    goal = _current_goal(character)
    if "Moss" not in goal and "courier" not in goal:
        return []

    has_apple = _has_named_inventory(actor, character, "apple")
    room_id = parse_entity_id(room.id)
    suggestions: list[str] = []
    if room.title == "Clover Post Office":
        if has_apple:
            suggestions.append("Drop the apple so Moss can eat it through the normal eat action.")
        else:
            suggestions.append("Go east to Market Lane and look for food Moss can reach.")
        suggestions.append("Leave the courier letter where Moss can take it after eating.")
    elif room.title == "Market Lane":
        if has_apple:
            suggestions.append("Go west to return the apple to Moss.")
        elif _room_has_named_entity(actor, room_id, "apple"):
            suggestions.append("Take the red market apple, then bring it west to Moss.")
        else:
            suggestions.append(
                "If the apple is gone, tell Moss what happened and watch the fallback."
            )
    elif room.title == "Moss Kiosk":
        suggestions.append("Inspect the delivery ledger or activity feed for the consequence.")
    if not suggestions:
        suggestions.append("Watch Moss choose eat, take, move, or write only when state allows it.")
    return suggestions


def _flatten_perceived(entities: Iterable[PerceivedEntity]) -> list[PerceivedEntity]:
    flattened: list[PerceivedEntity] = []
    for entity in entities:
        flattened.append(entity)
        flattened.extend(_flatten_perceived(entity.contents))
    return flattened


def _target_groups(
    actor: WorldActor,
    character,
    entities: tuple[PerceivedEntity, ...],
    exits: list[ClientExitView],
) -> dict[str, list[ClientTargetView]]:
    inventory = _inventory_targets(actor, character)
    visible = [_target_for_perceived(entity) for entity in _flatten_perceived(entities)]
    visible_by_id = {target.id: target for target in visible}
    carried_by_id = {target.id: target for target in inventory}
    room_items: list[ClientTargetView] = []
    for target in visible:
        # Perceived ids come from the perception projection, so they always resolve to a
        # live entity; only the kind/portable test gates whether it is a room item.
        entity = actor.world.get_entity(parse_entity_id(target.id))
        if target.kind != "character" and entity.has_component(PortableComponent):
            room_items.append(target)
    characters = [target for target in visible if target.kind == "character"]
    reachable = list({**visible_by_id, **carried_by_id}.values())
    return {
        "exits": [
            ClientTargetView(id=exit.id, label=exit.label, kind="exit")
            for exit in exits
        ],
        "roomItems": sorted(room_items, key=lambda target: target.label.lower()),
        "inventory": inventory,
        "characters": sorted(characters, key=lambda target: target.label.lower()),
        "reachable": sorted(reachable, key=lambda target: target.label.lower()),
        "reachableItems": sorted(
            [target for target in reachable if target.kind != "character"],
            key=lambda target: target.label.lower(),
        ),
    }


def _component(entity, component_type):
    return entity.get_component(component_type) if entity.has_component(component_type) else None


def _metric(
    label: str,
    value: float,
    maximum: float | None = None,
    *,
    text: str = "",
    band: str = "",
) -> ClientSheetMetricView:
    return ClientSheetMetricView(
        label=label,
        value=round(value, 2),
        maximum=round(maximum, 2) if maximum is not None else None,
        text=text,
        band=band,
    )


def _entry(label: str, value: object = "", detail: str = "") -> ClientSheetEntryView:
    return ClientSheetEntryView(label=label, value=str(value), detail=detail)


def _humanize_token(value: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return spaced.replace("_", " ").replace("-", " ").strip()


def _meter_metric(label: str, component) -> ClientSheetMetricView:
    meter = component.meter
    return _metric(
        label,
        meter.value,
        meter.maximum,
        text=f"{meter.value:g} / {meter.maximum:g}",
        band=meter_band(meter),
    )


def _sheet_vitals(character) -> list[ClientSheetMetricView]:
    vitals: list[ClientSheetMetricView] = []
    if health := _component(character, HealthComponent):
        vitals.append(
            _metric(
                "Health",
                health.current,
                health.maximum,
                text=f"{health.current:g} / {health.maximum:g}",
            )
        )
    if pain := _component(character, PainComponent):
        vitals.append(_metric("Pain", pain.current, 100.0, text=f"{pain.current:g}"))
    if bleeding := _component(character, BleedingComponent):
        vitals.append(
            _metric(
                "Bleeding",
                bleeding.rate,
                10.0,
                text=f"{bleeding.rate:g}/tick",
                band="urgent" if bleeding.rate > 0 else "calm",
            )
        )
    if encumbrance := _component(character, EncumbranceComponent):
        vitals.append(
            _metric(
                "Load",
                encumbrance.current_load,
                encumbrance.capacity,
                text=f"{encumbrance.current_load:g} / {encumbrance.capacity:g}",
                band="urgent" if encumbrance.overburdened else "calm",
            )
        )
    if initiative := _component(character, InitiativeComponent):
        vitals.append(_metric("Initiative", initiative.score, text=f"{initiative.score:g}"))
    return vitals


def _sheet_needs(character) -> list[ClientSheetMetricView]:
    rows: list[ClientSheetMetricView] = []
    for label, component_type in (
        ("Hunger", HungerComponent),
        ("Thirst", ThirstComponent),
        ("Fatigue", FatigueComponent),
        ("Hygiene", HygieneComponent),
        ("Comfort", ComfortNeedComponent),
        ("Fun", FunNeedComponent),
        ("Social", SocialNeedComponent),
        ("Privacy", PrivacyNeedComponent),
        ("Safety", SafetyNeedComponent),
    ):
        if component := _component(character, component_type):
            rows.append(_meter_metric(label, component))
    return rows


def _sheet_affect(character) -> list[ClientSheetMetricView]:
    affect = _component(character, AffectComponent)
    if affect is None:
        return []
    return [
        _metric(_humanize_token(name).title(), value, text=f"{value:g}")
        for name, value in jsonable(affect.current).items()
        if value
    ]


def _sheet_status(character) -> list[str]:
    status: list[str] = []
    if character.has_component(DeadComponent):
        status.append("dead")
    if character.has_component(DownedComponent):
        downed = character.get_component(DownedComponent)
        status.append("downed" + (" (stable)" if downed.stable else ""))
    if character.has_component(SleepingComponent):
        status.append("sleeping")
    if character.has_component(SuspendedComponent):
        status.append("suspended")
    if character.has_component(PregnancyComponent):
        status.append("pregnant")
    if character.has_component(WellRestedComponent):
        status.append("well rested")
    if bleeding := _component(character, BleedingComponent):
        if bleeding.rate > 0:
            status.append("bleeding")
    if character.has_component(InjuryComponent) or character.get_relationships(HasInjury):
        status.append("injured")
    if affect := _component(character, AffectComponent):
        status.extend(affect.labels)
    return status or ["active"]


def _sheet_profile(actor: WorldActor, character) -> list[ClientSheetEntryView]:
    rows: list[ClientSheetEntryView] = []
    identity = _component(character, IdentityComponent)
    rows.append(
        _entry("Kind", identity.kind if identity is not None and identity.kind else "character")
    )
    if stage := _component(character, LifeStageComponent):
        rows.append(_entry("Life Stage", stage.stage))
    if age := _component(character, AgeComponent):
        seconds = max(0, actor.epoch - age.born_at_epoch)
        years = seconds // (365 * 24 * 60 * 60)
        rows.append(_entry("Age", f"{years} years", f"born at epoch {age.born_at_epoch}"))
    if career := _component(character, CareerComponent):
        state = "active" if career.active else "inactive"
        rows.append(_entry("Career", career.title, f"level {career.level}, {state}"))
    if aspiration := _component(character, AspirationComponent):
        detail = ", ".join(aspiration.completed) if aspiration.completed else "in progress"
        rows.append(_entry("Aspiration", aspiration.name, detail))
    if household := _component(character, HouseholdComponent):
        rows.append(_entry("Household", household.name or household.household_id))
    if reputation := _component(character, ReputationComponent):
        rows.append(_entry("Reputation", f"{reputation.score:g}", ", ".join(reputation.known_for)))
    if persona := _component(character, PersonaProfileComponent):
        if persona.role:
            rows.append(_entry("Role", persona.role))
        if persona.voice:
            rows.append(_entry("Voice", persona.voice))
    if body := _component(character, BodyPlanComponent):
        rows.append(_entry("Body", ", ".join(body.parts), "vitals: " + ", ".join(body.vital_parts)))
    if weight := _component(character, WeightComponent):
        rows.append(_entry("Weight", f"{weight.weight:g}"))
    if pregnancy := _component(character, PregnancyComponent):
        rows.append(_entry("Pregnancy", f"due at epoch {pregnancy.due_at_epoch}"))
    return rows


def _sheet_traits(character) -> list[str]:
    traits: list[str] = []
    if profile := _component(character, CharacterProfileComponent):
        traits.extend(profile.traits)
        traits.extend(f"interested in {interest}" for interest in profile.interests)
        if profile.preferred_routine:
            traits.append(f"routine: {profile.preferred_routine}")
    if trait_set := _component(character, TraitSetComponent):
        traits.extend(trait_set.traits)
    if preference := _component(character, PreferenceComponent):
        traits.extend(f"likes {item}" for item in preference.likes)
        traits.extend(f"dislikes {item}" for item in preference.dislikes)
    if goals := _component(character, GoalComponent):
        traits.extend(f"goal: {goal}" for goal in goals.active_goals)
    if whim := _component(character, WhimComponent):
        if whim.completed_at_epoch is None:
            traits.append(f"whim: {whim.want}")
    return sorted(dict.fromkeys(traits))


def _sheet_skills(character) -> list[ClientSheetEntryView]:
    skills = _component(character, SkillSetComponent)
    if skills is None:
        return []
    return [
        _entry(
            _humanize_token(skill).title(),
            f"level {level}",
            f"{skills.xp.get(skill, 0.0):g} xp",
        )
        for skill, level in sorted(skills.levels.items())
    ]


def _sheet_injuries(actor: WorldActor, character) -> list[ClientSheetEntryView]:
    injuries: list[ClientSheetEntryView] = []
    if injury := _component(character, InjuryComponent):
        injuries.append(
            _entry(
                injury.body_part,
                f"severity {injury.severity:g}",
                f"pain {injury.pain:g}, bleeding {injury.bleeding_rate:g}",
            )
        )
    for _edge, injury_id in character.get_relationships(HasInjury):
        injury_entity = actor.world.get_entity(injury_id)
        if injury := _component(injury_entity, InjuryComponent):
            injuries.append(
                _entry(
                    injury.body_part,
                    f"severity {injury.severity:g}",
                    f"pain {injury.pain:g}, bleeding {injury.bleeding_rate:g}",
                )
            )
    return injuries


def _sheet_notes(actor: WorldActor, character) -> list[ClientSheetEntryView]:
    notes: list[ClientSheetEntryView] = []
    if description := _component(character, DescriptionComponent):
        if description.short:
            notes.append(_entry("Description", description.short))
        if description.appearance:
            notes.append(_entry("Appearance", description.appearance))
    for _edge, thought_id in character.get_relationships(HasThought):
        thought = actor.world.get_entity(thought_id)
        if thought_component := _component(thought, ThoughtComponent):
            notes.append(_entry("Thought", thought_component.label, thought_component.text))
    return notes


_RELATION_SKIP = {
    "Contains",
    "ControlledBy",
    "HasInjury",
    "HasThought",
    "Holding",
    "Wearing",
}


def _edge_detail(edge: dict[str, Any]) -> str:
    bits = [
        (
            f"{_humanize_token(key)} {value:g}"
            if isinstance(value, (int, float))
            else f"{_humanize_token(key)} {value}"
        )
        for key, value in sorted(edge.items())
        if value not in ("", 0, 0.0, None, False)
    ]
    return ", ".join(bits)


def _sheet_relations(actor: WorldActor, character) -> list[ClientSheetEntryView]:
    rows: list[ClientSheetEntryView] = []
    exported = actor.world.export_entity(character.id)
    for edge_name, edges in sorted(exported.get("relationships", {}).items()):
        if edge_name in _RELATION_SKIP:
            continue
        for edge in edges:
            target_id = parse_entity_id(str(edge["target"]))
            target = (
                actor.world.get_entity(target_id)
                if target_id is not None and actor.world.has_entity(target_id)
                else None
            )
            rows.append(
                _entry(
                    _humanize_token(edge_name).title(),
                    entity_name(target) if target is not None else str(edge["target"]),
                    _edge_detail(jsonable(edge.get("edge", {}))),
                )
            )
    return rows


def _character_sheet_projection(actor: WorldActor, character) -> ClientCharacterSheetView:
    character_component = character.get_component(CharacterComponent)
    identity = _component(character, IdentityComponent)
    description = _component(character, DescriptionComponent)
    return ClientCharacterSheetView(
        kind=identity.kind if identity is not None else "character",
        species=character_component.species,
        biography=character_component.biography,
        description=description.short if description is not None else "",
        appearance=description.appearance if description is not None else "",
        tags=list(identity.tags) if identity is not None else [],
        status=_sheet_status(character),
        vitals=_sheet_vitals(character),
        needs=_sheet_needs(character),
        affect=_sheet_affect(character),
        profile=_sheet_profile(actor, character),
        skills=_sheet_skills(character),
        traits=_sheet_traits(character),
        relations=_sheet_relations(actor, character),
        injuries=_sheet_injuries(actor, character),
        notes=_sheet_notes(actor, character),
    )


def _action_view(
    definition: ActionDefinition, availability: AvailabilityResult | None = None
) -> ClientActionView:
    arguments = [
        ClientActionArgumentView(
            key=key,
            title=argument.title,
            kind=argument.kind,
            required=argument.required,
            target_group=target_group_for_argument(definition, key),
        )
        for key, argument in (definition.arguments or {}).items()
    ]
    view = ClientActionView(
        command_type=definition.command_type,
        tool_name=definition.name,
        title=definition.title or definition.command_type.replace("-", " ").title(),
        description=definition.description,
        icon=definition.icon or action_icon_for(definition.command_type),
        lane=definition.lane,
        cost=CommandCostRequest(
            action=definition.cost.action,
            focus=definition.cost.focus,
        ),
        arguments=arguments,
    )
    if availability is not None:
        view.available = availability.available
        view.enough_action_points = availability.enough_action_points
        view.enough_focus_points = availability.enough_focus_points
        view.has_required_target = availability.has_required_target
        view.meets_requirements = availability.meets_requirements
        view.unavailable_reason = availability.reason
    return view


ACTION_SEARCH_MODES = ("substring", "word", "smart")

# Word boundaries for "word" search: any run of non-alphanumeric characters (hyphen,
# underscore, whitespace, and other punctuation) separates words.
_ACTION_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def _action_search_fields(definition: ActionDefinition) -> tuple[str, str, str]:
    return (definition.command_type, definition.title or "", definition.name)


def _action_matches(definition: ActionDefinition, needle: str, mode: str) -> bool:
    fields = _action_search_fields(definition)
    if mode == "word":
        return any(
            token.startswith(needle)
            for field in fields
            for token in _ACTION_WORD_SPLIT.split(field.lower())
            if token
        )
    return any(needle in field.lower() for field in fields)


def serialize_action_search(
    actor: WorldActor, query: str = "", limit: int = 30, mode: str = "substring"
) -> ActionSearchResponse:
    """Search the available action catalogue, returning a slim, paged action list.

    Progressive disclosure for clients that cannot render the whole catalogue at once
    (e.g. MCP clients): match ``query`` against each action's command_type, title, and tool
    name over the actions this world actually accepts. Mirrors the ``actions`` field of the
    character projection, which the web client filters client-side instead.

    ``mode`` is ``"substring"`` (default; matches anywhere, the TUI/Toon box behaviour),
    ``"word"`` (matches only where a word -- split on hyphen, underscore, whitespace, and
    other punctuation -- starts with the query, so ``"eat"`` no longer matches
    ``creature`` or ``defeat``), or ``"smart"`` (uses a Chroma collection with the action
    verbs and descriptions to rank the most relevant actions).
    """

    if mode not in ACTION_SEARCH_MODES:
        raise ValueError(f"mode must be one of {ACTION_SEARCH_MODES}")

    available = actor.available_command_types()
    definitions = sorted(
        (
            definition
            for definition in action_definitions(actor.action_definitions())
            if definition.command_type in available
        ),
        key=lambda definition: definition.command_type,
    )
    needle = (query or "").strip().lower()
    if needle and mode == "smart":
        definitions = smart_action_search(definitions, query=query.strip())
    elif needle:
        definitions = [
            definition
            for definition in definitions
            if _action_matches(definition, needle, mode)
        ]
    total_available = len(definitions)
    if limit and limit > 0:
        definitions = definitions[:limit]
    return ActionSearchResponse(
        world_epoch=actor.epoch,
        query=query or "",
        mode=mode,
        total_available=total_available,
        returned=len(definitions),
        actions=[_action_view(definition) for definition in definitions],
    )


def serialize_character_projection(
    actor: WorldActor, character_id: str
) -> CharacterProjectionResponse:
    """Return a viewer-scoped, player-facing view for structured clients.

    This intentionally differs from ``serialize_world``: it exposes only facts the
    character can use for normal play instead of raw ECS components and relationships.
    """

    character = _character_entity(actor, character_id)

    perception = perceive(actor.world, character)
    room = ClientRoomView()
    exits: list[ClientExitView] = []
    room_id = parse_entity_id(perception.room_id) or container_of(character)
    if room_id is not None and actor.world.has_entity(room_id):
        room_entity = actor.world.get_entity(room_id)
        room_title = (
            room_entity.get_component(RoomComponent).title
            if room_entity.has_component(RoomComponent)
            else str(room_id)
        )
        exits = [
            ClientExitView(
                id=exit.to_room_id,
                direction=exit.direction,
                label=f"{exit.direction}: {exit.to_room_id}" if exit.direction else exit.to_room_id,
                locked=exit.locked,
            )
            for exit in perception.exits
        ]
        room = ClientRoomView(
            id=str(room_id),
            title=room_title,
            entities=[_perceived_entity_view(entity) for entity in perception.entities],
            exits=exits,
        )

    groups = _target_groups(actor, character, perception.entities, exits)
    available_command_types = actor.available_command_types()
    return CharacterProjectionResponse(
        world_epoch=actor.epoch,
        character_id=str(character.id),
        character_name=entity_name(character),
        can_perceive=perception.can_perceive,
        portrait=_portrait_view(character),
        room=room,
        inventory=groups["inventory"],
        points=_points_view(character),
        controller=_controller_view(actor, character),
        sheet=_character_sheet_projection(actor, character),
        current_goal=_current_goal(character),
        suggested_actions=_first_run_suggestions(actor, character, room),
        checklist=_first_run_checklist(),
        target_groups=groups,
        actions=[
            _action_view(
                definition,
                evaluate_availability(actor, character, definition, target_groups=groups),
            )
            for definition in action_definitions(actor.action_definitions())
            if definition.command_type in available_command_types
        ],
    )


# Components surfaced by ``examine``. Public ones are outwardly observable; the self-only
# set adds the character's private needs/affect (others cannot read your exact hunger).
_EXAMINE_PUBLIC_COMPONENTS: tuple[tuple[type, str], ...] = (
    (DescriptionComponent, "description"),
    (PortableComponent, "portable"),
    (FoodComponent, "food"),
    (DrinkableComponent, "drinkable"),
    (DoorComponent, "door"),
    (ContainerComponent, "container"),
    (LightComponent, "light"),
)
_EXAMINE_SELF_COMPONENTS: tuple[tuple[type, str], ...] = _EXAMINE_PUBLIC_COMPONENTS + (
    (HungerComponent, "hunger"),
    (ThirstComponent, "thirst"),
    (FatigueComponent, "fatigue"),
    (AffectComponent, "affect"),
)
_EXAMINE_CONDITIONS: tuple[tuple[type, str], ...] = (
    (DeadComponent, "dead"),
    (DownedComponent, "downed"),
    (SleepingComponent, "asleep"),
    (SuspendedComponent, "suspended"),
)


def _examine_details(entity, *, is_self: bool) -> dict[str, Any]:
    catalogue = _EXAMINE_SELF_COMPONENTS if is_self else _EXAMINE_PUBLIC_COMPONENTS
    details: dict[str, Any] = {}
    for component_type, key in catalogue:
        if entity.has_component(component_type):
            details[key] = jsonable(entity.get_component(component_type))
    conditions = [
        name for component_type, name in _EXAMINE_CONDITIONS if entity.has_component(component_type)
    ]
    if conditions:
        details["condition"] = conditions
    return details


def _examine_perceivable_ids(actor: WorldActor, character) -> set[str]:
    perception = perceive(actor.world, character)
    ids = {str(character.id)}
    ids.update(entity.id for entity in _flatten_perceived(perception.entities))
    ids.update(target.id for target in _inventory_targets(actor, character))
    return ids


def serialize_examine(
    actor: WorldActor,
    character_id: str,
    target_id: str | None = None,
    *,
    fragment_providers: Sequence[Any] = (),
) -> ExamineResponse:
    """Return a curated, play-facing inspection of one perceivable entity (or self).

    Unlike ``component_schema`` (which describes component *types*), this returns the
    relevant component *values* on a specific entity the character can see or carry -- e.g.
    whether an item is food/spoiled or a door is locked, or, for the character itself, its
    own needs/affect plus status lines. The private needs/affect set is only returned when
    examining yourself, so a player cannot read another character's hidden state.
    """

    character = _character_entity(actor, character_id)
    resolved = parse_entity_id(target_id) if target_id is not None else character.id
    if resolved is None or not actor.world.has_entity(resolved):
        raise ValueError("entity does not exist")
    if str(resolved) not in _examine_perceivable_ids(actor, character):
        raise ValueError("entity is not perceivable")

    entity = actor.world.get_entity(resolved)
    is_self = resolved == character.id
    status: list[str] = []
    points = None
    if is_self:
        for provider in fragment_providers:
            status.extend(provider(actor.world, entity))
        points = _points_view(entity)
    return ExamineResponse(
        world_epoch=actor.epoch,
        id=str(entity.id),
        name=entity_name(entity),
        kind=_entity_kind(entity),
        is_character=entity.has_component(CharacterComponent),
        is_self=is_self,
        details=_examine_details(entity, is_self=is_self),
        status=status,
        points=points,
    )


def _dm_room_projection(actor: WorldActor, room) -> DmRoomProjectionView:
    facts = build_room_facts(actor.world, room.id)
    return DmRoomProjectionView(
        id=facts.room_id,
        title=facts.title,
        biome=facts.biome,
        occupants=[
            ClientTargetView(id=entity_id, label=name, kind="character")
            for entity_id, name in facts.occupants
        ],
        objects=[
            ClientEntityView(
                id=obj.id,
                name=obj.name,
                kind="object",
                is_character=False,
            )
            for obj in facts.objects
        ],
        exits=[
            ClientExitView(
                id=exit.to_room_id,
                direction=exit.direction,
                label=f"{exit.direction}: {exit.to_room_id}" if exit.direction else exit.to_room_id,
                locked=exit.locked,
            )
            for exit in facts.exits
        ],
    )


def serialize_dm_projection(actor: WorldActor, dm_id: str) -> DmProjectionResponse:
    """Return a permission-gated, structured moderator projection."""

    dm_id = dm_id.strip()
    if not dm_id:
        raise ValueError("dm id must not be blank")

    rooms = sorted(
        actor.world.query().with_all([RoomComponent]).execute_entities(),
        key=lambda room: entity_name(room).lower(),
    )
    characters = sorted(
        actor.world.query().with_all([CharacterComponent]).execute_entities(),
        key=lambda character: entity_name(character).lower(),
    )
    return DmProjectionResponse(
        world_epoch=actor.epoch,
        dm_id=dm_id,
        rooms=[_dm_room_projection(actor, room) for room in rooms],
        characters=[_target_for_entity(character) for character in characters],
    )


def serialize_event(event: DomainEvent) -> dict[str, Any]:
    """Return a typed event payload with class name and JSON-safe fields."""

    return {
        "event_type": event.__class__.__name__,
        "event": event.model_dump(mode="json"),
    }


def event_message(event: DomainEvent) -> dict[str, Any]:
    """Wrap a serialized event as a websocket message."""

    return {"type": "event", "data": serialize_event(event)}


__all__ = [
    "event_message",
    "jsonable",
    "serialize_character_projection",
    "serialize_character_queued_commands",
    "serialize_dm_projection",
    "serialize_entity",
    "serialize_event",
    "serialize_queued_command",
    "serialize_queued_commands",
    "serialize_room_projection",
    "serialize_world",
]
