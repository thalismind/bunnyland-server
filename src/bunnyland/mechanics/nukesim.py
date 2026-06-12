"""Nuke-sim wasteland mechanics.

This slice covers radiation exposure, source-specific mutation pressure, deterministic
mutation manifestation, decontamination, rad medicine, scavenging, and scrapping. It
reuses colony-sim resource stacks/recipes and void-sim radiation pressure so other packs
can interoperate without sharing one large mutation system.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pydantic.dataclasses import dataclass
from relics import Component, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    DeadComponent,
    IdentityComponent,
    PortableComponent,
    SuspendedComponent,
)
from ..core.ecs import (
    container_of,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .colonysim import ResourceStackComponent
from .voidsim import RadiationMutationPressureComponent, RadiationShieldComponent

SECONDS_PER_HOUR = 60 * 60
DEFAULT_MUTATION_THRESHOLD = 10.0


@dataclass(frozen=True)
class RadiationSourceComponent(Component):
    source_type: str = "fallout hotspot"
    rads_per_hour: float = 1.0
    mutation_pressure_per_rad: float = 1.0
    sickness_per_rad: float = 0.25
    sealed: bool = False
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class RadiationDoseComponent(Component):
    amount: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class RadiationSicknessComponent(Component):
    severity: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class RadProtectionComponent(Component):
    """Fractional protection against nearby radiation, where 1.0 blocks all exposure."""

    rating: float = 0.0


@dataclass(frozen=True)
class DecontaminationComponent(Component):
    dose_reduction: float = 5.0
    sickness_reduction: float = 2.0
    mutation_pressure_reduction: float = 2.0
    uses: int | None = None


@dataclass(frozen=True)
class RadMedicineComponent(Component):
    dose_reduction: float = 3.0
    sickness_reduction: float = 1.0
    mutation_pressure_reduction: float = 1.0
    uses: int = 1


@dataclass(frozen=True)
class MutationThresholdComponent(Component):
    threshold: float = DEFAULT_MUTATION_THRESHOLD


@dataclass(frozen=True)
class MutationResistanceComponent(Component):
    threshold_bonus: float = 0.0
    pressure_multiplier: float = 1.0


@dataclass(frozen=True)
class MutationComponent(Component):
    mutation_id: str
    label: str
    source: str = "radiation"
    effect: str = ""
    stable: bool = False
    manifested_at_epoch: int = 0


@dataclass(frozen=True)
class ScavengeSiteComponent(Component):
    site_type: str = "ruin cache"
    charges: int = 1
    hazard_rads: float = 0.0
    depleted: bool = False
    last_scavenged_epoch: int = 0


@dataclass(frozen=True)
class LootTableComponent(Component):
    outputs: dict[str, int]


@dataclass(frozen=True)
class JunkComponent(Component):
    outputs: dict[str, int]
    contaminated_rads: float = 0.0


@dataclass(frozen=True)
class ChemComponent(Component):
    """A consumable wasteland chem; using it relieves radiation but builds addiction."""

    chem_type: str = "stimulant"
    dose_relief: float = 0.0
    sickness_relief: float = 0.0
    addiction_per_dose: float = 0.2


@dataclass(frozen=True)
class AddictionComponent(Component):
    """Per-chem addiction levels on a character; withdrawal decays them over time."""

    levels: dict[str, float]
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class WaterPurityComponent(Component):
    """A drinkable water source; ``rads_per_drink`` applies unless it is purified."""

    rads_per_drink: float = 0.0
    purified: bool = False


class RadiationExposureEvent(DomainEvent):
    character_id: str
    source_id: str
    source_type: str
    amount: float
    dose: float
    mutation_pressure: float


class RadiationSicknessChangedEvent(DomainEvent):
    character_id: str
    severity: float


class RadiationScannedEvent(DomainEvent):
    target_id: str
    rads_per_hour: float
    source_type: str
    sealed: bool


class RadiationSourceSealedEvent(DomainEvent):
    source_id: str
    source_type: str


class DecontaminationAppliedEvent(DomainEvent):
    target_id: str
    dose: float
    sickness: float
    mutation_pressure: float


class RadMedicineUsedEvent(DomainEvent):
    target_id: str
    item_id: str
    dose: float
    sickness: float
    mutation_pressure: float


class MutationPressureChangedEvent(DomainEvent):
    character_id: str
    amount: float


class MutationManifestedEvent(DomainEvent):
    character_id: str
    mutation_id: str
    label: str


class MutationStabilizedEvent(DomainEvent):
    character_id: str
    mutation_id: str


class SiteScavengedEvent(DomainEvent):
    site_id: str
    output_ids: tuple[str, ...] = ()


class LootFoundEvent(DomainEvent):
    site_id: str
    resource_type: str
    quantity: int
    stack_id: str


class HazardTriggeredEvent(DomainEvent):
    site_id: str
    hazard_type: str
    amount: float


class ItemScrappedEvent(DomainEvent):
    item_id: str
    output_ids: tuple[str, ...] = ()


class ChemTakenEvent(DomainEvent):
    character_id: str
    chem_type: str
    addiction: float


class WithdrawalProgressedEvent(DomainEvent):
    character_id: str
    chem_type: str
    level: float


class WaterPurifiedEvent(DomainEvent):
    item_id: str


class ContaminatedWaterDrunkEvent(DomainEvent):
    character_id: str
    item_id: str
    rads: float


def _event_base(epoch: int, **kwargs) -> dict:
    base = {
        "event_id": uuid4().hex,
        "world_epoch": epoch,
        "created_at": datetime.now(UTC),
        "visibility": EventVisibility.ROOM,
    }
    base.update(kwargs)
    return base


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


def _reachable_component(ctx: HandlerContext, character_id: EntityId, target_id, component):
    parsed = parse_entity_id(target_id)
    if parsed is None or not ctx.world.has_entity(parsed):
        return None, "target does not exist"
    character = ctx.entity(character_id)
    if parsed not in reachable_ids(ctx.world, character):
        return None, "target is not reachable"
    entity = ctx.entity(parsed)
    if not entity.has_component(component):
        return None, "target is the wrong kind"
    return entity, None


def _remove_from_container(world: World, entity_id: EntityId) -> None:
    entity = world.get_entity(entity_id)
    parent_id = container_of(entity)
    if parent_id is not None and world.has_entity(parent_id):
        world.get_entity(parent_id).remove_relationship(Contains, entity_id)


def _stack_name(resource_type: str, quantity: int) -> str:
    return f"{resource_type} x{quantity}"


def _resource_stack_in_inventory(
    character: Entity, world: World, resource_type: str
) -> Entity | None:
    for edge, item_id in character.get_relationships(Contains):
        if edge.mode != ContainmentMode.INVENTORY or not world.has_entity(item_id):
            continue
        item = world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == resource_type
        ):
            return item
    return None


def _add_resource_stack(
    character: Entity, world: World, resource_type: str, quantity: int
) -> str:
    existing = _resource_stack_in_inventory(character, world, resource_type)
    if existing is not None:
        stack = existing.get_component(ResourceStackComponent)
        updated = replace(stack, quantity=stack.quantity + quantity)
        replace_component(existing, updated)
        replace_component(
            existing,
            IdentityComponent(name=_stack_name(resource_type, updated.quantity), kind="resource"),
        )
        return str(existing.id)

    item = spawn_entity(
        world,
        [
            IdentityComponent(name=_stack_name(resource_type, quantity), kind="resource"),
            ResourceStackComponent(resource_type=resource_type, quantity=quantity),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _radiation_protection(world: World, character: Entity) -> float:
    protection = 0.0
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(RadProtectionComponent):
            protection += max(0.0, entity.get_component(RadProtectionComponent).rating)
        if entity.has_component(RadiationShieldComponent):
            protection += max(0.0, entity.get_component(RadiationShieldComponent).strength) / 100.0
    return min(1.0, protection)


def _radiation_targets_for_source(world: World, source_id: EntityId) -> list[Entity]:
    targets: list[Entity] = []
    for character in (
        world.query()
        .with_all([CharacterComponent])
        .with_none([DeadComponent, SuspendedComponent])
        .execute_entities()
    ):
        if source_id in reachable_ids(world, character):
            targets.append(character)
    return targets


def _radiation_pressure(character: Entity) -> RadiationMutationPressureComponent:
    if character.has_component(RadiationMutationPressureComponent):
        return character.get_component(RadiationMutationPressureComponent)
    return RadiationMutationPressureComponent()


def _apply_radiation(
    world: World,
    epoch: int,
    character: Entity,
    *,
    source_id: EntityId,
    source_type: str,
    amount: float,
    mutation_pressure_per_rad: float,
    sickness_per_rad: float,
    visibility: EventVisibility = EventVisibility.PRIVATE,
) -> list[DomainEvent]:
    if amount <= 0.0:
        return []

    dose = (
        character.get_component(RadiationDoseComponent)
        if character.has_component(RadiationDoseComponent)
        else RadiationDoseComponent()
    )
    updated_dose = replace(dose, amount=dose.amount + amount, last_updated_epoch=epoch)
    replace_component(character, updated_dose)

    resistance = (
        character.get_component(MutationResistanceComponent)
        if character.has_component(MutationResistanceComponent)
        else MutationResistanceComponent()
    )
    pressure_delta = amount * max(0.0, mutation_pressure_per_rad) * max(
        0.0, resistance.pressure_multiplier
    )
    pressure = _radiation_pressure(character)
    updated_pressure = replace(
        pressure,
        amount=pressure.amount + pressure_delta,
        last_updated_epoch=epoch,
    )
    replace_component(character, updated_pressure)

    sickness_delta = amount * max(0.0, sickness_per_rad)
    sickness = (
        character.get_component(RadiationSicknessComponent)
        if character.has_component(RadiationSicknessComponent)
        else RadiationSicknessComponent()
    )
    updated_sickness = replace(
        sickness,
        severity=min(100.0, sickness.severity + sickness_delta),
        last_updated_epoch=epoch,
    )
    replace_component(character, updated_sickness)

    base = {
        "visibility": visibility,
        "actor_id": str(character.id),
        "room_id": _room_id(world, character.id),
        "target_ids": (str(character.id), str(source_id)),
    }
    events: list[DomainEvent] = [
        RadiationExposureEvent(
            **_event_base(
                epoch,
                **base,
                character_id=str(character.id),
                source_id=str(source_id),
                source_type=source_type,
                amount=amount,
                dose=updated_dose.amount,
                mutation_pressure=updated_pressure.amount,
            )
        ),
        MutationPressureChangedEvent(
            **_event_base(
                epoch,
                **base,
                character_id=str(character.id),
                amount=updated_pressure.amount,
            )
        ),
    ]
    if updated_sickness.severity != sickness.severity:
        events.append(
            RadiationSicknessChangedEvent(
                **_event_base(
                    epoch,
                    **base,
                    character_id=str(character.id),
                    severity=updated_sickness.severity,
                )
            )
        )
    return events


def _reduce_radiation_state(
    character: Entity,
    epoch: int,
    *,
    dose_reduction: float,
    sickness_reduction: float,
    mutation_pressure_reduction: float,
) -> tuple[float, float, float]:
    dose_amount = 0.0
    sickness_amount = 0.0
    pressure_amount = 0.0
    if character.has_component(RadiationDoseComponent):
        dose = character.get_component(RadiationDoseComponent)
        dose_amount = max(0.0, dose.amount - max(0.0, dose_reduction))
        replace_component(character, replace(dose, amount=dose_amount, last_updated_epoch=epoch))
    if character.has_component(RadiationSicknessComponent):
        sickness = character.get_component(RadiationSicknessComponent)
        sickness_amount = max(0.0, sickness.severity - max(0.0, sickness_reduction))
        replace_component(
            character,
            replace(sickness, severity=sickness_amount, last_updated_epoch=epoch),
        )
    if character.has_component(RadiationMutationPressureComponent):
        pressure = character.get_component(RadiationMutationPressureComponent)
        pressure_amount = max(0.0, pressure.amount - max(0.0, mutation_pressure_reduction))
        replace_component(
            character,
            replace(pressure, amount=pressure_amount, last_updated_epoch=epoch),
        )
    return dose_amount, sickness_amount, pressure_amount


class RadiationExposureConsequence:
    """Apply nearby radiation sources to reachable, active characters."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for source in world.query().with_all([RadiationSourceComponent]).execute_entities():
            radiation = source.get_component(RadiationSourceComponent)
            elapsed = max(0, epoch - radiation.last_updated_epoch)
            replace_component(source, replace(radiation, last_updated_epoch=epoch))
            if elapsed <= 0 or radiation.sealed:
                continue
            hours = elapsed / SECONDS_PER_HOUR
            for character in _radiation_targets_for_source(world, source.id):
                protection = _radiation_protection(world, character)
                amount = max(0.0, radiation.rads_per_hour * (1.0 - protection) * hours)
                events.extend(
                    _apply_radiation(
                        world,
                        epoch,
                        character,
                        source_id=source.id,
                        source_type=radiation.source_type,
                        amount=amount,
                        mutation_pressure_per_rad=radiation.mutation_pressure_per_rad,
                        sickness_per_rad=radiation.sickness_per_rad,
                    )
                )
        return events


