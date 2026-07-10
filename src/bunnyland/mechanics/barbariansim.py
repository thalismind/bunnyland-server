"""Barbarian-sim combat, PvP, and roleplay mechanics (spec 21.4).

Combat writes only health/status state; existing downed/death consequences decide later
outcomes. PvP and lethal PvP are policy-gated before damage is applied.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from random import Random
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
    IdentityComponent,
    InjuryComponent,
    KeyComponent,
    PortableComponent,
    RoomComponent,
    SuspendedComponent,
    TemperatureComponent,
)
from ..core.ecs import (
    container_of,
    entity_name,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
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
from ..prompts import ComponentPromptContext
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

RAIDER_HEALTH = 8.0
RAIDER_DAMAGE = 4.0
OFFICER_HEALTH = 16.0
OFFICER_DAMAGE = 6.0
WARLORD_HEALTH = 28.0
WARLORD_DAMAGE = 9.0
RAIDER_COST = 1
OFFICER_COST = 3
WARLORD_COST = 5

_RAIDER_EPITHETS = (
    "ironjaw",
    "skullbrand",
    "the cruel",
    "redhand",
    "stormcaller",
    "blackmane",
)


@dataclass(frozen=True)
class BarbarianSimPolicyComponent(Component):
    raid_storyteller_incidents: bool = True


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        lines: list[str] = []
        if self.heat or self.cold:
            lines.append(f"Exposure: heat {self.heat:g}, cold {self.cold:g}.")
        if self.heat_danger:
            lines.append("You are suffering dangerous heat exposure.")
        if self.cold_danger:
            lines.append("You are suffering dangerous cold exposure.")
        return tuple(lines)


@dataclass(frozen=True)
class PoisonComponent(Component):
    severity: float = 0.0
    damage_per_hour: float = 1.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Poisoned: severity {self.severity:g}.",)


@dataclass(frozen=True)
class CorruptionComponent(Component):
    amount: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Corruption: {self.amount:g}.",)


@dataclass(frozen=True)
class StaminaComponent(Component):
    current: float = 10.0
    maximum: float = 10.0
    regen_per_hour: float = 4.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Stamina: {self.current:g}/{self.maximum:g}.",)


@dataclass(frozen=True)
class DurabilityComponent(Component):
    current: float
    maximum: float
    broken: bool = False


@dataclass(frozen=True)
class WeaponComponent(Component):
    damage: float = UNARMED_DAMAGE
    damage_type: str = "blunt"
    lethal_capable: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        durability = ""
        if ctx.entity.has_component(DurabilityComponent):
            item_durability = ctx.entity.get_component(DurabilityComponent)
            status = "broken" if item_durability.broken else "durability"
            durability = f", {status} {item_durability.current:g}/{item_durability.maximum:g}"
        return (
            f"Reachable weapon: {self.damage_type} ({self.damage} damage{durability}).",
        )


@dataclass(frozen=True)
class ArmorComponent(Component):
    rating: float = 0.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Your armor rating is {self.rating}.",)


@dataclass(frozen=True)
class DefendingComponent(Component):
    started_at_epoch: int
    reduction: float = DEFEND_REDUCTION

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return ("You are defending yourself.",)


@dataclass(frozen=True)
class FortificationComponent(Component):
    rating: float = 1.0
    durability: float = 10.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Reachable fortification: rating {self.rating}, durability {self.durability}.",)


@dataclass(frozen=True)
class BaseClaimComponent(Component):
    claimed_by: str
    clan: str = ""
    claimed_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        clan = f" for {self.clan}" if self.clan else ""
        return (f"Base claim on {entity_name(ctx.entity)}{clan}.",)


@dataclass(frozen=True)
class TrapComponent(Component):
    damage: float = 5.0
    armed: bool = True
    placed_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "armed" if self.armed else "disarmed"
        return (f"Trap {entity_name(ctx.entity)}: {state}, {self.damage:g} damage.",)


@dataclass(frozen=True)
class ThrallComponent(Component):
    """A subdued captive bound to a master as a worker (catalogue 4.5).

    One master per thrall, so the master is a singleton field; a master's several
    thralls are several entities each carrying this component (spec ECS modeling).
    """

    master_id: str
    task: str = "labor"
    loyalty: float = 0.0
    bound_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if (
            ctx.target is not None
            and self.master_id == str(ctx.target.id)
            and ctx.can_view_private_state
        ):
            return (f"Your thrall {entity_name(ctx.entity)} is set to {self.task}.",)
        if ctx.is_first_person:
            return (f"You are bound as a thrall (task: {self.task}).",)
        return ()


@dataclass(frozen=True)
class FollowerComponent(Component):
    """A willing companion who follows a master's orders (catalogue 4.5)."""

    master_id: str
    orders: str = "follow"
    since_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if (
            ctx.target is not None
            and self.master_id == str(ctx.target.id)
            and ctx.can_view_private_state
        ):
            return (f"Your follower {entity_name(ctx.entity)} is ordered to {self.orders}.",)
        if ctx.is_first_person:
            return (f"You follow a leader (orders: {self.orders}).",)
        return ()


@dataclass(frozen=True)
class SurvivalGapComponent(Component):
    gap_type: str = "water"
    severity: float = 1.0
    required_resource: str = ""
    bridged_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        state = "bridged" if self.bridged_by else "open"
        return (f"Survival gap: {self.gap_type} severity {self.severity:g} ({state}).",)


@dataclass(frozen=True)
class BuildingComponent(Component):
    level: int = 1
    integrity: float = 10.0
    maximum_integrity: float = 10.0
    demolished: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "demolished" if self.demolished else "standing"
        return (
            f"Building {entity_name(ctx.entity)}: level {self.level}, "
            f"integrity {self.integrity:g}/{self.maximum_integrity:g}, {state}.",
        )


