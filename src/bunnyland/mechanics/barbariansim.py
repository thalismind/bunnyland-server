"""Barbarian-sim combat, PvP, and roleplay mechanics (spec 21.4).

Combat writes only health/status state; existing downed/death consequences decide later
outcomes. PvP and lethal PvP are policy-gated before damage is applied.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, EntityId, Frequency, System, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    BodyPlanComponent,
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    HealthComponent,
    InjuryComponent,
    PortableComponent,
    SuspendedComponent,
)
from ..core.ecs import container_of, parse_entity_id, reachable_ids, replace_component, spawn_entity
from ..core.edges import ContainmentMode, Contains, HasInjury, Wearing
from ..core.events import (
    CharacterAttackedEvent,
    CharacterDefendedEvent,
    CharacterPickpocketedEvent,
    CombatChallengeEvent,
    DomainEvent,
    EventVisibility,
    FortificationBuiltEvent,
    InjuryAddedEvent,
    RaidStartedEvent,
)
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .policy import BoundaryTag, PolicyGate

UNARMED_DAMAGE = 5.0
DEFEND_REDUCTION = 2.0
ATTACK_STAMINA_COST = 3.0
SPAR_STAMINA_COST = 2.0
DEFEND_STAMINA_COST = 2.0


@dataclass(frozen=True)
class StaminaComponent(Component):
    current: float = 10.0
    maximum: float = 10.0
    regen_per_hour: float = 4.0


@dataclass(frozen=True)
class WeaponComponent(Component):
    damage: float = UNARMED_DAMAGE
    damage_type: str = "blunt"
    lethal_capable: bool = False


@dataclass(frozen=True)
class ArmorComponent(Component):
    rating: float = 0.0


@dataclass(frozen=True)
class DefendingComponent(Component):
    started_at_epoch: int
    reduction: float = DEFEND_REDUCTION


@dataclass(frozen=True)
class FortificationComponent(Component):
    rating: float = 1.0
    durability: float = 10.0


class StaminaChangedEvent(DomainEvent):
    current: float
    maximum: float
    reason: str = ""


class StaminaRegenSystem(System):
    def query(self):
        return self.q.with_all([StaminaComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        del components
        for entity in entities:
            stamina = entity.get_component(StaminaComponent)
            gained = stamina.regen_per_hour * (delta / 3600.0)
            current = min(stamina.maximum, stamina.current + gained)
            if current != stamina.current:
                replace_component(entity, replace(stamina, current=current))


def pvp_classifier(command: SubmittedCommand):
    if command.command_type in {"attack", "spar"}:
        return BoundaryTag.PVP, _participants(command)
    return None


def lethal_pvp_classifier(command: SubmittedCommand):
    if command.command_type == "attack" and bool(command.payload.get("lethal", False)):
        return BoundaryTag.LETHAL_PVP, _participants(command)
    return None


def pickpocket_classifier(command: SubmittedCommand):
    if command.command_type == "pickpocket":
        return BoundaryTag.PICKPOCKETING, _participants(command)
    return None


def _participants(command: SubmittedCommand) -> list[str]:
    target = command.payload.get("target_id")
    return [command.character_id, str(target)] if target is not None else [command.character_id]


def _same_room(world: World, left_id: EntityId, right_id: EntityId) -> bool:
    return container_of(world.get_entity(left_id)) == container_of(world.get_entity(right_id))


def _can_fight(entity) -> bool:
    return (
        entity.has_component(CharacterComponent)
        and not entity.has_component(SuspendedComponent)
        and not entity.has_component(DownedComponent)
        and not entity.has_component(DeadComponent)
    )


def _weapon_damage(ctx: HandlerContext, actor_id: EntityId, weapon_id: EntityId | None) -> float:
    if weapon_id is None:
        return UNARMED_DAMAGE
    actor = ctx.entity(actor_id)
    if weapon_id not in reachable_ids(ctx.world, actor):
        return -1.0
    weapon = ctx.entity(weapon_id)
    if not weapon.has_component(WeaponComponent):
        return -1.0
    return weapon.get_component(WeaponComponent).damage


def _armor_rating(ctx: HandlerContext, target_id: EntityId) -> float:
    target = ctx.entity(target_id)
    rating = (
        target.get_component(ArmorComponent).rating
        if target.has_component(ArmorComponent)
        else 0.0
    )
    for _edge, item_id in target.get_relationships(Wearing):
        item = ctx.entity(item_id)
        if item.has_component(ArmorComponent):
            rating += item.get_component(ArmorComponent).rating
    return rating


def _body_part(target, requested: object) -> str:
    if isinstance(requested, str) and requested:
        return requested
    if target.has_component(BodyPlanComponent):
        parts = target.get_component(BodyPlanComponent).parts
        if parts:
            return parts[0]
    return "body"


def _spend_stamina(
    ctx: HandlerContext,
    entity_id: EntityId,
    amount: float,
    *,
    reason: str,
) -> tuple[bool, str | None, StaminaChangedEvent | None]:
    entity = ctx.entity(entity_id)
    if amount <= 0 or not entity.has_component(StaminaComponent):
        return True, None, None
    stamina = entity.get_component(StaminaComponent)
    if stamina.current < amount:
        return False, "insufficient stamina", None
    updated = replace(stamina, current=stamina.current - amount)
    replace_component(entity, updated)
    return (
        True,
        None,
        StaminaChangedEvent(
            **ctx.event_base(
                visibility=EventVisibility.PRIVATE,
                actor_id=str(entity_id),
                current=updated.current,
                maximum=updated.maximum,
                reason=reason,
            )
        ),
    )


class AttackHandler:
    command_type = "attack"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        return _resolve_attack(ctx, command, sparring=False)


class SparHandler:
    command_type = "spar"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        return _resolve_attack(ctx, command, sparring=True)


def _resolve_attack(
    ctx: HandlerContext, command: SubmittedCommand, *, sparring: bool
) -> HandlerResult:
    actor_id = parse_entity_id(command.character_id)
    target_id = parse_entity_id(command.payload.get("target_id"))
    weapon_id = parse_entity_id(command.payload.get("weapon_id"))
    if actor_id is None or target_id is None:
        return rejected("invalid attacker or target id")
    if not ctx.world.has_entity(target_id):
        return rejected("target does not exist")

    actor = ctx.entity(actor_id)
    target = ctx.entity(target_id)
    if not _can_fight(target):
        return rejected("target cannot fight")
    if not _same_room(ctx.world, actor_id, target_id):
        return rejected("target is not present")
    if not target.has_component(HealthComponent):
        return rejected("target has no health")

    stamina_cost = float(
        command.payload.get(
            "stamina_cost",
            SPAR_STAMINA_COST if sparring else ATTACK_STAMINA_COST,
        )
    )
    allowed, reason, stamina_event = _spend_stamina(
        ctx,
        actor_id,
        stamina_cost,
        reason="spar" if sparring else "attack",
    )
    if not allowed:
        return rejected(reason or "insufficient stamina")

    raw_damage = _weapon_damage(ctx, actor_id, weapon_id)
    if raw_damage < 0:
        return rejected("weapon is not usable")
    armor = _armor_rating(ctx, target_id)
    defend = (
        target.get_component(DefendingComponent).reduction
        if target.has_component(DefendingComponent)
        else 0.0
    )
    damage = max(0.0, raw_damage - armor - defend)
    lethal = bool(command.payload.get("lethal", False)) and not sparring
    health = target.get_component(HealthComponent)
    next_health = health.current - damage
    if not lethal:
        next_health = max(1.0, next_health)
    replace_component(target, replace(health, current=next_health))
    if target.has_component(DefendingComponent):
        target.remove_component(DefendingComponent)

    events: list[DomainEvent] = []
    if stamina_event is not None:
        events.append(stamina_event)
    events.append(
        CharacterAttackedEvent(
            **ctx.event_base(
                visibility=EventVisibility.ROOM,
                actor_id=str(actor_id),
                room_id=str(container_of(actor)) if container_of(actor) else None,
                target_ids=(str(target_id),),
                target_id=str(target_id),
                weapon_id=str(weapon_id) if weapon_id is not None else None,
                damage=damage,
                lethal=lethal,
                sparring=sparring,
            )
        )
    )
    if damage > 0:
        body_part = _body_part(target, command.payload.get("body_part"))
        injury = spawn_entity(
            ctx.world,
            [
                InjuryComponent(
                    body_part=body_part,
                    severity=damage,
                    pain=damage,
                    bleeding_rate=damage * 0.1,
                    applied_at_epoch=ctx.epoch,
                )
            ],
        )
        target.add_relationship(HasInjury(), injury.id)
        events.append(
            InjuryAddedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(actor)) if container_of(actor) else None,
                    target_ids=(str(target_id), str(injury.id)),
                    injury_id=str(injury.id),
                    body_part=body_part,
                    severity=damage,
                    bleeding_rate=damage * 0.1,
                )
            )
        )

    return ok(*events)


class DefendHandler:
    command_type = "defend"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        stamina_cost = float(command.payload.get("stamina_cost", DEFEND_STAMINA_COST))
        allowed, reason, stamina_event = _spend_stamina(
            ctx, actor_id, stamina_cost, reason="defend"
        )
        if not allowed:
            return rejected(reason or "insufficient stamina")
        character = ctx.entity(actor_id)
        replace_component(
            character,
            DefendingComponent(
                started_at_epoch=ctx.epoch,
                reduction=float(command.payload.get("reduction", DEFEND_REDUCTION)),
            ),
        )
        events: list[DomainEvent] = []
        if stamina_event is not None:
            events.append(stamina_event)
        events.append(
            CharacterDefendedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    reduction=character.get_component(DefendingComponent).reduction,
                )
            )
        )
        return ok(*events)


class ChallengeHandler:
    command_type = "challenge"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        terms = str(command.payload.get("terms", "")).strip()
        if actor_id is None or target_id is None:
            return rejected("invalid challenger or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")
        return ok(
            CombatChallengeEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(ctx.entity(actor_id))),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    terms=terms,
                )
            )
        )


class FortifyHandler:
    command_type = "fortify"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None:
            return rejected("invalid character id")
        character = ctx.entity(actor_id)
        if target_id is None:
            target_id = container_of(character)
        if target_id is None or not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        target = ctx.entity(target_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")

        strength = float(command.payload.get("strength", 1.0))
        if strength <= 0:
            return rejected("fortification strength must be positive")
        current = (
            target.get_component(FortificationComponent)
            if target.has_component(FortificationComponent)
            else FortificationComponent(rating=0.0, durability=0.0)
        )
        updated = FortificationComponent(
            rating=current.rating + strength,
            durability=current.durability + strength * 5.0,
        )
        replace_component(target, updated)
        return ok(
            FortificationBuiltEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    durability=updated.durability,
                    rating=updated.rating,
                )
            )
        )


class RaidHandler:
    command_type = "raid"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid raider or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        character = ctx.entity(actor_id)
        target = ctx.entity(target_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")

        intensity = float(command.payload.get("intensity", 1.0))
        if intensity <= 0:
            return rejected("raid intensity must be positive")
        fortification = (
            target.get_component(FortificationComponent)
            if target.has_component(FortificationComponent)
            else FortificationComponent(rating=0.0, durability=0.0)
        )
        damage = max(0.0, intensity - fortification.rating)
        if fortification.durability > 0:
            replace_component(
                target,
                replace(fortification, durability=max(0.0, fortification.durability - damage)),
            )
        return ok(
            RaidStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    intensity=intensity,
                    damage=damage,
                )
            )
        )


class PickpocketHandler:
    command_type = "pickpocket"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        item_id = parse_entity_id(command.payload.get("item_id"))
        if actor_id is None or target_id is None or item_id is None:
            return rejected("invalid thief, target, or item id")
        if not ctx.world.has_entity(target_id) or not ctx.world.has_entity(item_id):
            return rejected("target or item does not exist")

        actor = ctx.entity(actor_id)
        target = ctx.entity(target_id)
        item = ctx.entity(item_id)
        if not _can_fight(target):
            return rejected("target cannot be pickpocketed")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")
        if container_of(item) != target_id:
            return rejected("item is not in target inventory")
        if not item.has_component(PortableComponent) or not item.get_component(
            PortableComponent
        ).can_pick_up:
            return rejected("item cannot be taken")

        target.remove_relationship(Contains, item_id)
        actor.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item_id)
        return ok(
            CharacterPickpocketedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    room_id=str(container_of(actor)) if container_of(actor) else None,
                    target_ids=(str(target_id), str(item_id)),
                    target_id=str(target_id),
                    item_id=str(item_id),
                )
            )
        )


def barbariansim_fragments(world: World, character) -> list[str]:
    lines: list[str] = []
    if character.has_component(StaminaComponent):
        stamina = character.get_component(StaminaComponent)
        lines.append(f"Stamina: {stamina.current:g}/{stamina.maximum:g}.")
    if character.has_component(DefendingComponent):
        lines.append("You are defending yourself.")
    if character.has_component(ArmorComponent):
        lines.append(f"Your armor rating is {character.get_component(ArmorComponent).rating}.")
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(WeaponComponent):
            weapon = entity.get_component(WeaponComponent)
            lines.append(f"Reachable weapon: {weapon.damage_type} ({weapon.damage} damage).")
        if entity.has_component(FortificationComponent):
            fort = entity.get_component(FortificationComponent)
            lines.append(
                f"Reachable fortification: rating {fort.rating}, durability {fort.durability}."
            )
    return sorted(lines)


def install_barbariansim(actor) -> None:
    actor.world.register_system(StaminaRegenSystem())
    actor.register_gate(
        PolicyGate((pvp_classifier, lethal_pvp_classifier, pickpocket_classifier))
    )


__all__ = [
    "ArmorComponent",
    "AttackHandler",
    "ChallengeHandler",
    "DefendHandler",
    "DefendingComponent",
    "FortificationComponent",
    "FortifyHandler",
    "PickpocketHandler",
    "RaidHandler",
    "SparHandler",
    "StaminaChangedEvent",
    "StaminaComponent",
    "StaminaRegenSystem",
    "WeaponComponent",
    "barbariansim_fragments",
    "install_barbariansim",
    "lethal_pvp_classifier",
    "pickpocket_classifier",
    "pvp_classifier",
]