class MutationResolutionConsequence:
    """Resolve radiation mutation pressure into one deterministic mutation."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in (
            world.query()
            .with_all([CharacterComponent, RadiationMutationPressureComponent])
            .with_none([DeadComponent])
            .execute_entities()
        ):
            if character.has_component(MutationComponent):
                continue
            pressure = character.get_component(RadiationMutationPressureComponent)
            threshold = (
                character.get_component(MutationThresholdComponent).threshold
                if character.has_component(MutationThresholdComponent)
                else DEFAULT_MUTATION_THRESHOLD
            )
            resistance = (
                character.get_component(MutationResistanceComponent)
                if character.has_component(MutationResistanceComponent)
                else MutationResistanceComponent()
            )
            if pressure.amount < threshold + max(0.0, resistance.threshold_bonus):
                continue

            mutation = MutationComponent(
                mutation_id="rad-adapted",
                label="Rad-Adapted",
                effect="Radiation no longer feels entirely alien, but the body is changed.",
                stable=False,
                manifested_at_epoch=epoch,
            )
            replace_component(character, mutation)
            replace_component(
                character,
                replace(pressure, amount=0.0, last_updated_epoch=epoch),
            )
            events.append(
                MutationManifestedEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character.id),
                        room_id=_room_id(world, character.id),
                        target_ids=(str(character.id),),
                        character_id=str(character.id),
                        mutation_id=mutation.mutation_id,
                        label=mutation.label,
                    )
                )
            )
        return events


WITHDRAWAL_DECAY_PER_HOUR = 0.1


class AddictionWithdrawalConsequence:
    """Decay chem addiction over time; clearing a chem ends the addiction."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in (
            world.query()
            .with_all([AddictionComponent])
            .with_none([DeadComponent])
            .execute_entities()
        ):
            addiction = character.get_component(AddictionComponent)
            elapsed = max(0, epoch - addiction.last_updated_epoch)
            if elapsed <= 0:
                continue
            decay = WITHDRAWAL_DECAY_PER_HOUR * (elapsed / SECONDS_PER_HOUR)
            new_levels: dict[str, float] = {}
            changed = False
            for chem_type, level in addiction.levels.items():
                reduced = max(0.0, level - decay)
                if reduced != level:
                    changed = True
                if reduced > 0.0:
                    new_levels[chem_type] = reduced
            if not changed:
                replace_component(character, replace(addiction, last_updated_epoch=epoch))
                continue
            if new_levels:
                replace_component(
                    character, AddictionComponent(levels=new_levels, last_updated_epoch=epoch)
                )
            else:
                character.remove_component(AddictionComponent)
            for chem_type, level in new_levels.items():
                events.append(
                    WithdrawalProgressedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            target_ids=(str(character.id),),
                            character_id=str(character.id),
                            chem_type=chem_type,
                            level=level,
                        )
                    )
                )
        return events