@dataclass(frozen=True)
class SiegeReadinessComponent(Component):
    score: float = 0.0
    prepared_by: str | None = None
    prepared_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Siege readiness at {entity_name(ctx.entity)}: {self.score:g}.",)


@dataclass(frozen=True)
class PurgeWaveComponent(Component):
    wave: int = 0
    intensity: float = 1.0
    active: bool = False
    started_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "active" if self.active else "quiet"
        return (f"Purge wave at {entity_name(ctx.entity)}: wave {self.wave}, {state}.",)


@dataclass(frozen=True)
class ShrineComponent(Component):
    deity: str = "the wild"
    attunement: float = 0.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Shrine nearby: {self.deity} attunement {self.attunement:g}.",)


@dataclass(frozen=True)
class RitualComponent(Component):
    ritual_type: str = "blessing"
    blessing: str = ""
    curse: str = ""
    corruption_cost: float = 0.0
    performed_by: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Ritual nearby: {self.ritual_type}.",)


@dataclass(frozen=True)
class BlessingComponent(Component):
    name: str
    source_id: str = ""
    expires_at_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Blessing: {self.name}.",)


@dataclass(frozen=True)
class CurseComponent(Component):
    name: str
    source_id: str = ""
    severity: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Curse: {self.name} severity {self.severity:g}.",)


@dataclass(frozen=True)
class DangerZoneComponent(Component):
    zone_type: str = "ruin"
    danger_rating: float = 1.0
    explored_by: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Danger zone: {self.zone_type} rating {self.danger_rating:g}.",)


@dataclass(frozen=True)
class BossComponent(Component):
    name: str = "world boss"
    defeated: bool = False
    defeated_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        state = "defeated" if self.defeated else "undefeated"
        return (f"Boss nearby: {self.name} ({state}).",)


@dataclass(frozen=True)
class TreasureComponent(Component):
    treasure_type: str = "cache"
    locked: bool = True
    key_name: str = ""
    claimed_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        state = "locked" if self.locked else "unlocked"
        return (f"Treasure nearby: {self.treasure_type} ({state}).",)


@dataclass(frozen=True)
class ClimbingSkillComponent(Component):
    level: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Climbing skill: {self.level}.",)


@dataclass(frozen=True)
class ClimbingGateComponent(Component):
    required_level: int = 1
    opened_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Climbing gate nearby: requires level {self.required_level}.",)


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


class CharacterPoisonedEvent(DomainEvent):
    character_id: str
    severity: float


class PoisonProgressedEvent(DomainEvent):
    character_id: str
    severity: float
    damage: float
    health: float


class PoisonTreatedEvent(DomainEvent):
    character_id: str


class CorruptionGainedEvent(DomainEvent):
    character_id: str
    amount: float


class CorruptionCleansedEvent(DomainEvent):
    character_id: str


class ItemDamagedEvent(DomainEvent):
    item_id: str
    durability: float
    maximum: float


class ItemBrokenEvent(DomainEvent):
    item_id: str


class ItemRepairedEvent(DomainEvent):
    item_id: str
    durability: float
    maximum: float


class BaseClaimedEvent(DomainEvent):
    base_id: str
    clan: str = ""


class TrapPlacedEvent(DomainEvent):
    trap_id: str
    damage: float


class TrapDisarmedEvent(DomainEvent):
    trap_id: str


class ThrallTakenEvent(DomainEvent):
    master_id: str
    thrall_id: str
    task: str


class FollowerRecruitedEvent(DomainEvent):
    master_id: str
    follower_id: str


class FollowerOrderChangedEvent(DomainEvent):
    master_id: str
    subordinate_id: str
    orders: str


class ThrallReleasedEvent(DomainEvent):
    master_id: str
    subordinate_id: str


class SurvivalGapBridgedEvent(DomainEvent):
    gap_id: str
    gap_type: str


class BuildingDecayedEvent(DomainEvent):
    building_id: str
    integrity: float
    maximum_integrity: float


class BuildingUpgradedEvent(DomainEvent):
    building_id: str
    level: int
    integrity: float


class BuildingDemolishedEvent(DomainEvent):
    building_id: str


class SiegePreparedEvent(DomainEvent):
    base_id: str
    score: float


class PurgeWaveStartedEvent(DomainEvent):
    base_id: str
    wave: int
    intensity: float


class RitualPerformedEvent(DomainEvent):
    shrine_id: str
    ritual_id: str
    ritual_type: str


class BlessingReceivedEvent(DomainEvent):
    blessing: str


class CurseReceivedEvent(DomainEvent):
    curse: str


class DangerZoneExploredEvent(DomainEvent):
    zone_id: str
    zone_type: str
    danger_rating: float


class BossDefeatedEvent(DomainEvent):
    boss_id: str
    boss_name: str


class TreasureUnlockedEvent(DomainEvent):
    treasure_id: str
    key_name: str


class TreasureClaimedEvent(DomainEvent):
    treasure_id: str
    treasure_type: str


class ClimbingGatePassedEvent(DomainEvent):
    gate_id: str
    required_level: int


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
    if (
        weapon.has_component(DurabilityComponent)
        and weapon.get_component(DurabilityComponent).broken
    ):
        return -1.0
    return weapon.get_component(WeaponComponent).damage


def _armor_rating(ctx: HandlerContext, target_id: EntityId) -> float:
    target = ctx.entity(target_id)
    rating = (
        target.get_component(ArmorComponent).rating if target.has_component(ArmorComponent) else 0.0
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


def _damage_item(
    ctx: HandlerContext,
    item_id: EntityId | None,
    *,
    amount: float,
    actor_id: EntityId,
) -> list[DomainEvent]:
    if item_id is None or amount <= 0:
        return []
    item = ctx.entity(item_id)
    if not item.has_component(DurabilityComponent):
        return []
    durability = item.get_component(DurabilityComponent)
    if durability.broken:
        return []
    current = max(0.0, durability.current - amount)
    broken = current <= 0
    updated = DurabilityComponent(
        current=current,
        maximum=durability.maximum,
        broken=broken,
    )
    replace_component(item, updated)
    events: list[DomainEvent] = [
        ItemDamagedEvent(
            **ctx.event_base(
                visibility=EventVisibility.PRIVATE,
                actor_id=str(actor_id),
                target_ids=(str(item_id),),
                item_id=str(item_id),
                durability=current,
                maximum=durability.maximum,
            )
        )
    ]
    if broken:
        events.append(
            ItemBrokenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                )
            )
        )
    return events


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


