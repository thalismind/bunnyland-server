"""Shared faction identity, membership, standing, and stance resolution."""

from __future__ import annotations

from enum import StrEnum

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from ...core.commands import SubmittedCommand
from ...core.ecs import entity_name, parse_entity_id, room_id_for
from ...core.events import DomainEvent, EventVisibility
from ...core.handlers import HandlerContext, HandlerResult, planned, rejected
from ...core.mutations import AddEdge, MutationPlan, RemoveEdge
from ...projections.perception import perceive
from ...prompts import ComponentPromptContext


class FactionDispositionStance(StrEnum):
    """A directed faction-to-faction policy."""

    FRIENDLY = "friendly"
    HOSTILE = "hostile"


class FactionStance(StrEnum):
    """An actor's resolved observer-relative stance toward another actor."""

    FRIENDLY = "friendly"
    HOSTILE = "hostile"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class FactionComponent(Component):
    """Singleton identity and visibility policy for a faction entity."""

    name: str
    ideology: str = ""
    secret: bool = False


@dataclass(frozen=True)
class MemberOfFaction(Edge):
    """Repeatable character -> faction membership."""

    rank: str = "member"
    since_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or not ctx.can_view_private_state or ctx.target is None:
            return ()
        faction_name = (
            ctx.target.get_component(FactionComponent).name
            if ctx.target.has_component(FactionComponent)
            else entity_name(ctx.target)
        )
        return (f"You are a {self.rank} of {faction_name}.",)


@dataclass(frozen=True)
class HasStandingWithFaction(Edge):
    """Repeatable character -> faction standing score."""

    score: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or not ctx.can_view_private_state or ctx.target is None:
            return ()
        faction_name = (
            ctx.target.get_component(FactionComponent).name
            if ctx.target.has_component(FactionComponent)
            else entity_name(ctx.target)
        )
        return (f"Faction standing with {faction_name}: {self.score}.",)


@dataclass(frozen=True)
class FactionDisposition(Edge):
    """Directed faction -> faction policy used by observer-relative stance resolution."""

    stance: FactionDispositionStance = FactionDispositionStance.FRIENDLY


class FactionJoinedEvent(DomainEvent):
    faction_id: str
    faction_name: str
    rank: str = "member"


class FactionLeftEvent(DomainEvent):
    faction_id: str
    faction_name: str


def _faction_ids(entity: Entity) -> tuple[EntityId, ...]:
    targets = (target for _edge, target in entity.get_relationships(MemberOfFaction))
    return tuple(sorted(targets, key=str))


def resolve_faction_stance(
    world: World, observer_faction_id: EntityId, target_faction_id: EntityId
) -> FactionStance:
    """Resolve one directed faction pair, with shared identity treated as friendly."""

    if observer_faction_id == target_faction_id:
        return FactionStance.FRIENDLY
    if not world.has_entity(observer_faction_id) or not world.has_entity(target_faction_id):
        return FactionStance.NEUTRAL
    observer_faction = world.get_entity(observer_faction_id)
    for disposition, target_id in observer_faction.get_relationships(FactionDisposition):
        if target_id != target_faction_id:
            continue
        if disposition.stance is FactionDispositionStance.HOSTILE:
            return FactionStance.HOSTILE
        return FactionStance.FRIENDLY
    return FactionStance.NEUTRAL


def resolve_actor_stance(world: World, observer: Entity, target: Entity) -> FactionStance:
    """Resolve how ``observer`` regards ``target`` through all faction memberships.

    Dispositions are directed from the observer's factions. Any hostile pair wins;
    otherwise any shared or explicitly friendly pair is friendly.
    """

    observer_factions = _faction_ids(observer)
    target_factions = _faction_ids(target)
    friendly = bool(set(observer_factions) & set(target_factions))
    for observer_faction_id in observer_factions:
        for target_faction_id in target_factions:
            stance = resolve_faction_stance(world, observer_faction_id, target_faction_id)
            if stance is FactionStance.HOSTILE:
                return FactionStance.HOSTILE
            if stance is FactionStance.FRIENDLY:
                friendly = True
    return FactionStance.FRIENDLY if friendly else FactionStance.NEUTRAL