class ScanRadiationHandler:
    command_type = "scan-radiation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        target, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), RadiationSourceComponent
        )
        if target is None:
            return rejected(error if error else "target is not radioactive")
        radiation = target.get_component(RadiationSourceComponent)
        return ok(
            RadiationScannedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target.id),),
                    target_id=str(target.id),
                    rads_per_hour=radiation.rads_per_hour,
                    source_type=radiation.source_type,
                    sealed=radiation.sealed,
                )
            )
        )


class SealRadiationSourceHandler:
    command_type = "seal-radiation-source"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        source, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), RadiationSourceComponent
        )
        if source is None:
            return rejected(error if error else "target is not radioactive")
        radiation = source.get_component(RadiationSourceComponent)
        if radiation.sealed:
            return rejected("radiation source is already sealed")
        replace_component(source, replace(radiation, sealed=True, last_updated_epoch=ctx.epoch))
        return ok(
            RadiationSourceSealedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(source.id),),
                    source_id=str(source.id),
                    source_type=radiation.source_type,
                )
            )
        )


class DecontaminateHandler:
    command_type = "decontaminate"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        target_id = parse_entity_id(command.payload.get("target_id")) or character_id
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        character = ctx.entity(character_id)
        if target_id != character_id and target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")

        station, error = _reachable_component(
            ctx, character_id, command.payload.get("station_id"), DecontaminationComponent
        )
        if station is None:
            return rejected(error if error else "decontamination station is required")
        decon = station.get_component(DecontaminationComponent)
        if decon.uses is not None and decon.uses <= 0:
            return rejected("decontamination station is spent")
        if decon.uses is not None:
            replace_component(station, replace(decon, uses=decon.uses - 1))

        target = ctx.entity(target_id)
        dose, sickness, pressure = _reduce_radiation_state(
            target,
            ctx.epoch,
            dose_reduction=decon.dose_reduction,
            sickness_reduction=decon.sickness_reduction,
            mutation_pressure_reduction=decon.mutation_pressure_reduction,
        )
        return ok(
            DecontaminationAppliedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id), str(station.id)),
                    target_id=str(target_id),
                    dose=dose,
                    sickness=sickness,
                    mutation_pressure=pressure,
                )
            )
        )