class PoisonConsequence:
    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = (
            world.query()
            .with_all([CharacterComponent, PoisonComponent, HealthComponent])
            .with_none([DeadComponent, SuspendedComponent])
        )
        for character in query.execute_entities():
            poison = character.get_component(PoisonComponent)
            elapsed = max(0, epoch - poison.last_updated_epoch)
            if elapsed <= 0:
                continue
            hours = elapsed / 3600.0
            damage = poison.severity * poison.damage_per_hour * hours
            health = character.get_component(HealthComponent)
            updated_health = replace(health, current=health.current - damage)
            replace_component(character, updated_health)
            replace_component(character, replace(poison, last_updated_epoch=epoch))
            events.append(
                PoisonProgressedEvent(
                    **_barbarian_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character.id),
                        character_id=str(character.id),
                        severity=poison.severity,
                        damage=damage,
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
    events.extend(
        _damage_item(
            ctx,
            weapon_id,
            amount=float(command.payload.get("durability_cost", 1.0)),
            actor_id=actor_id,
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


class ClaimBaseHandler:
    command_type = "claim-base"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("base_id"))
        if actor_id is None:
            return rejected("invalid character id")
        character = ctx.entity(actor_id)
        if target_id is None:
            target_id = container_of(character)
        if target_id is None or not ctx.world.has_entity(target_id):
            return rejected("base does not exist")
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("base is not reachable")
        base = ctx.entity(target_id)
        if base.has_component(BaseClaimComponent):
            return rejected("base is already claimed")
        clan = str(command.payload.get("clan", "")).strip()
        base.add_component(
            BaseClaimComponent(
                claimed_by=str(actor_id),
                clan=clan,
                claimed_at_epoch=ctx.epoch,
            )
        )
        return ok(
            BaseClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(target_id),),
                    base_id=str(target_id),
                    clan=clan,
                )
            )
        )


class PlaceTrapHandler:
    command_type = "place-trap"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        room_id = container_of(ctx.entity(actor_id))
        if room_id is None:
            return rejected("no room to place trap")
        damage = float(command.payload.get("damage", 5.0))
        if damage <= 0:
            return rejected("trap damage must be positive")
        trap = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name="armed trap", kind="trap"),
                TrapComponent(damage=damage, armed=True, placed_by=str(actor_id)),
            ],
        )
        ctx.entity(room_id).add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), trap.id)
        return ok(
            TrapPlacedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(room_id),
                    target_ids=(str(trap.id),),
                    trap_id=str(trap.id),
                    damage=damage,
                )
            )
        )


class DisarmTrapHandler:
    command_type = "disarm-trap"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        trap_id = parse_entity_id(command.payload.get("trap_id"))
        if actor_id is None or trap_id is None:
            return rejected("invalid character or trap id")
        if not ctx.world.has_entity(trap_id):
            return rejected("trap does not exist")
        character = ctx.entity(actor_id)
        if trap_id not in reachable_ids(ctx.world, character):
            return rejected("trap is not reachable")
        trap = ctx.entity(trap_id)
        if not trap.has_component(TrapComponent):
            return rejected("target is not a trap")
        component = trap.get_component(TrapComponent)
        if not component.armed:
            return rejected("trap is already disarmed")
        replace_component(trap, replace(component, armed=False))
        return ok(
            TrapDisarmedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(trap_id),),
                    trap_id=str(trap_id),
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


class BridgeSurvivalGapHandler:
    command_type = "bridge-survival-gap"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        gap_id = parse_entity_id(command.payload.get("gap_id"))
        if actor_id is None or gap_id is None:
            return rejected("invalid character or gap id")
        if not ctx.world.has_entity(gap_id):
            return rejected("survival gap does not exist")
        character = ctx.entity(actor_id)
        if gap_id not in reachable_ids(ctx.world, character):
            return rejected("survival gap is not reachable")
        gap_entity = ctx.entity(gap_id)
        if not gap_entity.has_component(SurvivalGapComponent):
            return rejected("target is not a survival gap")
        gap = gap_entity.get_component(SurvivalGapComponent)
        if gap.bridged_by is not None:
            return rejected("survival gap is already bridged")
        replace_component(gap_entity, replace(gap, bridged_by=str(actor_id)))
        return ok(
            SurvivalGapBridgedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(gap_id),),
                    gap_id=str(gap_id),
                    gap_type=gap.gap_type,
                )
            )
        )


class DecayBuildingHandler:
    command_type = "decay-building"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        building_id = parse_entity_id(command.payload.get("building_id"))
        if actor_id is None or building_id is None:
            return rejected("invalid character or building id")
        if not ctx.world.has_entity(building_id):
            return rejected("building does not exist")
        character = ctx.entity(actor_id)
        if building_id not in reachable_ids(ctx.world, character):
            return rejected("building is not reachable")
        building_entity = ctx.entity(building_id)
        if not building_entity.has_component(BuildingComponent):
            return rejected("target is not a building")
        building = building_entity.get_component(BuildingComponent)
        if building.demolished:
            return rejected("building is demolished")
        amount = float(command.payload.get("amount", 1.0))
        if amount <= 0:
            return rejected("decay amount must be positive")
        updated = replace(building, integrity=max(0.0, building.integrity - amount))
        replace_component(building_entity, updated)
        return ok(
            BuildingDecayedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(building_id),),
                    building_id=str(building_id),
                    integrity=updated.integrity,
                    maximum_integrity=updated.maximum_integrity,
                )
            )
        )