class JoinFactionHandler:
    command_type = "join-faction"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        faction_id = parse_entity_id(command.payload.get("faction_id"))
        rank = str(command.payload.get("rank", "member")).strip() or "member"
        if character_id is None or faction_id is None:
            return rejected("invalid character or faction id")
        if not ctx.world.has_entity(faction_id):
            return rejected("faction does not exist")
        character = ctx.entity(character_id)
        faction = ctx.entity(faction_id)
        if not faction.has_component(FactionComponent):
            return rejected("target is not a faction")
        faction_component = faction.get_component(FactionComponent)
        if faction_component.secret:
            return rejected("secret factions cannot be joined publicly")
        if character.has_relationship(MemberOfFaction, faction_id):
            return rejected("already a faction member")

        return planned(
            MutationPlan(
                (
                    AddEdge(
                        character_id,
                        faction_id,
                        MemberOfFaction(rank=rank, since_epoch=ctx.epoch),
                    ),
                )
            ),
            FactionJoinedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=room_id_for(ctx.world, character_id),
                    target_ids=(str(faction_id),),
                    faction_id=str(faction_id),
                    faction_name=faction_component.name,
                    rank=rank,
                )
            ),
        )


class LeaveFactionHandler:
    command_type = "leave-faction"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        faction_id = parse_entity_id(command.payload.get("faction_id"))
        if character_id is None or faction_id is None:
            return rejected("invalid character or faction id")
        if not ctx.world.has_entity(faction_id):
            return rejected("faction does not exist")
        character = ctx.entity(character_id)
        faction = ctx.entity(faction_id)
        if not faction.has_component(FactionComponent):
            return rejected("target is not a faction")
        faction_component = faction.get_component(FactionComponent)
        if faction_component.secret:
            return rejected("secret factions cannot be left publicly")
        if not character.has_relationship(MemberOfFaction, faction_id):
            return rejected("not a faction member")

        return planned(
            MutationPlan((RemoveEdge(character_id, faction_id, MemberOfFaction),)),
            FactionLeftEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=room_id_for(ctx.world, character_id),
                    target_ids=(str(faction_id),),
                    faction_id=str(faction_id),
                    faction_name=faction_component.name,
                )
            ),
        )


def faction_fragments(world: World, character: Entity) -> list[str]:
    """Private affiliations plus generic observer-relative nearby stance."""

    lines: list[str] = []
    context = ComponentPromptContext.for_entity(world, character)
    for edge, faction_id in character.get_relationships(MemberOfFaction):
        faction = world.get_entity(faction_id)
        edge_context = ComponentPromptContext.for_entity(
            world, character, perspective=context.perspective, target=faction
        )
        lines.extend(edge.prompt_fragments(edge_context))
    for edge, faction_id in character.get_relationships(HasStandingWithFaction):
        faction = world.get_entity(faction_id)
        edge_context = ComponentPromptContext.for_entity(
            world, character, perspective=context.perspective, target=faction
        )
        lines.extend(edge.prompt_fragments(edge_context))

    perception = perceive(world, character)
    for perceived in perception.entities:
        if not perceived.is_character:
            continue
        target_id = parse_entity_id(perceived.id)
        if target_id is None or not world.has_entity(target_id):
            continue
        stance = resolve_actor_stance(world, character, world.get_entity(target_id))
        lines.append(f"Nearby {perceived.name} is {stance.value}.")
    return sorted(lines)


__all__ = [
    "FactionComponent",
    "FactionDisposition",
    "FactionDispositionStance",
    "FactionJoinedEvent",
    "FactionLeftEvent",
    "FactionStance",
    "HasStandingWithFaction",
    "JoinFactionHandler",
    "LeaveFactionHandler",
    "MemberOfFaction",
    "faction_fragments",
    "resolve_actor_stance",
    "resolve_faction_stance",
]