class UseRadMedicineHandler:
    command_type = "use-rad-medicine"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        medicine, error = _reachable_component(
            ctx, character_id, command.payload.get("item_id"), RadMedicineComponent
        )
        if medicine is None:
            return rejected(error if error else "item is not rad medicine")
        med = medicine.get_component(RadMedicineComponent)
        if med.uses <= 0:
            return rejected("rad medicine is spent")

        target_id = parse_entity_id(command.payload.get("target_id")) or character_id
        character = ctx.entity(character_id)
        if target_id != character_id and target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")
        target = ctx.entity(target_id)

        dose, sickness, pressure = _reduce_radiation_state(
            target,
            ctx.epoch,
            dose_reduction=med.dose_reduction,
            sickness_reduction=med.sickness_reduction,
            mutation_pressure_reduction=med.mutation_pressure_reduction,
        )
        if med.uses == 1:
            _remove_from_container(ctx.world, medicine.id)
        else:
            replace_component(medicine, replace(med, uses=med.uses - 1))

        return ok(
            RadMedicineUsedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id), str(medicine.id)),
                    target_id=str(target_id),
                    item_id=str(medicine.id),
                    dose=dose,
                    sickness=sickness,
                    mutation_pressure=pressure,
                )
            )
        )


class TakeChemHandler:
    command_type = "take-chem"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        chem_entity, error = _reachable_component(
            ctx, character_id, command.payload.get("chem_id"), ChemComponent
        )
        if chem_entity is None:
            return rejected(error if error else "item is not a chem")
        chem = chem_entity.get_component(ChemComponent)
        character = ctx.entity(character_id)

        if chem.dose_relief > 0.0 or chem.sickness_relief > 0.0:
            _reduce_radiation_state(
                character,
                ctx.epoch,
                dose_reduction=chem.dose_relief,
                sickness_reduction=chem.sickness_relief,
                mutation_pressure_reduction=0.0,
            )
        levels = (
            dict(character.get_component(AddictionComponent).levels)
            if character.has_component(AddictionComponent)
            else {}
        )
        levels[chem.chem_type] = levels.get(chem.chem_type, 0.0) + chem.addiction_per_dose
        if character.has_component(AddictionComponent):
            replace_component(
                character,
                replace(
                    character.get_component(AddictionComponent),
                    levels=levels,
                    last_updated_epoch=ctx.epoch,
                ),
            )
        else:
            character.add_component(
                AddictionComponent(levels=levels, last_updated_epoch=ctx.epoch)
            )
        _remove_from_container(ctx.world, chem_entity.id)
        return ok(
            ChemTakenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(chem_entity.id),),
                    character_id=str(character_id),
                    chem_type=chem.chem_type,
                    addiction=levels[chem.chem_type],
                )
            )
        )