class UpgradeBuildingHandler:
    command_type = "upgrade-building"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        building_id = parse_entity_id(command.payload.get("building_id"))
        if actor_id is None or building_id is None:
            return rejected("invalid character or building id")
        if not ctx.world.has_entity(building_id):
            return rejected("building does not exist")
        character = ctx.entity(actor_id)
        if building_id not in reachable_ids(ctx.world, character):
            return rejected("building is not reachable")
        building_entity = ctx.entity(building_id)
        if not building_entity.has_component(BuildingComponent):
            return rejected("target is not a building")
        building = building_entity.get_component(BuildingComponent)
        if building.demolished:
            return rejected("building is demolished")
        added_integrity = float(command.payload.get("integrity", 5.0))
        if added_integrity <= 0:
            return rejected("upgrade integrity must be positive")
        maximum = building.maximum_integrity + added_integrity
        updated = replace(
            building,
            level=building.level + 1,
            maximum_integrity=maximum,
            integrity=maximum,
        )
        replace_component(building_entity, updated)
        return ok(
            BuildingUpgradedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(building_id),),
                    building_id=str(building_id),
                    level=updated.level,
                    integrity=updated.integrity,
                )
            )
        )


class DemolishBuildingHandler:
    command_type = "demolish-building"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        building_id = parse_entity_id(command.payload.get("building_id"))
        if actor_id is None or building_id is None:
            return rejected("invalid character or building id")
        if not ctx.world.has_entity(building_id):
            return rejected("building does not exist")
        character = ctx.entity(actor_id)
        if building_id not in reachable_ids(ctx.world, character):
            return rejected("building is not reachable")
        building_entity = ctx.entity(building_id)
        if not building_entity.has_component(BuildingComponent):
            return rejected("target is not a building")
        building = building_entity.get_component(BuildingComponent)
        if building.demolished:
            return rejected("building is already demolished")
        replace_component(building_entity, replace(building, integrity=0.0, demolished=True))
        return ok(
            BuildingDemolishedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(building_id),),
                    building_id=str(building_id),
                )
            )
        )


class PrepareSiegeHandler:
    command_type = "prepare-siege"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        base_id = parse_entity_id(command.payload.get("base_id"))
        if actor_id is None:
            return rejected("invalid character id")
        character = ctx.entity(actor_id)
        if base_id is None:
            base_id = container_of(character)
        if base_id is None or not ctx.world.has_entity(base_id):
            return rejected("base does not exist")
        if base_id not in reachable_ids(ctx.world, character):
            return rejected("base is not reachable")
        base = ctx.entity(base_id)
        score = float(command.payload.get("score", 1.0))
        if score <= 0:
            return rejected("siege score must be positive")
        current = (
            base.get_component(SiegeReadinessComponent)
            if base.has_component(SiegeReadinessComponent)
            else SiegeReadinessComponent()
        )
        updated = replace(
            current,
            score=current.score + score,
            prepared_by=str(actor_id),
            prepared_at_epoch=ctx.epoch,
        )
        replace_component(base, updated)
        return ok(
            SiegePreparedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(base_id),),
                    base_id=str(base_id),
                    score=updated.score,
                )
            )
        )


class StartPurgeWaveHandler:
    command_type = "start-purge-wave"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        base_id = parse_entity_id(command.payload.get("base_id"))
        if actor_id is None:
            return rejected("invalid character id")
        character = ctx.entity(actor_id)
        if base_id is None:
            base_id = container_of(character)
        if base_id is None or not ctx.world.has_entity(base_id):
            return rejected("base does not exist")
        if base_id not in reachable_ids(ctx.world, character):
            return rejected("base is not reachable")
        base = ctx.entity(base_id)
        current = (
            base.get_component(PurgeWaveComponent)
            if base.has_component(PurgeWaveComponent)
            else PurgeWaveComponent()
        )
        intensity = float(command.payload.get("intensity", current.intensity))
        if intensity <= 0:
            return rejected("purge intensity must be positive")
        updated = replace(
            current,
            wave=current.wave + 1,
            intensity=intensity,
            active=True,
            started_at_epoch=ctx.epoch,
        )
        replace_component(base, updated)
        return ok(
            PurgeWaveStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(base_id),),
                    base_id=str(base_id),
                    wave=updated.wave,
                    intensity=updated.intensity,
                )
            )
        )


