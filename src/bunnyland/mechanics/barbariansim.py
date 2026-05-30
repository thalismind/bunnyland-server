"""Barbarian-sim combat, PvP, and roleplay mechanics (spec 21.4).

Combat writes only health/status state; existing downed/death consequences decide later
outcomes. PvP and lethal PvP are policy-gated before damage is applied.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

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
    RoomComponent,
    SuspendedComponent,
    TemperatureComponent,
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
HOT_SAFE_CELSIUS = 30.0
COLD_SAFE_CELSIUS = 5.0
EXPOSURE_DANGER = 10.0
EXPOSURE_DAMAGE_PER_HOUR = 5.0
EXPOSURE_RECOVERY_PER_HOUR = 4.0


@dataclass(frozen=True)
class TemperatureResistanceComponent(Component):
    heat: float = 0.0
    cold: float = 0.0


@dataclass(frozen=True)
class ShelterComponent(Component):
    temperature_buffer: float = 0.0


@dataclass(frozen=True)
class TemperatureExposureComponent(Component):
    heat: float = 0.0
    cold: float = 0.0
    heat_danger: bool = False
    cold_danger: bool = False
    last_updated_epoch: int = 0


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


class ExposureChangedEvent(DomainEvent):
    character_id: str
    ambient_celsius: float | None = None
    heat: float
    cold: float


class HeatstrokeStartedEvent(DomainEvent):
    character_id: str
    heat: float


class FrostbiteStartedEvent(DomainEvent):
    character_id: str
    cold: float


class ExposureDamageEvent(DomainEvent):
    character_id: str
    damage: float
    cause: str
    health: float


def _barbarian_event_base(epoch: int, **kwargs) -> dict:
    base = {"event_id": uuid4().hex, "world_epoch": epoch, "created_at": datetime.now(UTC)}
    base.update(kwargs)
    return base


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


def _temperature_buffer(world: World, character_id: EntityId, room_id: EntityId | None) -> float:
    character = world.get_entity(character_id)
    buffer = 0.0
    if character.has_component(ShelterComponent):
        buffer += character.get_component(ShelterComponent).temperature_buffer
    if room_id is not None and world.has_entity(room_id):
        room = world.get_entity(room_id)
        if room.has_component(RoomComponent) and room.get_component(RoomComponent).indoor:
            buffer += 5.0
        if room.has_component(ShelterComponent):
            buffer += room.get_component(ShelterComponent).temperature_buffer
    return buffer


def _ambient_celsius(world: World, room_id: EntityId | None) -> float | None:
    if room_id is None or not world.has_entity(room_id):
        return None
    room = world.get_entity(room_id)
    if not room.has_component(TemperatureComponent):
        return None
    return room.get_component(TemperatureComponent).celsius


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


class TemperatureExposureConsequence:
    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = (
            world.query()
            .with_all([CharacterComponent, TemperatureExposureComponent])
            .with_none([DeadComponent, SuspendedComponent])
        )
        for character in query.execute_entities():
            exposure = character.get_component(TemperatureExposureComponent)
            elapsed = max(0, epoch - exposure.last_updated_epoch)
            if elapsed <= 0:
                continue

            room_id = container_of(character)
            ambient = _ambient_celsius(world, room_id)
            resistance = (
                character.get_component(TemperatureResistanceComponent)
                if character.has_component(TemperatureResistanceComponent)
                else TemperatureResistanceComponent()
            )
            buffer = _temperature_buffer(world, character.id, room_id)
            hours = elapsed / 3600.0
            heat = exposure.heat
            cold = exposure.cold

            if ambient is None:
                heat = max(0.0, heat - EXPOSURE_RECOVERY_PER_HOUR * hours)
                cold = max(0.0, cold - EXPOSURE_RECOVERY_PER_HOUR * hours)
            else:
                hot_limit = HOT_SAFE_CELSIUS + resistance.heat + buffer
                cold_limit = COLD_SAFE_CELSIUS - resistance.cold - buffer
                if ambient > hot_limit:
                    heat += (ambient - hot_limit) * hours
                    cold = max(0.0, cold - EXPOSURE_RECOVERY_PER_HOUR * hours)
                elif ambient < cold_limit:
                    cold += (cold_limit - ambient) * hours
                    heat = max(0.0, heat - EXPOSURE_RECOVERY_PER_HOUR * hours)
                else:
                    heat = max(0.0, heat - EXPOSURE_RECOVERY_PER_HOUR * hours)
                    cold = max(0.0, cold - EXPOSURE_RECOVERY_PER_HOUR * hours)

            heat_danger = heat >= EXPOSURE_DANGER
            cold_danger = cold >= EXPOSURE_DANGER
            if heat == exposure.heat and cold == exposure.cold:
                replace_component(character, replace(exposure, last_updated_epoch=epoch))
                continue

            updated = TemperatureExposureComponent(
                heat=heat,
                cold=cold,
                heat_danger=heat_danger,
                cold_danger=cold_danger,
                last_updated_epoch=epoch,
            )
            replace_component(character, updated)
            events.append(
                ExposureChangedEvent(
                    **_barbarian_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character.id),
                        room_id=str(room_id) if room_id is not None else None,
                        character_id=str(character.id),
                        ambient_celsius=ambient,
                        heat=heat,
                        cold=cold,
                    )
                )
            )
            if heat_danger and not exposure.heat_danger:
                events.append(
                    HeatstrokeStartedEvent(
                        **_barbarian_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=str(room_id) if room_id is not None else None,
                            character_id=str(character.id),
                            heat=heat,
                        )
                    )
                )
            if cold_danger and not exposure.cold_danger:
                events.append(
                    FrostbiteStartedEvent(
                        **_barbarian_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=str(room_id) if room_id is not None else None,
                            character_id=str(character.id),
                            cold=cold,
                        )
                    )
                )
            if character.has_component(HealthComponent) and (heat_danger or cold_danger):
                cause = "heat exposure" if heat >= cold else "cold exposure"
                damage = EXPOSURE_DAMAGE_PER_HOUR * hours
                health = character.get_component(HealthComponent)
                updated_health = replace(health, current=health.current - damage)
                replace_component(character, updated_health)
                events.append(
                    ExposureDamageEvent(
                        **_barbarian_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=str(room_id) if room_id is not None else None,
                            character_id=str(character.id),
                            damage=damage,
                            cause=cause,
                            health=updated_health.current,
                        )
                    )
                )
        return events


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
    if character.has_component(TemperatureExposureComponent):
        exposure = character.get_component(TemperatureExposureComponent)
        if exposure.heat or exposure.cold:
            lines.append(f"Exposure: heat {exposure.heat:g}, cold {exposure.cold:g}.")
        if exposure.heat_danger:
            lines.append("You are suffering dangerous heat exposure.")
        if exposure.cold_danger:
            lines.append("You are suffering dangerous cold exposure.")
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
    actor.register_consequence(TemperatureExposureConsequence())
    actor.register_gate(
        PolicyGate((pvp_classifier, lethal_pvp_classifier, pickpocket_classifier))
    )


__all__ = [
    "ArmorComponent",
    "AttackHandler",
    "ChallengeHandler",
    "DefendHandler",
    "DefendingComponent",
    "ExposureChangedEvent",
    "ExposureDamageEvent",
    "FortificationComponent",
    "FortifyHandler",
    "FrostbiteStartedEvent",
    "HeatstrokeStartedEvent",
    "PickpocketHandler",
    "RaidHandler",
    "ShelterComponent",
    "SparHandler",
    "StaminaChangedEvent",
    "StaminaComponent",
    "StaminaRegenSystem",
    "TemperatureExposureComponent",
    "TemperatureExposureConsequence",
    "TemperatureResistanceComponent",
    "WeaponComponent",
    "barbariansim_fragments",
    "install_barbariansim",
    "lethal_pvp_classifier",
    "pickpocket_classifier",
    "pvp_classifier",
]