class PurifyWaterHandler:
    command_type = "purify-water"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        water, error = _reachable_component(
            ctx, character_id, command.payload.get("water_id"), WaterPurityComponent
        )
        if water is None:
            return rejected(error if error else "target is not a water source")
        purity = water.get_component(WaterPurityComponent)
        if purity.purified:
            return rejected("water is already purified")
        replace_component(water, replace(purity, purified=True))
        return ok(
            WaterPurifiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(water.id),),
                    item_id=str(water.id),
                )
            )
        )


class DrinkContaminatedWaterHandler:
    command_type = "drink-water"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        water, error = _reachable_component(
            ctx, character_id, command.payload.get("water_id"), WaterPurityComponent
        )
        if water is None:
            return rejected(error if error else "target is not a water source")
        purity = water.get_component(WaterPurityComponent)
        rads = 0.0 if purity.purified else max(0.0, purity.rads_per_drink)
        character = ctx.entity(character_id)
        if rads > 0.0:
            current = (
                character.get_component(RadiationDoseComponent)
                if character.has_component(RadiationDoseComponent)
                else RadiationDoseComponent()
            )
            replace_component(
                character,
                replace(current, amount=current.amount + rads, last_updated_epoch=ctx.epoch),
            )
        return ok(
            ContaminatedWaterDrunkEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(water.id),),
                    character_id=str(character_id),
                    item_id=str(water.id),
                    rads=rads,
                )
            )
        )