class PerformRitualHandler:
    command_type = "perform-ritual"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        shrine_id = parse_entity_id(command.payload.get("shrine_id"))
        ritual_id = parse_entity_id(command.payload.get("ritual_id"))
        if actor_id is None or shrine_id is None or ritual_id is None:
            return rejected("invalid character, shrine, or ritual id")
        if not ctx.world.has_entity(shrine_id) or not ctx.world.has_entity(ritual_id):
            return rejected("shrine or ritual does not exist")
        character = ctx.entity(actor_id)
        reachable = reachable_ids(ctx.world, character)
        if shrine_id not in reachable or ritual_id not in reachable:
            return rejected("shrine or ritual is not reachable")
        shrine = ctx.entity(shrine_id)
        ritual_entity = ctx.entity(ritual_id)
        if not shrine.has_component(ShrineComponent):
            return rejected("target is not a shrine")
        if not ritual_entity.has_component(RitualComponent):
            return rejected("target is not a ritual")
        ritual = ritual_entity.get_component(RitualComponent)
        if str(actor_id) in ritual.performed_by:
            return rejected("ritual already performed")

        replace_component(
            ritual_entity,
            replace(ritual, performed_by=tuple(sorted((*ritual.performed_by, str(actor_id))))),
        )
        if ritual.corruption_cost > 0:
            current = (
                character.get_component(CorruptionComponent)
                if character.has_component(CorruptionComponent)
                else CorruptionComponent()
            )
            replace_component(
                character,
                replace(
                    current,
                    amount=current.amount + ritual.corruption_cost,
                    last_updated_epoch=ctx.epoch,
                ),
            )
        events: list[DomainEvent] = [
            RitualPerformedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(shrine_id), str(ritual_id)),
                    shrine_id=str(shrine_id),
                    ritual_id=str(ritual_id),
                    ritual_type=ritual.ritual_type,
                )
            )
        ]
        if ritual.blessing:
            character.add_component(
                BlessingComponent(name=ritual.blessing, source_id=str(ritual_id))
            )
            events.append(
                BlessingReceivedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(actor_id),
                        room_id=str(container_of(character)) if container_of(character) else None,
                        target_ids=(str(ritual_id),),
                        blessing=ritual.blessing,
                    )
                )
            )
        if ritual.curse:
            character.add_component(CurseComponent(name=ritual.curse, source_id=str(ritual_id)))
            events.append(
                CurseReceivedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(actor_id),
                        room_id=str(container_of(character)) if container_of(character) else None,
                        target_ids=(str(ritual_id),),
                        curse=ritual.curse,
                    )
                )
            )
        return ok(*events)


class ExploreDangerZoneHandler:
    command_type = "explore-danger-zone"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        zone_id = parse_entity_id(command.payload.get("zone_id"))
        if actor_id is None or zone_id is None:
            return rejected("invalid character or zone id")
        if not ctx.world.has_entity(zone_id):
            return rejected("danger zone does not exist")
        character = ctx.entity(actor_id)
        if zone_id not in reachable_ids(ctx.world, character):
            return rejected("danger zone is not reachable")
        zone_entity = ctx.entity(zone_id)
        if not zone_entity.has_component(DangerZoneComponent):
            return rejected("target is not a danger zone")
        zone = zone_entity.get_component(DangerZoneComponent)
        if str(actor_id) not in zone.explored_by:
            replace_component(
                zone_entity,
                replace(zone, explored_by=tuple(sorted((*zone.explored_by, str(actor_id))))),
            )
        return ok(
            DangerZoneExploredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(zone_id),),
                    zone_id=str(zone_id),
                    zone_type=zone.zone_type,
                    danger_rating=zone.danger_rating,
                )
            )
        )


class DefeatBossHandler:
    command_type = "defeat-boss"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        boss_id = parse_entity_id(command.payload.get("boss_id"))
        if actor_id is None or boss_id is None:
            return rejected("invalid character or boss id")
        if not ctx.world.has_entity(boss_id):
            return rejected("boss does not exist")
        character = ctx.entity(actor_id)
        if boss_id not in reachable_ids(ctx.world, character):
            return rejected("boss is not reachable")
        boss_entity = ctx.entity(boss_id)
        if not boss_entity.has_component(BossComponent):
            return rejected("target is not a boss")
        boss = boss_entity.get_component(BossComponent)
        if boss.defeated:
            return rejected("boss is already defeated")
        updated = replace(boss, defeated=True, defeated_by=str(actor_id))
        replace_component(boss_entity, updated)
        return ok(
            BossDefeatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(boss_id),),
                    boss_id=str(boss_id),
                    boss_name=updated.name,
                )
            )
        )


class UnlockTreasureHandler:
    command_type = "unlock-treasure"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        treasure_id = parse_entity_id(command.payload.get("treasure_id"))
        key_id = parse_entity_id(command.payload.get("key_id"))
        if actor_id is None or treasure_id is None:
            return rejected("invalid character or treasure id")
        if not ctx.world.has_entity(treasure_id):
            return rejected("treasure does not exist")
        character = ctx.entity(actor_id)
        if treasure_id not in reachable_ids(ctx.world, character):
            return rejected("treasure is not reachable")
        treasure_entity = ctx.entity(treasure_id)
        if not treasure_entity.has_component(TreasureComponent):
            return rejected("target is not treasure")
        treasure = treasure_entity.get_component(TreasureComponent)
        if not treasure.locked:
            return rejected("treasure is already unlocked")
        if treasure.key_name:
            if (
                key_id is None
                or not ctx.world.has_entity(key_id)
                or container_of(ctx.world.get_entity(key_id)) != actor_id
            ):
                return rejected("required key is not carried")
            key = ctx.entity(key_id)
            if (
                not key.has_component(KeyComponent)
                or key.get_component(KeyComponent).key_name != treasure.key_name
            ):
                return rejected("wrong key")
        updated = replace(treasure, locked=False)
        replace_component(treasure_entity, updated)
        return ok(
            TreasureUnlockedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(treasure_id),),
                    treasure_id=str(treasure_id),
                    key_name=treasure.key_name,
                )
            )
        )


class ClaimTreasureHandler:
    command_type = "claim-treasure"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        treasure_id = parse_entity_id(command.payload.get("treasure_id"))
        if actor_id is None or treasure_id is None:
            return rejected("invalid character or treasure id")
        if not ctx.world.has_entity(treasure_id):
            return rejected("treasure does not exist")
        character = ctx.entity(actor_id)
        if treasure_id not in reachable_ids(ctx.world, character):
            return rejected("treasure is not reachable")
        treasure_entity = ctx.entity(treasure_id)
        if not treasure_entity.has_component(TreasureComponent):
            return rejected("target is not treasure")
        treasure = treasure_entity.get_component(TreasureComponent)
        if treasure.locked:
            return rejected("treasure is locked")
        if treasure.claimed_by is not None:
            return rejected("treasure is already claimed")
        updated = replace(treasure, claimed_by=str(actor_id))
        replace_component(treasure_entity, updated)
        return ok(
            TreasureClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(treasure_id),),
                    treasure_id=str(treasure_id),
                    treasure_type=treasure.treasure_type,
                )
            )
        )


