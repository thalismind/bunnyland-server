"""Dagger-sim procedural RPG realm mechanics.

This package owns the gameplay reasons for expanding civic RPG content. Worldgen may
propose the actual rooms and entities later; dagger-sim tracks when a stub location has
become real enough for play to reference.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import IdentityComponent
from ..core.ecs import container_of, parse_entity_id, reachable_ids, replace_component
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected


@dataclass(frozen=True)
class ProceduralSiteComponent(Component):
    site_type: str
    seed: str
    generated: bool = False
    generator_id: str | None = None


@dataclass(frozen=True)
class UnrealizedLocationComponent(Component):
    summary: str
    region_id: str
    detail_level: str = "stub"


@dataclass(frozen=True)
class ExpansionHookComponent(Component):
    trigger: str
    generator_plugin_id: str
    priority: int = 0


class ExpansionRequestedEvent(DomainEvent):
    site_id: str
    site_type: str
    trigger: str
    generator_plugin_id: str | None = None


class GeneratedSiteInstantiatedEvent(DomainEvent):
    site_id: str
    site_type: str
    detail_level: str
    generator_plugin_id: str | None = None


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


class ExpandSiteHandler:
    command_type = "expand-site"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        site_id = parse_entity_id(command.payload.get("site_id"))
        if character_id is None or site_id is None:
            return rejected("invalid character or site id")
        if not ctx.world.has_entity(site_id):
            return rejected("site does not exist")

        character = ctx.entity(character_id)
        if site_id not in reachable_ids(ctx.world, character):
            return rejected("site is not reachable")
        site = ctx.entity(site_id)
        if not site.has_component(ProceduralSiteComponent):
            return rejected("target is not a procedural site")
        if not site.has_component(UnrealizedLocationComponent):
            return rejected("target is already realized")

        procedural = site.get_component(ProceduralSiteComponent)
        unrealized = site.get_component(UnrealizedLocationComponent)
        if procedural.generated or unrealized.detail_level == "instantiated":
            return rejected("site is already instantiated")

        hook = (
            site.get_component(ExpansionHookComponent)
            if site.has_component(ExpansionHookComponent)
            else None
        )
        generator_id = str(
            command.payload.get(
                "generator_id",
                hook.generator_plugin_id if hook is not None else procedural.generator_id or "",
            )
        ).strip() or None
        trigger = str(
            command.payload.get("trigger", hook.trigger if hook is not None else "manual")
        )

        replace_component(
            site,
            replace(procedural, generated=True, generator_id=generator_id),
        )
        replace_component(site, replace(unrealized, detail_level="instantiated"))
        return ok(
            ExpansionRequestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site_id),),
                    site_id=str(site_id),
                    site_type=procedural.site_type,
                    trigger=trigger,
                    generator_plugin_id=generator_id,
                )
            ),
            GeneratedSiteInstantiatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site_id),),
                    site_id=str(site_id),
                    site_type=procedural.site_type,
                    detail_level="instantiated",
                    generator_plugin_id=generator_id,
                )
            ),
        )


def daggersim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if not entity.has_component(UnrealizedLocationComponent):
            continue
        unrealized = entity.get_component(UnrealizedLocationComponent)
        if unrealized.detail_level == "instantiated":
            continue
        site_type = (
            entity.get_component(ProceduralSiteComponent).site_type
            if entity.has_component(ProceduralSiteComponent)
            else "site"
        )
        lines.append(
            f"Nearby unrealized {site_type}: {_name(entity)} ({unrealized.summary})."
        )
    return sorted(lines)


__all__ = [
    "ExpandSiteHandler",
    "ExpansionHookComponent",
    "ExpansionRequestedEvent",
    "GeneratedSiteInstantiatedEvent",
    "ProceduralSiteComponent",
    "UnrealizedLocationComponent",
    "daggersim_fragments",
]