class ScavengeHandler:
    command_type = "scavenge"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        site, error = _reachable_component(
            ctx, character_id, command.payload.get("site_id"), ScavengeSiteComponent
        )
        if site is None:
            return rejected(error if error else "target is not a scavenge site")
        state = site.get_component(ScavengeSiteComponent)
        if state.depleted or state.charges <= 0:
            return rejected("scavenge site is depleted")
        if not site.has_component(LootTableComponent):
            return rejected("scavenge site has no loot")

        character = ctx.entity(character_id)
        outputs: list[str] = []
        events: list[DomainEvent] = []
        for resource_type, quantity in site.get_component(LootTableComponent).outputs.items():
            if quantity <= 0:
                continue
            stack_id = _add_resource_stack(character, ctx.world, resource_type, quantity)
            outputs.append(stack_id)
            events.append(
                LootFoundEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(site.id), stack_id),
                        site_id=str(site.id),
                        resource_type=resource_type,
                        quantity=quantity,
                        stack_id=stack_id,
                    )
                )
            )

        remaining = state.charges - 1
        replace_component(
            site,
            replace(
                state,
                charges=remaining,
                depleted=remaining <= 0,
                last_scavenged_epoch=ctx.epoch,
            ),
        )
        events.insert(
            0,
            SiteScavengedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site.id), *outputs),
                    site_id=str(site.id),
                    output_ids=tuple(outputs),
                )
            ),
        )
        if state.hazard_rads > 0.0:
            events.append(
                HazardTriggeredEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(site.id), str(character_id)),
                        site_id=str(site.id),
                        hazard_type="radiation",
                        amount=state.hazard_rads,
                    )
                )
            )
            events.extend(
                _apply_radiation(
                    ctx.world,
                    ctx.epoch,
                    character,
                    source_id=site.id,
                    source_type=f"{state.site_type} hazard",
                    amount=state.hazard_rads * (1.0 - _radiation_protection(ctx.world, character)),
                    mutation_pressure_per_rad=1.0,
                    sickness_per_rad=0.25,
                )
            )
        return ok(*events)


class ScrapItemHandler:
    command_type = "scrap-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        item, error = _reachable_component(
            ctx, character_id, command.payload.get("item_id"), JunkComponent
        )
        if item is None:
            return rejected(error if error else "item cannot be scrapped")

        character = ctx.entity(character_id)
        junk = item.get_component(JunkComponent)
        output_ids = tuple(
            _add_resource_stack(character, ctx.world, resource_type, quantity)
            for resource_type, quantity in junk.outputs.items()
            if quantity > 0
        )
        if junk.contaminated_rads > 0.0:
            radiation_events = _apply_radiation(
                ctx.world,
                ctx.epoch,
                character,
                source_id=item.id,
                source_type="contaminated junk",
                amount=junk.contaminated_rads * (1.0 - _radiation_protection(ctx.world, character)),
                mutation_pressure_per_rad=1.0,
                sickness_per_rad=0.25,
            )
        else:
            radiation_events = []
        _remove_from_container(ctx.world, item.id)
        return ok(
            ItemScrappedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id), *output_ids),
                    item_id=str(item.id),
                    output_ids=output_ids,
                )
            ),
            *radiation_events,
        )