class ClimbHandler:
    command_type = "climb"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        gate_id = parse_entity_id(command.payload.get("gate_id"))
        if actor_id is None or gate_id is None:
            return rejected("invalid character or climbing gate id")
        if not ctx.world.has_entity(gate_id):
            return rejected("climbing gate does not exist")
        character = ctx.entity(actor_id)
        if gate_id not in reachable_ids(ctx.world, character):
            return rejected("climbing gate is not reachable")
        gate_entity = ctx.entity(gate_id)
        if not gate_entity.has_component(ClimbingGateComponent):
            return rejected("target is not a climbing gate")
        gate = gate_entity.get_component(ClimbingGateComponent)
        level = (
            character.get_component(ClimbingSkillComponent).level
            if character.has_component(ClimbingSkillComponent)
            else 0
        )
        if level < gate.required_level:
            return rejected("climbing skill is too low")
        replace_component(gate_entity, replace(gate, opened_by=str(actor_id)))
        return ok(
            ClimbingGatePassedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(gate_id),),
                    gate_id=str(gate_id),
                    required_level=gate.required_level,
                )
            )
        )


class RepairItemHandler:
    command_type = "repair-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        if actor_id is None or item_id is None:
            return rejected("invalid character or item id")
        if not ctx.world.has_entity(item_id):
            return rejected("item does not exist")
        actor = ctx.entity(actor_id)
        if item_id not in reachable_ids(ctx.world, actor):
            return rejected("item is not reachable")
        item = ctx.entity(item_id)
        if not item.has_component(DurabilityComponent):
            return rejected("item has no durability")
        durability = item.get_component(DurabilityComponent)
        amount = float(command.payload.get("amount", durability.maximum))
        if amount <= 0:
            return rejected("repair amount must be positive")
        current = min(durability.maximum, durability.current + amount)
        updated = DurabilityComponent(
            current=current,
            maximum=durability.maximum,
            broken=current <= 0,
        )
        replace_component(item, updated)
        return ok(
            ItemRepairedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                    durability=current,
                    maximum=durability.maximum,
                )
            )
        )


class PoisonCharacterHandler:
    command_type = "poison-character"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid actor or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")
        severity = float(command.payload.get("severity", 1.0))
        if severity <= 0:
            return rejected("poison severity must be positive")
        target = ctx.entity(target_id)
        replace_component(
            target,
            PoisonComponent(
                severity=severity,
                damage_per_hour=float(command.payload.get("damage_per_hour", 1.0)),
                last_updated_epoch=ctx.epoch,
            ),
        )
        return ok(
            CharacterPoisonedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(actor_id),
                    target_ids=(str(target_id),),
                    character_id=str(target_id),
                    severity=severity,
                )
            )
        )


class TreatPoisonHandler:
    command_type = "treat-poison"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id", command.character_id))
        if actor_id is None or target_id is None:
            return rejected("invalid actor or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")
        target = ctx.entity(target_id)
        if not target.has_component(PoisonComponent):
            return rejected("target is not poisoned")
        target.remove_component(PoisonComponent)
        return ok(
            PoisonTreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(actor_id),
                    target_ids=(str(target_id),),
                    character_id=str(target_id),
                )
            )
        )


class GainCorruptionHandler:
    command_type = "gain-corruption"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        amount = float(command.payload.get("amount", 1.0))
        if amount <= 0:
            return rejected("corruption amount must be positive")
        actor = ctx.entity(actor_id)
        current = (
            actor.get_component(CorruptionComponent)
            if actor.has_component(CorruptionComponent)
            else CorruptionComponent()
        )
        updated = CorruptionComponent(
            amount=current.amount + amount,
            last_updated_epoch=ctx.epoch,
        )
        replace_component(actor, updated)
        return ok(
            CorruptionGainedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    character_id=str(actor_id),
                    amount=updated.amount,
                )
            )
        )


class CleanseCorruptionHandler:
    command_type = "cleanse-corruption"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if not actor.has_component(CorruptionComponent):
            return rejected("character is not corrupted")
        actor.remove_component(CorruptionComponent)
        return ok(
            CorruptionCleansedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    character_id=str(actor_id),
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
        if (
            not item.has_component(PortableComponent)
            or not item.get_component(PortableComponent).can_pick_up
        ):
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


def _master_of(entity) -> str | None:
    """Return the master id recorded on a thrall/follower, or None."""
    if entity.has_component(ThrallComponent):
        return entity.get_component(ThrallComponent).master_id
    if entity.has_component(FollowerComponent):
        return entity.get_component(FollowerComponent).master_id
    return None


class SubdueHandler:
    command_type = "subdue"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid captor or target id")
        if actor_id == target_id:
            return rejected("cannot subdue yourself")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        target = ctx.entity(target_id)
        if not target.has_component(CharacterComponent):
            return rejected("target cannot be bound")
        if target.has_component(DeadComponent):
            return rejected("target is dead")
        if not target.has_component(DownedComponent):
            return rejected("target must be defeated first")
        if target.has_component(ThrallComponent) or target.has_component(FollowerComponent):
            return rejected("target already serves a master")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")

        task = str(command.payload.get("task", "labor")).strip() or "labor"
        target.add_component(
            ThrallComponent(master_id=str(actor_id), task=task, bound_at_epoch=ctx.epoch)
        )
        return ok(
            ThrallTakenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(ctx.entity(actor_id))),
                    target_ids=(str(target_id),),
                    master_id=str(actor_id),
                    thrall_id=str(target_id),
                    task=task,
                )
            )
        )