class StabilizeMutationHandler:
    command_type = "stabilize-mutation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if not character.has_component(MutationComponent):
            return rejected("no mutation to stabilize")
        mutation = character.get_component(MutationComponent)
        requested = str(command.payload.get("mutation_id") or mutation.mutation_id)
        if requested != mutation.mutation_id:
            return rejected("mutation does not match")
        if mutation.stable:
            return rejected("mutation is already stable")
        replace_component(character, replace(mutation, stable=True))
        return ok(
            MutationStabilizedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(character_id),),
                    character_id=str(character_id),
                    mutation_id=mutation.mutation_id,
                )
            )
        )


# --- Old-world tech recovery (catalogue 9.5) ------------------------------------------


@dataclass(frozen=True)
class OldWorldTechComponent(Component):
    """A pre-war device that can be identified and then restored to working order."""

    tech_name: str
    identified: bool = False
    functional: bool = False
    restore_scrap: int = 3


@dataclass(frozen=True)
class TechLeadComponent(Component):
    """A salvage lead pointing toward a piece of old-world tech."""

    target_tech: str
    location_hint: str = ""


class OldWorldTechIdentifiedEvent(DomainEvent):
    item_id: str
    tech_name: str


class OldWorldTechRestoredEvent(DomainEvent):
    item_id: str
    tech_name: str
    scrap_spent: int


class IdentifyTechHandler:
    command_type = "identify-tech"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        item, error = _reachable_component(
            ctx, character_id, command.payload.get("tech_id"), OldWorldTechComponent
        )
        if item is None:
            return rejected(error if error else "target is not old-world tech")
        tech = item.get_component(OldWorldTechComponent)
        if tech.identified:
            return rejected("tech is already identified")
        replace_component(item, replace(tech, identified=True))
        return ok(
            OldWorldTechIdentifiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    tech_name=tech.tech_name,
                )
            )
        )


class RestoreTechHandler:
    command_type = "restore-tech"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        item, error = _reachable_component(
            ctx, character_id, command.payload.get("tech_id"), OldWorldTechComponent
        )
        if item is None:
            return rejected(error if error else "target is not old-world tech")
        tech = item.get_component(OldWorldTechComponent)
        if not tech.identified:
            return rejected("identify the tech first")
        if tech.functional:
            return rejected("tech is already functional")

        character = ctx.entity(character_id)
        stack_entity = _resource_stack_in_inventory(character, ctx.world, "scrap")
        have = (
            stack_entity.get_component(ResourceStackComponent).quantity
            if stack_entity is not None
            else 0
        )
        if have < tech.restore_scrap:
            return rejected("not enough scrap to restore")

        stack = stack_entity.get_component(ResourceStackComponent)
        remaining = stack.quantity - tech.restore_scrap
        if remaining > 0:
            replace_component(stack_entity, replace(stack, quantity=remaining))
            replace_component(
                stack_entity,
                IdentityComponent(name=_stack_name("scrap", remaining), kind="resource"),
            )
        else:
            _remove_from_container(ctx.world, stack_entity.id)
        replace_component(item, replace(tech, functional=True))
        return ok(
            OldWorldTechRestoredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    tech_name=tech.tech_name,
                    scrap_spent=tech.restore_scrap,
                )
            )
        )