class RecruitFollowerHandler:
    command_type = "recruit-follower"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid leader or target id")
        if actor_id == target_id:
            return rejected("cannot recruit yourself")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        target = ctx.entity(target_id)
        if not target.has_component(CharacterComponent):
            return rejected("target cannot be recruited")
        if target.has_component(DeadComponent) or target.has_component(DownedComponent):
            return rejected("target cannot be recruited in this state")
        if target.has_component(ThrallComponent) or target.has_component(FollowerComponent):
            return rejected("target already serves a master")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")

        target.add_component(FollowerComponent(master_id=str(actor_id), since_epoch=ctx.epoch))
        return ok(
            FollowerRecruitedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(ctx.entity(actor_id))),
                    target_ids=(str(target_id),),
                    master_id=str(actor_id),
                    follower_id=str(target_id),
                )
            )
        )


class CommandFollowerHandler:
    command_type = "command-follower"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        orders = str(command.payload.get("orders", "")).strip()
        if actor_id is None or target_id is None:
            return rejected("invalid master or subordinate id")
        if not orders:
            return rejected("orders must not be empty")
        if not ctx.world.has_entity(target_id):
            return rejected("subordinate does not exist")
        target = ctx.entity(target_id)
        if _master_of(target) != str(actor_id):
            return rejected("you do not command this character")

        if target.has_component(FollowerComponent):
            replace_component(
                target, replace(target.get_component(FollowerComponent), orders=orders)
            )
        else:
            replace_component(target, replace(target.get_component(ThrallComponent), task=orders))
        return ok(
            FollowerOrderChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(target_id),),
                    master_id=str(actor_id),
                    subordinate_id=str(target_id),
                    orders=orders,
                )
            )
        )


class ReleaseThrallHandler:
    command_type = "release-thrall"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid master or subordinate id")
        if not ctx.world.has_entity(target_id):
            return rejected("subordinate does not exist")
        target = ctx.entity(target_id)
        if _master_of(target) != str(actor_id):
            return rejected("you do not command this character")

        if target.has_component(ThrallComponent):
            target.remove_component(ThrallComponent)
        else:
            target.remove_component(FollowerComponent)
        return ok(
            ThrallReleasedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    target_ids=(str(target_id),),
                    master_id=str(actor_id),
                    subordinate_id=str(target_id),
                )
            )
        )


@dataclass(frozen=True)
class RaiderSpawnSpec:
    name: str
    rank: str
    health: float
    damage: float
    armor: float = 0.0
    lethal_capable: bool = False


def _raid_rank_profile(rank: str) -> tuple[float, float, float, bool]:
    if rank == "warlord":
        return WARLORD_HEALTH, WARLORD_DAMAGE, 4.0, True
    if rank == "officer":
        return OFFICER_HEALTH, OFFICER_DAMAGE, 2.0, True
    return RAIDER_HEALTH, RAIDER_DAMAGE, 0.0, False


def generate_raid_spawn_specs(
    attack_budget: int | float, seed: str = ""
) -> tuple[RaiderSpawnSpec, ...]:
    """Split an attack budget into a swarm of weak raiders and a few leaders."""

    total = max(1, int(round(attack_budget)))
    warlords = 1 if total >= WARLORD_COST + OFFICER_COST else 0
    remaining = total - warlords * WARLORD_COST
    officers = min(3, max(1, remaining // 6)) if remaining >= OFFICER_COST else 0
    remaining -= officers * OFFICER_COST
    raiders = max(1, remaining // RAIDER_COST)
    rng = Random(seed)
    epithets = list(_RAIDER_EPITHETS)
    rng.shuffle(epithets)

    def _spec(name: str, rank: str) -> RaiderSpawnSpec:
        health, damage, armor, lethal = _raid_rank_profile(rank)
        return RaiderSpawnSpec(
            name=name,
            rank=rank,
            health=health,
            damage=damage,
            armor=armor,
            lethal_capable=lethal,
        )

    specs = [_spec(f"raider {index + 1}", "raider") for index in range(raiders)]
    for index in range(officers):
        specs.append(_spec(f"raid officer {epithets[index % len(epithets)]}", "officer"))
    for index in range(warlords):
        epithet = epithets[(officers + index) % len(epithets)]
        specs.append(_spec(f"raid warlord {epithet}", "warlord"))
    return tuple(specs)


class BarbarianRaidEnrichment:
    """Barbarian-sim incident enrichment for generated storyteller raid swarms."""

    def __init__(self, world: World):
        self.world = world

    def subscribe(self, bus) -> None:
        from .storyteller import IncidentGeneratedEvent

        bus.subscribe(IncidentGeneratedEvent, self._on_incident)

    def _on_incident(self, event) -> None:
        if event.kind != "barbarian_raid" and "raid-swarm" not in event.wants:
            return
        from .storyteller import IncidentSpawned

        incident_id = parse_entity_id(event.incident_id)
        room_id = parse_entity_id(event.room_id)
        if (
            incident_id is None
            or room_id is None
            or not self.world.has_entity(incident_id)
            or not self.world.has_entity(room_id)
        ):
            return
        incident = self.world.get_entity(incident_id)
        if incident.get_relationships(IncidentSpawned):
            return
        room = self.world.get_entity(room_id)
        for spec in generate_raid_spawn_specs(event.budget_spent, event.seed):
            components = [
                IdentityComponent(
                    name=spec.name,
                    kind="character",
                    tags=("barbariansim", "raider", spec.rank),
                ),
                CharacterComponent(species="raider"),
                HealthComponent(current=spec.health, maximum=spec.health),
                WeaponComponent(
                    damage=spec.damage,
                    damage_type="blade",
                    lethal_capable=spec.lethal_capable,
                ),
                StaminaComponent(),
            ]
            if spec.armor > 0:
                components.append(ArmorComponent(rating=spec.armor))
            raider = spawn_entity(self.world, components)
            room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), raider.id)
            incident.add_relationship(IncidentSpawned(kind="monster"), raider.id)


def ensure_barbariansim_policy(actor) -> BarbarianSimPolicyComponent:
    for entity in actor.world.query().with_all([BarbarianSimPolicyComponent]).execute_entities():
        return entity.get_component(BarbarianSimPolicyComponent)
    entity = spawn_entity(actor.world, [BarbarianSimPolicyComponent()])
    return entity.get_component(BarbarianSimPolicyComponent)


def barbariansim_fragments(world: World, character) -> list[str]:
    lines: list[str] = []
    ctx = ComponentPromptContext.for_entity(world, character)
    for component_type in (
        StaminaComponent,
        TemperatureExposureComponent,
        PoisonComponent,
        CorruptionComponent,
        DefendingComponent,
        ArmorComponent,
        ThrallComponent,
        FollowerComponent,
        BlessingComponent,
        CurseComponent,
        ClimbingSkillComponent,
    ):
        if character.has_component(component_type):
            lines.extend(character.get_component(component_type).prompt_fragments(ctx))
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        entity_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, room=ctx.room, target=character
        )
        if _master_of(entity) == str(character.id):
            for component_type in (ThrallComponent, FollowerComponent):
                if entity.has_component(component_type):
                    lines.extend(entity.get_component(component_type).prompt_fragments(entity_ctx))
        for component_type in (
            WeaponComponent,
            FortificationComponent,
            BaseClaimComponent,
            TrapComponent,
            SurvivalGapComponent,
            BuildingComponent,
            SiegeReadinessComponent,
            PurgeWaveComponent,
            ShrineComponent,
            RitualComponent,
            DangerZoneComponent,
            BossComponent,
            TreasureComponent,
            KeyComponent,
            ClimbingGateComponent,
        ):
            if entity.has_component(component_type):
                lines.extend(
                    entity.get_component(component_type).prompt_fragments(entity_ctx)
                )
    return sorted(lines)


def install_barbariansim(actor) -> None:
    actor.world.register_system(StaminaRegenSystem())
    actor.register_consequence(TemperatureExposureConsequence())
    actor.register_consequence(PoisonConsequence())
    actor.register_gate(PolicyGate((pvp_classifier, lethal_pvp_classifier, pickpocket_classifier)))
    ensure_barbariansim_policy(actor)
    BarbarianRaidEnrichment(actor.world).subscribe(actor.bus)


__all__ = [
    "ArmorComponent",
    "AttackHandler",
    "BarbarianRaidEnrichment",
    "BarbarianSimPolicyComponent",
    "BaseClaimComponent",
    "BaseClaimedEvent",
    "BlessingComponent",
    "BlessingReceivedEvent",
    "BossComponent",
    "BossDefeatedEvent",
    "BridgeSurvivalGapHandler",
    "BuildingComponent",
    "BuildingDecayedEvent",
    "BuildingDemolishedEvent",
    "BuildingUpgradedEvent",
    "CharacterPoisonedEvent",
    "ChallengeHandler",
    "ClaimBaseHandler",
    "ClaimTreasureHandler",
    "CleanseCorruptionHandler",
    "ClimbHandler",
    "ClimbingGateComponent",
    "ClimbingGatePassedEvent",
    "ClimbingSkillComponent",
    "CorruptionCleansedEvent",
    "CorruptionComponent",
    "CorruptionGainedEvent",
    "CurseComponent",
    "CurseReceivedEvent",
    "DangerZoneComponent",
    "DangerZoneExploredEvent",
    "DecayBuildingHandler",
    "DefendHandler",
    "DefendingComponent",
    "DefeatBossHandler",
    "DemolishBuildingHandler",
    "CommandFollowerHandler",
    "DisarmTrapHandler",
    "DurabilityComponent",
    "ExploreDangerZoneHandler",
    "ExposureChangedEvent",
    "ExposureDamageEvent",
    "FollowerComponent",
    "FollowerOrderChangedEvent",
    "FollowerRecruitedEvent",
    "FortificationComponent",
    "FortifyHandler",
    "FrostbiteStartedEvent",
    "HeatstrokeStartedEvent",
    "ItemBrokenEvent",
    "ItemDamagedEvent",
    "ItemRepairedEvent",
    "KeyComponent",
    "PlaceTrapHandler",
    "PickpocketHandler",
    "PoisonCharacterHandler",
    "PoisonComponent",
    "PoisonConsequence",
    "PoisonProgressedEvent",
    "PoisonTreatedEvent",
    "RaidHandler",
    "RaiderSpawnSpec",
    "RecruitFollowerHandler",
    "ReleaseThrallHandler",
    "RepairItemHandler",
    "PerformRitualHandler",
    "PrepareSiegeHandler",
    "PurgeWaveComponent",
    "PurgeWaveStartedEvent",
    "RitualComponent",
    "RitualPerformedEvent",
    "ShelterComponent",
    "ShrineComponent",
    "SiegePreparedEvent",
    "SiegeReadinessComponent",
    "SparHandler",
    "StartPurgeWaveHandler",
    "SubdueHandler",
    "StaminaChangedEvent",
    "StaminaComponent",
    "StaminaRegenSystem",
    "SurvivalGapBridgedEvent",
    "SurvivalGapComponent",
    "TemperatureExposureComponent",
    "TemperatureExposureConsequence",
    "TemperatureResistanceComponent",
    "TreasureClaimedEvent",
    "TreasureComponent",
    "TreasureUnlockedEvent",
    "ThrallComponent",
    "ThrallReleasedEvent",
    "ThrallTakenEvent",
    "TreatPoisonHandler",
    "TrapComponent",
    "TrapDisarmedEvent",
    "TrapPlacedEvent",
    "UnlockTreasureHandler",
    "UpgradeBuildingHandler",
    "WeaponComponent",
    "barbariansim_fragments",
    "ensure_barbariansim_policy",
    "generate_raid_spawn_specs",
    "install_barbariansim",
    "lethal_pvp_classifier",
    "pickpocket_classifier",
    "pvp_classifier",
]