def nukesim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    if character.has_component(RadiationDoseComponent):
        dose = character.get_component(RadiationDoseComponent)
        if dose.amount > 0.0:
            lines.append(f"Radiation dose: {dose.amount:g} rads.")
    if character.has_component(RadiationSicknessComponent):
        sickness = character.get_component(RadiationSicknessComponent)
        if sickness.severity > 0.0:
            lines.append(f"Radiation sickness severity: {sickness.severity:g}.")
    if character.has_component(RadiationMutationPressureComponent):
        pressure = character.get_component(RadiationMutationPressureComponent)
        if pressure.amount > 0.0:
            lines.append(f"Radiation mutation pressure: {pressure.amount:g}.")
    if character.has_component(MutationComponent):
        mutation = character.get_component(MutationComponent)
        state = "stable" if mutation.stable else "unstable"
        lines.append(f"Mutation: {mutation.label} ({state}).")
    if character.has_component(AddictionComponent):
        for chem_type, level in character.get_component(AddictionComponent).levels.items():
            lines.append(f"Addiction to {chem_type}: {level:.1f}.")

    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(ChemComponent):
            lines.append(f"Chem available: {entity.get_component(ChemComponent).chem_type}.")
        if entity.has_component(WaterPurityComponent):
            purity = entity.get_component(WaterPurityComponent)
            if purity.purified:
                state = "purified"
            elif purity.rads_per_drink > 0.0:
                state = f"contaminated ({purity.rads_per_drink:g} rads/drink)"
            else:
                state = "clean"
            lines.append(f"Water source {_name(entity)}: {state}.")
        if entity.has_component(RadiationSourceComponent):
            source = entity.get_component(RadiationSourceComponent)
            status = "sealed" if source.sealed else f"{source.rads_per_hour:g} rads/hour"
            lines.append(f"Radiation source {_name(entity)}: {source.source_type}, {status}.")
        if entity.has_component(ScavengeSiteComponent):
            site = entity.get_component(ScavengeSiteComponent)
            status = "depleted" if site.depleted else f"{site.charges} searches left"
            lines.append(f"Scavenge site {_name(entity)}: {site.site_type}, {status}.")
        if entity.has_component(DecontaminationComponent):
            lines.append(f"Decontamination available: {_name(entity)}.")
        if entity.has_component(RadMedicineComponent):
            lines.append(f"Rad medicine available: {_name(entity)}.")
        if entity.has_component(JunkComponent):
            lines.append(f"Scrappable junk: {_name(entity)}.")
        if entity.has_component(OldWorldTechComponent):
            tech = entity.get_component(OldWorldTechComponent)
            label = tech.tech_name if tech.identified else "unknown device"
            if tech.functional:
                state = "functional"
            elif tech.identified:
                state = f"identified, needs {tech.restore_scrap} scrap to restore"
            else:
                state = "unidentified"
            lines.append(f"Old-world tech {_name(entity)}: {label} ({state}).")
        if entity.has_component(TechLeadComponent):
            lead = entity.get_component(TechLeadComponent)
            hint = f" near {lead.location_hint}" if lead.location_hint else ""
            lines.append(f"Tech lead: {lead.target_tech}{hint}.")
    return sorted(lines)


def install_nukesim(actor) -> None:
    actor.register_consequence(RadiationExposureConsequence())
    actor.register_consequence(MutationResolutionConsequence())
    actor.register_consequence(AddictionWithdrawalConsequence())


__all__ = [
    "AddictionComponent",
    "AddictionWithdrawalConsequence",
    "ChemComponent",
    "ChemTakenEvent",
    "ContaminatedWaterDrunkEvent",
    "DecontaminateHandler",
    "DecontaminationAppliedEvent",
    "DecontaminationComponent",
    "DrinkContaminatedWaterHandler",
    "HazardTriggeredEvent",
    "IdentifyTechHandler",
    "ItemScrappedEvent",
    "JunkComponent",
    "LootFoundEvent",
    "LootTableComponent",
    "OldWorldTechComponent",
    "OldWorldTechIdentifiedEvent",
    "OldWorldTechRestoredEvent",
    "MutationComponent",
    "MutationManifestedEvent",
    "MutationPressureChangedEvent",
    "MutationResistanceComponent",
    "MutationResolutionConsequence",
    "MutationStabilizedEvent",
    "MutationThresholdComponent",
    "PurifyWaterHandler",
    "RadMedicineComponent",
    "RadMedicineUsedEvent",
    "RadProtectionComponent",
    "RadiationDoseComponent",
    "RadiationExposureConsequence",
    "RadiationExposureEvent",
    "RadiationScannedEvent",
    "RadiationSicknessChangedEvent",
    "RadiationSicknessComponent",
    "RadiationSourceComponent",
    "RadiationSourceSealedEvent",
    "RestoreTechHandler",
    "ScanRadiationHandler",
    "ScavengeHandler",
    "ScavengeSiteComponent",
    "ScrapItemHandler",
    "SealRadiationSourceHandler",
    "SiteScavengedEvent",
    "StabilizeMutationHandler",
    "TakeChemHandler",
    "TechLeadComponent",
    "UseRadMedicineHandler",
    "WaterPurifiedEvent",
    "WaterPurityComponent",
    "WithdrawalProgressedEvent",
    "install_nukesim",
    "nukesim_fragments",
]
