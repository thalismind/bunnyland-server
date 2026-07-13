"""Nuke-sim wasteland mechanics.

This slice covers radiation exposure, source-specific mutation pressure, deterministic
mutation manifestation, decontamination, rad medicine, scavenging, and scrapping. It
reuses colony-sim resource stacks/recipes and shared radiation pressure so other packs can
interoperate without sharing one large mutation system.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial

from pydantic.dataclasses import dataclass
from relics import Component, Entity, EntityId, World

from bunnyland.foundation.mutation.mechanics import (
    RadiationMutationPressureComponent,
    RadiationShieldComponent,
)
from bunnyland.simpacks.barbariansim.mechanics import DurabilityComponent
from bunnyland.simpacks.colonysim.mechanics import ResourceStackComponent

from ...core.commands import SubmittedCommand
from ...core.components import (
    CharacterComponent,
    DeadComponent,
    IdentityComponent,
    PortableComponent,
    SuspendedComponent,
)
from ...core.ecs import (
    container_of,
    parse_entity_id,
    reachable_ids,
    replace_component,
)
from ...core.ecs import (
    entity_name as _name,
)
from ...core.ecs import (
    reachable_component as _reachable_component,
)
from ...core.ecs import (
    room_id_for as _room_id,
)
from ...core.edges import ContainmentMode, Contains
from ...core.events import DomainEvent, EventVisibility, event_base
from ...core.handlers import (
    HandlerContext,
    HandlerResult,
    planned,
    rejected,
    require_character,
)
from ...core.mutations import (
    AddComponent,
    AddEdge,
    AddEntity,
    EntityReference,
    MutationOperation,
    MutationPlan,
    RemoveEdge,
    SetComponent,
)
from ...prompts import ComponentPromptContext

SECONDS_PER_HOUR = 60 * 60
DEFAULT_MUTATION_THRESHOLD = 10.0


def _payload_entity_id(command: SubmittedCommand, *keys: str):
    for key in keys:
        if key in command.payload:
            return parse_entity_id(command.payload.get(key))
    return None


@dataclass(frozen=True)
class RadiationSourceComponent(Component):
    source_type: str = "fallout hotspot"
    rads_per_hour: float = 1.0
    mutation_pressure_per_rad: float = 1.0
    sickness_per_rad: float = 0.25
    sealed: bool = False
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        status = "sealed" if self.sealed else f"{self.rads_per_hour:g} rads/hour"
        return (f"Radiation source {_name(ctx.entity)}: {self.source_type}, {status}.",)


@dataclass(frozen=True)
class RadiationDoseComponent(Component):
    amount: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or self.amount <= 0.0:
            return ()
        return (f"Radiation dose: {self.amount:g} rads.",)


@dataclass(frozen=True)
class RadiationSicknessComponent(Component):
    severity: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or self.severity <= 0.0:
            return ()
        return (f"Radiation sickness severity: {self.severity:g}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Decontamination available: {_name(ctx.entity)}.",)


@dataclass(frozen=True)
class RadMedicineComponent(Component):
    dose_reduction: float = 3.0
    sickness_reduction: float = 1.0
    mutation_pressure_reduction: float = 1.0
    uses: int = 1

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Rad medicine available: {_name(ctx.entity)}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        state = "stable" if self.stable else "unstable"
        return (f"Mutation: {self.label} ({state}).",)


@dataclass(frozen=True)
class ScavengeSiteComponent(Component):
    site_type: str = "ruin cache"
    charges: int = 1
    hazard_rads: float = 0.0
    depleted: bool = False
    last_scavenged_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        status = "depleted" if self.depleted else f"{self.charges} searches left"
        return (f"Scavenge site {_name(ctx.entity)}: {self.site_type}, {status}.",)


@dataclass(frozen=True)
class LootTableComponent(Component):
    outputs: dict[str, int]


@dataclass(frozen=True)
class JunkComponent(Component):
    outputs: dict[str, int]
    contaminated_rads: float = 0.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Scrappable junk: {_name(ctx.entity)}.",)


@dataclass(frozen=True)
class ChemComponent(Component):
    """A consumable wasteland chem; using it relieves radiation but builds addiction."""

    chem_type: str = "stimulant"
    dose_relief: float = 0.0
    sickness_relief: float = 0.0
    addiction_per_dose: float = 0.2

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Chem available: {self.chem_type}.",)


@dataclass(frozen=True)
class AddictionComponent(Component):
    """Per-chem addiction levels on a character; withdrawal decays them over time."""

    levels: dict[str, float]
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return tuple(
            f"Addiction to {chem_type}: {level:.1f}."
            for chem_type, level in sorted(self.levels.items())
        )


@dataclass(frozen=True)
class WaterPurityComponent(Component):
    """A drinkable water source; ``rads_per_drink`` applies unless it is purified."""

    rads_per_drink: float = 0.0
    purified: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.purified:
            state = "purified"
        elif self.rads_per_drink > 0.0:
            state = f"contaminated ({self.rads_per_drink:g} rads/drink)"
        else:
            state = "clean"
        return (f"Water source {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class HotspotMarkerComponent(Component):
    source_id: str
    marked_by: str
    label: str = "hotspot"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Hotspot marker: {self.label}.",)


@dataclass(frozen=True)
class SuppressantComponent(Component):
    pressure_reduction: float = 1.0
    uses: int = 1

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Radiation suppressant available: {_name(ctx.entity)}.",)


@dataclass(frozen=True)
class SampleComponent(Component):
    sample_type: str = "irradiated tissue"
    studied_by: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        studied = (
            ctx.target is not None
            and str(ctx.target.id) in self.studied_by
            and ctx.can_view_private_state
        )
        state = "studied" if studied else "unstudied"
        return (f"Sample {_name(ctx.entity)}: {self.sample_type} ({state}).",)


@dataclass(frozen=True)
class LockedCrateComponent(Component):
    locked: bool = True
    key_name: str = ""

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Locked crate {_name(ctx.entity)}: {'locked' if self.locked else 'open'}.",)


@dataclass(frozen=True)
class WastelandArtifactComponent(Component):
    artifact_type: str = "relic"
    studied: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "studied" if self.studied else "unstudied"
        return (f"Wasteland artifact {_name(ctx.entity)}: {self.artifact_type} ({state}).",)


@dataclass(frozen=True)
class FactionSalvageComponent(Component):
    faction_id: str
    claimed_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "claimed" if self.claimed_by else "available"
        return (f"Faction salvage {_name(ctx.entity)}: {self.faction_id}, {state}.",)


@dataclass(frozen=True)
class SchematicComponent(Component):
    mod_name: str
    resource_inputs: tuple[tuple[str, int], ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Schematic {_name(ctx.entity)}: {self.mod_name}.",)


@dataclass(frozen=True)
class ItemModComponent(Component):
    mod_name: str
    installed: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Item mod {_name(ctx.entity)}: {self.mod_name}.",)


@dataclass(frozen=True)
class FieldRepairComponent(Component):
    repair_amount: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Field repair kit {_name(ctx.entity)}: +{self.repair_amount:g}.",)


@dataclass(frozen=True)
class ChemRecipeComponent(Component):
    chem_type: str
    resource_inputs: tuple[tuple[str, int], ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Chem recipe {_name(ctx.entity)}: {self.chem_type}.",)


@dataclass(frozen=True)
class BeaconComponent(Component):
    message: str = "safe route"
    active: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "active" if self.active else "inactive"
        return (f"Beacon {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class TraderRouteComponent(Component):
    destination: str
    open: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "open" if self.open else "closed"
        return (f"Trader route {_name(ctx.entity)}: {self.destination} ({state}).",)


@dataclass(frozen=True)
class RaiderPressureComponent(Component):
    pressure: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Raider pressure at {_name(ctx.entity)}: {self.pressure}.",)


@dataclass(frozen=True)
class TerminalComponent(Component):
    booted: bool = False
    access_level: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "booted" if self.booted else "offline"
        return (f"Terminal {_name(ctx.entity)}: {state}, access {self.access_level}.",)


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


class HotspotMarkedEvent(DomainEvent):
    source_id: str
    marker_id: str


class SuppressantUsedEvent(DomainEvent):
    item_id: str
    pressure: float


class SampleHarvestedEvent(DomainEvent):
    sample_id: str
    sample_type: str


class SampleStudiedEvent(DomainEvent):
    sample_id: str
    sample_type: str


class CrateUnlockedEvent(DomainEvent):
    crate_id: str


class WastelandArtifactStudiedEvent(DomainEvent):
    artifact_id: str
    artifact_type: str


class FactionSalvageClaimedEvent(DomainEvent):
    salvage_id: str
    faction_id: str


class ModInstalledEvent(DomainEvent):
    item_id: str
    mod_name: str


class FieldRepairAppliedEvent(DomainEvent):
    item_id: str
    durability: float


class ChemBrewedEvent(DomainEvent):
    chem_id: str
    chem_type: str


class BeaconActivatedEvent(DomainEvent):
    beacon_id: str
    message: str


class TraderRouteOpenedEvent(DomainEvent):
    route_id: str
    destination: str


class RaiderPressureChangedEvent(DomainEvent):
    target_id: str
    pressure: int


class TerminalBootedEvent(DomainEvent):
    terminal_id: str
    access_level: int


_event_base = partial(event_base, default_visibility=EventVisibility.ROOM)


def _stack_name(resource_type: str, quantity: int) -> str:
    return f"{resource_type} x{quantity}"


def _resource_stack_in_inventory(
    character: Entity, world: World, resource_type: str
) -> Entity | None:
    for edge, item_id in character.get_relationships(Contains):
        if edge.mode != ContainmentMode.INVENTORY:
            continue
        item = world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == resource_type
        ):
            return item
    return None


def _add_resource_operations(
    character: Entity,
    world: World,
    resource_type: str,
    quantity: int,
) -> tuple[list[MutationOperation], EntityId | EntityReference]:
    existing = _resource_stack_in_inventory(character, world, resource_type)
    if existing is not None:
        stack = existing.get_component(ResourceStackComponent)
        updated = replace(stack, quantity=stack.quantity + quantity)
        return [
            SetComponent(existing.id, updated),
            SetComponent(
                existing.id,
                IdentityComponent(
                    name=_stack_name(resource_type, updated.quantity),
                    kind="resource",
                ),
            ),
        ], existing.id

    item = EntityReference()
    return [
        AddEntity(
            (
                IdentityComponent(name=_stack_name(resource_type, quantity), kind="resource"),
                ResourceStackComponent(resource_type=resource_type, quantity=quantity),
                PortableComponent(can_pick_up=True),
            ),
            reference=item,
        ),
        AddEdge(character.id, item, Contains(mode=ContainmentMode.INVENTORY)),
    ], item


def _spend_inventory_resource_operations(
    character: Entity, world: World, resource_type: str, quantity: int
) -> list[MutationOperation] | None:
    stack_entity = _resource_stack_in_inventory(character, world, resource_type)
    have = (
        stack_entity.get_component(ResourceStackComponent).quantity
        if stack_entity is not None
        else 0
    )
    if have < quantity:
        return None
    assert stack_entity is not None
    stack = stack_entity.get_component(ResourceStackComponent)
    remaining = stack.quantity - quantity
    if remaining > 0:
        return [
            SetComponent(stack_entity.id, replace(stack, quantity=remaining)),
            SetComponent(
                stack_entity.id,
                IdentityComponent(name=_stack_name(resource_type, remaining), kind="resource"),
            ),
        ]
    return [RemoveEdge(character.id, stack_entity.id, Contains)]


def _entity_target_id(target: EntityId | EntityReference) -> str:
    return str(target.require() if isinstance(target, EntityReference) else target)


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


def _radiation_operations(
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
) -> tuple[list[MutationOperation], list[DomainEvent]]:
    if amount <= 0.0:
        return [], []

    dose = (
        character.get_component(RadiationDoseComponent)
        if character.has_component(RadiationDoseComponent)
        else RadiationDoseComponent()
    )
    updated_dose = replace(dose, amount=dose.amount + amount, last_updated_epoch=epoch)

    resistance = (
        character.get_component(MutationResistanceComponent)
        if character.has_component(MutationResistanceComponent)
        else MutationResistanceComponent()
    )
    pressure_delta = (
        amount * max(0.0, mutation_pressure_per_rad) * max(0.0, resistance.pressure_multiplier)
    )
    pressure = _radiation_pressure(character)
    updated_pressure = replace(
        pressure,
        amount=pressure.amount + pressure_delta,
        last_updated_epoch=epoch,
    )

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
    operations: list[MutationOperation] = [
        SetComponent(character.id, updated_dose),
        SetComponent(character.id, updated_pressure),
        SetComponent(character.id, updated_sickness),
    ]

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
    return operations, events


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
    operations, events = _radiation_operations(
        world,
        epoch,
        character,
        source_id=source_id,
        source_type=source_type,
        amount=amount,
        mutation_pressure_per_rad=mutation_pressure_per_rad,
        sickness_per_rad=sickness_per_rad,
        visibility=visibility,
    )
    for operation in operations:
        assert isinstance(operation, SetComponent)
        replace_component(character, operation.component)
    return events


def _reduce_radiation_operations(
    character: Entity,
    epoch: int,
    *,
    dose_reduction: float,
    sickness_reduction: float,
    mutation_pressure_reduction: float,
) -> tuple[list[MutationOperation], float, float, float]:
    operations: list[MutationOperation] = []
    dose_amount = 0.0
    sickness_amount = 0.0
    pressure_amount = 0.0
    if character.has_component(RadiationDoseComponent):
        dose = character.get_component(RadiationDoseComponent)
        dose_amount = max(0.0, dose.amount - max(0.0, dose_reduction))
        operations.append(
            SetComponent(
                character.id,
                replace(dose, amount=dose_amount, last_updated_epoch=epoch),
            )
        )
    if character.has_component(RadiationSicknessComponent):
        sickness = character.get_component(RadiationSicknessComponent)
        sickness_amount = max(0.0, sickness.severity - max(0.0, sickness_reduction))
        operations.append(
            SetComponent(
                character.id,
                replace(sickness, severity=sickness_amount, last_updated_epoch=epoch),
            )
        )
    if character.has_component(RadiationMutationPressureComponent):
        pressure = character.get_component(RadiationMutationPressureComponent)
        pressure_amount = max(0.0, pressure.amount - max(0.0, mutation_pressure_reduction))
        operations.append(
            SetComponent(
                character.id,
                replace(pressure, amount=pressure_amount, last_updated_epoch=epoch),
            )
        )
    return operations, dose_amount, sickness_amount, pressure_amount


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
            ctx.world, character_id, command.payload.get("target_id"), RadiationSourceComponent
        )
        if target is None:
            return rejected(error if error else "target is not radioactive")
        radiation = target.get_component(RadiationSourceComponent)
        return planned(
            MutationPlan(),
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
            ),
            ctx=ctx,
        )


class SealRadiationSourceHandler:
    command_type = "seal-radiation-source"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        source, error = _reachable_component(
            ctx.world, character_id, command.payload.get("target_id"), RadiationSourceComponent
        )
        if source is None:
            return rejected(error if error else "target is not radioactive")
        radiation = source.get_component(RadiationSourceComponent)
        if radiation.sealed:
            return rejected("radiation source is already sealed")
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        source.id,
                        replace(radiation, sealed=True, last_updated_epoch=ctx.epoch),
                    ),
                )
            ),
            RadiationSourceSealedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(source.id),),
                    source_id=str(source.id),
                    source_type=radiation.source_type,
                )
            ),
            ctx=ctx,
        )


class DecontaminateHandler:
    command_type = "decontaminate"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        target_raw = command.payload.get("target_character_id")
        if target_raw is None:
            target_raw = command.payload.get("patient_id")
        if target_raw is None and "item_id" in command.payload:
            target_raw = command.payload.get("target_id")
        target_id = parse_entity_id(target_raw) or character_id
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        character = ctx.entity(character_id)
        if target_id != character_id and target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")

        station, error = _reachable_component(
            ctx.world, character_id, command.payload.get("station_id"), DecontaminationComponent
        )
        if station is None:
            return rejected(error if error else "decontamination station is required")
        decon = station.get_component(DecontaminationComponent)
        if decon.uses is not None and decon.uses <= 0:
            return rejected("decontamination station is spent")
        operations: list[MutationOperation] = []
        if decon.uses is not None:
            operations.append(SetComponent(station.id, replace(decon, uses=decon.uses - 1)))

        target = ctx.entity(target_id)
        reduction_operations, dose, sickness, pressure = _reduce_radiation_operations(
            target,
            ctx.epoch,
            dose_reduction=decon.dose_reduction,
            sickness_reduction=decon.sickness_reduction,
            mutation_pressure_reduction=decon.mutation_pressure_reduction,
        )
        operations.extend(reduction_operations)
        return planned(
            MutationPlan(tuple(operations)),
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
            ),
            ctx=ctx,
        )


class UseRadMedicineHandler:
    command_type = "use"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        item_id = _payload_entity_id(command, "item_id")
        if item_id is None or not ctx.world.has_entity(item_id):
            return "item_id" in command.payload
        return (
            item_id is not None
            and ctx.world.has_entity(item_id)
            and ctx.entity(item_id).has_component(RadMedicineComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        medicine, error = _reachable_component(
            ctx.world,
            character_id,
            _payload_entity_id(command, "item_id"),
            RadMedicineComponent,
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

        operations, dose, sickness, pressure = _reduce_radiation_operations(
            target,
            ctx.epoch,
            dose_reduction=med.dose_reduction,
            sickness_reduction=med.sickness_reduction,
            mutation_pressure_reduction=med.mutation_pressure_reduction,
        )
        if med.uses == 1:
            container_id = container_of(medicine)
            if container_id is not None:
                operations.append(RemoveEdge(container_id, medicine.id, Contains))
        else:
            operations.append(SetComponent(medicine.id, replace(med, uses=med.uses - 1)))

        return planned(
            MutationPlan(tuple(operations)),
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
            ),
            ctx=ctx,
        )


class TakeChemHandler:
    command_type = "take-chem"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        chem_entity, error = _reachable_component(
            ctx.world, character_id, command.payload.get("chem_id"), ChemComponent
        )
        if chem_entity is None:
            return rejected(error if error else "item is not a chem")
        chem = chem_entity.get_component(ChemComponent)
        character = ctx.entity(character_id)

        operations: list[MutationOperation] = []
        if chem.dose_relief > 0.0 or chem.sickness_relief > 0.0:
            reduction_operations, _dose, _sickness, _pressure = _reduce_radiation_operations(
                character,
                ctx.epoch,
                dose_reduction=chem.dose_relief,
                sickness_reduction=chem.sickness_relief,
                mutation_pressure_reduction=0.0,
            )
            operations.extend(reduction_operations)
        levels = (
            dict(character.get_component(AddictionComponent).levels)
            if character.has_component(AddictionComponent)
            else {}
        )
        levels[chem.chem_type] = levels.get(chem.chem_type, 0.0) + chem.addiction_per_dose
        if character.has_component(AddictionComponent):
            operations.append(
                SetComponent(
                    character_id,
                    replace(
                        character.get_component(AddictionComponent),
                        levels=levels,
                        last_updated_epoch=ctx.epoch,
                    ),
                ),
            )
        else:
            operations.append(
                AddComponent(
                    character_id,
                    AddictionComponent(levels=levels, last_updated_epoch=ctx.epoch),
                )
            )
        container_id = container_of(chem_entity)
        if container_id is not None:
            operations.append(RemoveEdge(container_id, chem_entity.id, Contains))
        return planned(
            MutationPlan(tuple(operations)),
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
            ),
            ctx=ctx,
        )


class PurifyWaterHandler:
    command_type = "purify-water"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        water, error = _reachable_component(
            ctx.world, character_id, command.payload.get("water_id"), WaterPurityComponent
        )
        if water is None:
            return rejected(error if error else "target is not a water source")
        purity = water.get_component(WaterPurityComponent)
        if purity.purified:
            return rejected("water is already purified")
        return planned(
            MutationPlan((SetComponent(water.id, replace(purity, purified=True)),)),
            WaterPurifiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(water.id),),
                    item_id=str(water.id),
                )
            ),
            ctx=ctx,
        )


class DrinkContaminatedWaterHandler:
    command_type = "drink"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        if "water_id" in command.payload:
            return True
        water_id = _payload_entity_id(command, "water_id", "source_id", "target_id")
        return (
            water_id is not None
            and ctx.world.has_entity(water_id)
            and ctx.entity(water_id).has_component(WaterPurityComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        water, error = _reachable_component(
            ctx.world,
            character_id,
            _payload_entity_id(command, "water_id", "source_id", "target_id"),
            WaterPurityComponent,
        )
        if water is None:
            return rejected(error if error else "target is not a water source")
        purity = water.get_component(WaterPurityComponent)
        rads = 0.0 if purity.purified else max(0.0, purity.rads_per_drink)
        character = ctx.entity(character_id)
        operations: tuple[MutationOperation, ...] = ()
        if rads > 0.0:
            current = (
                character.get_component(RadiationDoseComponent)
                if character.has_component(RadiationDoseComponent)
                else RadiationDoseComponent()
            )
            operations = (
                SetComponent(
                    character_id,
                    replace(current, amount=current.amount + rads, last_updated_epoch=ctx.epoch),
                ),
            )
        return planned(
            MutationPlan(operations),
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
            ),
            ctx=ctx,
        )


class ScavengeHandler:
    command_type = "scavenge"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        site, error = _reachable_component(
            ctx.world, character_id, command.payload.get("site_id"), ScavengeSiteComponent
        )
        if site is None:
            return rejected(error if error else "target is not a scavenge site")
        state = site.get_component(ScavengeSiteComponent)
        if state.depleted or state.charges <= 0:
            return rejected("scavenge site is depleted")
        if not site.has_component(LootTableComponent):
            return rejected("scavenge site has no loot")

        character = ctx.entity(character_id)
        operations: list[MutationOperation] = []
        outputs: list[EntityId | EntityReference] = []
        loot: list[tuple[str, int, EntityId | EntityReference]] = []
        for resource_type, quantity in site.get_component(LootTableComponent).outputs.items():
            if quantity <= 0:
                continue
            stack_operations, stack = _add_resource_operations(
                character,
                ctx.world,
                resource_type,
                quantity,
            )
            operations.extend(stack_operations)
            outputs.append(stack)
            loot.append((resource_type, quantity, stack))

        def site_event() -> DomainEvent:
            output_ids = tuple(_entity_target_id(output) for output in outputs)
            return SiteScavengedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site.id), *output_ids),
                    site_id=str(site.id),
                    output_ids=output_ids,
                )
            )

        event_factories = [site_event]
        for resource_type, quantity, stack in loot:

            def loot_event(
                resource_type=resource_type,
                quantity=quantity,
                stack=stack,
            ) -> DomainEvent:
                stack_id = _entity_target_id(stack)
                return LootFoundEvent(
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

            event_factories.append(loot_event)

        remaining = state.charges - 1
        operations.append(
            SetComponent(
                site.id,
                replace(
                    state,
                    charges=remaining,
                    depleted=remaining <= 0,
                    last_scavenged_epoch=ctx.epoch,
                ),
            ),
        )
        if state.hazard_rads > 0.0:
            event_factories.append(
                lambda: HazardTriggeredEvent(
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
            radiation_operations, radiation_events = _radiation_operations(
                ctx.world,
                ctx.epoch,
                character,
                source_id=site.id,
                source_type=f"{state.site_type} hazard",
                amount=state.hazard_rads * (1.0 - _radiation_protection(ctx.world, character)),
                mutation_pressure_per_rad=1.0,
                sickness_per_rad=0.25,
            )
            operations.extend(radiation_operations)
            event_factories.extend(lambda event=event: event for event in radiation_events)
        return planned(
            MutationPlan(tuple(operations)),
            *event_factories,
            ctx=ctx,
        )


class ScrapItemHandler:
    command_type = "scrap-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        item, error = _reachable_component(
            ctx.world, character_id, command.payload.get("item_id"), JunkComponent
        )
        if item is None:
            return rejected(error if error else "item cannot be scrapped")

        character = ctx.entity(character_id)
        junk = item.get_component(JunkComponent)
        operations: list[MutationOperation] = []
        outputs: list[EntityId | EntityReference] = []
        for resource_type, quantity in junk.outputs.items():
            if quantity <= 0:
                continue
            stack_operations, stack = _add_resource_operations(
                character,
                ctx.world,
                resource_type,
                quantity,
            )
            operations.extend(stack_operations)
            outputs.append(stack)
        if junk.contaminated_rads > 0.0:
            radiation_operations, radiation_events = _radiation_operations(
                ctx.world,
                ctx.epoch,
                character,
                source_id=item.id,
                source_type="contaminated junk",
                amount=junk.contaminated_rads * (1.0 - _radiation_protection(ctx.world, character)),
                mutation_pressure_per_rad=1.0,
                sickness_per_rad=0.25,
            )
            operations.extend(radiation_operations)
        else:
            radiation_events = []
        container_id = container_of(item)
        if container_id is not None:
            operations.append(RemoveEdge(container_id, item.id, Contains))

        def scrapped_event() -> DomainEvent:
            output_ids = tuple(_entity_target_id(output) for output in outputs)
            return ItemScrappedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id), *output_ids),
                    item_id=str(item.id),
                    output_ids=output_ids,
                )
            )

        return planned(
            MutationPlan(tuple(operations)),
            scrapped_event,
            *(lambda event=event: event for event in radiation_events),
            ctx=ctx,
        )


class StabilizeMutationHandler:
    command_type = "stabilize-mutation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if not character.has_component(MutationComponent):
            return rejected("no mutation to stabilize")
        mutation = character.get_component(MutationComponent)
        requested = str(command.payload.get("mutation_id") or mutation.mutation_id)
        if requested != mutation.mutation_id:
            return rejected("mutation does not match")
        if mutation.stable:
            return rejected("mutation is already stable")
        return planned(
            MutationPlan((SetComponent(character_id, replace(mutation, stable=True)),)),
            MutationStabilizedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(character_id),),
                    character_id=str(character_id),
                    mutation_id=mutation.mutation_id,
                )
            ),
            ctx=ctx,
        )


class MarkHotspotHandler:
    command_type = "mark-hotspot"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        source, error = _reachable_component(
            ctx.world, character_id, command.payload.get("source_id"), RadiationSourceComponent
        )
        if source is None:
            return rejected(error if error else "target is not a radiation source")
        label = str(command.payload.get("label", "hotspot")).strip() or "hotspot"
        marker = EntityReference()

        def marked_event() -> DomainEvent:
            marker_id = str(marker.require())
            return HotspotMarkedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(source.id), marker_id),
                    source_id=str(source.id),
                    marker_id=marker_id,
                )
            )

        return planned(
            MutationPlan(
                (
                    AddEntity(
                        (
                            IdentityComponent(name=f"{label} marker", kind="hotspot-marker"),
                            PortableComponent(can_pick_up=True),
                            HotspotMarkerComponent(
                                source_id=str(source.id),
                                marked_by=str(character_id),
                                label=label,
                            ),
                        ),
                        reference=marker,
                    ),
                    AddEdge(character_id, marker, Contains(mode=ContainmentMode.INVENTORY)),
                )
            ),
            marked_event,
            ctx=ctx,
        )


class UseSuppressantHandler:
    command_type = "use-suppressant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        item, error = _reachable_component(
            ctx.world, character_id, command.payload.get("item_id"), SuppressantComponent
        )
        if item is None:
            return rejected(error if error else "target is not a suppressant")
        character = ctx.entity(character_id)
        suppressant = item.get_component(SuppressantComponent)
        pressure = _radiation_pressure(character)
        updated_pressure = max(0.0, pressure.amount - suppressant.pressure_reduction)
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        character_id,
                        replace(pressure, amount=updated_pressure, last_updated_epoch=ctx.epoch),
                    ),
                    SetComponent(
                        item.id,
                        replace(suppressant, uses=max(0, suppressant.uses - 1)),
                    ),
                )
            ),
            SuppressantUsedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    pressure=updated_pressure,
                )
            ),
            ctx=ctx,
        )


class HarvestSampleHandler:
    command_type = "harvest"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        del ctx
        if "sample_type" in command.payload:
            return True
        target_keys = {"creature_id", "soil_id", "target_id"}
        if target_keys.intersection(command.payload):
            return False
        return "product_type" in command.payload or not command.payload

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        sample_type = str(
            command.payload.get("sample_type")
            or command.payload.get("product_type")
            or "irradiated tissue"
        ).strip()
        sample = EntityReference()

        def sample_event() -> DomainEvent:
            sample_id = str(sample.require())
            return SampleHarvestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(sample_id,),
                    sample_id=sample_id,
                    sample_type=sample_type,
                )
            )

        return planned(
            MutationPlan(
                (
                    AddEntity(
                        (
                            IdentityComponent(name=sample_type, kind="sample"),
                            PortableComponent(can_pick_up=True),
                            SampleComponent(sample_type=sample_type),
                        ),
                        reference=sample,
                    ),
                    AddEdge(character_id, sample, Contains(mode=ContainmentMode.INVENTORY)),
                )
            ),
            sample_event,
            ctx=ctx,
        )


class StudySampleHandler:
    command_type = "study-sample"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        sample, error = _reachable_component(
            ctx.world, character_id, command.payload.get("sample_id"), SampleComponent
        )
        if sample is None:
            return rejected(error if error else "target is not a sample")
        component = sample.get_component(SampleComponent)
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        sample.id,
                        replace(
                            component,
                            studied_by=tuple(sorted((*component.studied_by, str(character_id)))),
                        ),
                    ),
                )
            ),
            SampleStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(sample.id),),
                    sample_id=str(sample.id),
                    sample_type=component.sample_type,
                )
            ),
            ctx=ctx,
        )


class UnlockCrateHandler:
    command_type = "unlock"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        if "crate_id" in command.payload:
            return True
        crate_id = _payload_entity_id(command, "crate_id", "target_id")
        return (
            crate_id is not None
            and ctx.world.has_entity(crate_id)
            and ctx.entity(crate_id).has_component(LockedCrateComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        crate, error = _reachable_component(
            ctx.world,
            character_id,
            _payload_entity_id(command, "crate_id", "target_id"),
            LockedCrateComponent,
        )
        if crate is None:
            return rejected(error if error else "target is not a locked crate")
        component = crate.get_component(LockedCrateComponent)
        if not component.locked:
            return rejected("crate is already unlocked")
        return planned(
            MutationPlan((SetComponent(crate.id, replace(component, locked=False)),)),
            CrateUnlockedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(crate.id),),
                    crate_id=str(crate.id),
                )
            ),
            ctx=ctx,
        )


class StudyWastelandArtifactHandler:
    command_type = "study-wasteland-artifact"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        artifact, error = _reachable_component(
            ctx.world, character_id, command.payload.get("artifact_id"), WastelandArtifactComponent
        )
        if artifact is None:
            return rejected(error if error else "target is not a wasteland artifact")
        component = artifact.get_component(WastelandArtifactComponent)
        return planned(
            MutationPlan((SetComponent(artifact.id, replace(component, studied=True)),)),
            WastelandArtifactStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(artifact.id),),
                    artifact_id=str(artifact.id),
                    artifact_type=component.artifact_type,
                )
            ),
            ctx=ctx,
        )


class ClaimFactionSalvageHandler:
    command_type = "claim-faction-salvage"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        salvage, error = _reachable_component(
            ctx.world, character_id, command.payload.get("salvage_id"), FactionSalvageComponent
        )
        if salvage is None:
            return rejected(error if error else "target is not faction salvage")
        component = salvage.get_component(FactionSalvageComponent)
        if component.claimed_by is not None:
            return rejected("faction salvage already claimed")
        return planned(
            MutationPlan(
                (SetComponent(salvage.id, replace(component, claimed_by=str(character_id))),)
            ),
            FactionSalvageClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(salvage.id),),
                    salvage_id=str(salvage.id),
                    faction_id=component.faction_id,
                )
            ),
            ctx=ctx,
        )


class InstallModHandler:
    command_type = "install-mod"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        if character_id is None or item_id is None or not ctx.world.has_entity(item_id):
            return rejected("invalid character or item id")
        character = ctx.entity(character_id)
        if item_id not in reachable_ids(ctx.world, character):
            return rejected("item is not reachable")
        schematic, error = _reachable_component(
            ctx.world, character_id, command.payload.get("schematic_id"), SchematicComponent
        )
        if schematic is None:
            return rejected(error if error else "target is not a schematic")
        component = schematic.get_component(SchematicComponent)
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        item_id,
                        ItemModComponent(mod_name=component.mod_name, installed=True),
                    ),
                )
            ),
            ModInstalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id), str(schematic.id)),
                    item_id=str(item_id),
                    mod_name=component.mod_name,
                )
            ),
            ctx=ctx,
        )


class FieldRepairHandler:
    command_type = "field-repair"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        if character_id is None or item_id is None or not ctx.world.has_entity(item_id):
            return rejected("invalid character or item id")
        item = ctx.entity(item_id)
        if not item.has_component(DurabilityComponent):
            return rejected("target has no durability")
        kit, error = _reachable_component(
            ctx.world, character_id, command.payload.get("kit_id"), FieldRepairComponent
        )
        if kit is None:
            return rejected(error if error else "target is not a repair kit")
        durability = item.get_component(DurabilityComponent)
        repair = kit.get_component(FieldRepairComponent)
        updated = replace(
            durability,
            current=min(durability.maximum, durability.current + repair.repair_amount),
            broken=False,
        )
        return planned(
            MutationPlan((SetComponent(item_id, updated),)),
            FieldRepairAppliedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id), str(kit.id)),
                    item_id=str(item_id),
                    durability=updated.current,
                )
            ),
            ctx=ctx,
        )


class BrewChemHandler:
    command_type = "brew-chem"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        recipe, error = _reachable_component(
            ctx.world, character_id, command.payload.get("recipe_id"), ChemRecipeComponent
        )
        if recipe is None:
            return rejected(error if error else "target is not a chem recipe")
        component = recipe.get_component(ChemRecipeComponent)
        character = ctx.entity(character_id)
        requirements: dict[str, int] = {}
        for resource, quantity in component.resource_inputs:
            requirements[resource] = requirements.get(resource, 0) + quantity
        operations: list[MutationOperation] = []
        for resource, quantity in requirements.items():
            spend_operations = _spend_inventory_resource_operations(
                character,
                ctx.world,
                resource,
                quantity,
            )
            if spend_operations is None:
                return rejected("missing chem ingredients")
            operations.extend(spend_operations)
        chem = EntityReference()
        operations.extend(
            (
                AddEntity(
                    (
                        IdentityComponent(name=component.chem_type, kind="chem"),
                        PortableComponent(can_pick_up=True),
                        ChemComponent(chem_type=component.chem_type),
                    ),
                    reference=chem,
                ),
                AddEdge(character_id, chem, Contains(mode=ContainmentMode.INVENTORY)),
            )
        )

        def brewed_event() -> DomainEvent:
            chem_id = str(chem.require())
            return ChemBrewedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(chem_id,),
                    chem_id=chem_id,
                    chem_type=component.chem_type,
                )
            )

        return planned(
            MutationPlan(tuple(operations)),
            brewed_event,
            ctx=ctx,
        )


class ActivateBeaconHandler:
    command_type = "activate-beacon"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        beacon, error = _reachable_component(
            ctx.world, character_id, command.payload.get("beacon_id"), BeaconComponent
        )
        if beacon is None:
            return rejected(error if error else "target is not a beacon")
        component = beacon.get_component(BeaconComponent)
        return planned(
            MutationPlan((SetComponent(beacon.id, replace(component, active=True)),)),
            BeaconActivatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(beacon.id),),
                    beacon_id=str(beacon.id),
                    message=component.message,
                )
            ),
            ctx=ctx,
        )


class OpenTraderRouteHandler:
    command_type = "open-trader-route"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        route, error = _reachable_component(
            ctx.world, character_id, command.payload.get("route_id"), TraderRouteComponent
        )
        if route is None:
            return rejected(error if error else "target is not a trader route")
        component = route.get_component(TraderRouteComponent)
        return planned(
            MutationPlan((SetComponent(route.id, replace(component, open=True)),)),
            TraderRouteOpenedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(route.id),),
                    route_id=str(route.id),
                    destination=component.destination,
                )
            ),
            ctx=ctx,
        )


class IncreaseRaiderPressureHandler:
    command_type = "increase-raider-pressure"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None or not ctx.world.has_entity(target_id):
            return rejected("invalid character or target id")
        target = ctx.entity(target_id)
        current = (
            target.get_component(RaiderPressureComponent)
            if target.has_component(RaiderPressureComponent)
            else RaiderPressureComponent()
        )
        amount = int(command.payload.get("amount", 1))
        updated = replace(current, pressure=current.pressure + amount)
        return planned(
            MutationPlan((SetComponent(target_id, updated),)),
            RaiderPressureChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    pressure=updated.pressure,
                )
            ),
            ctx=ctx,
        )


class BootTerminalHandler:
    command_type = "boot-terminal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        terminal, error = _reachable_component(
            ctx.world, character_id, command.payload.get("terminal_id"), TerminalComponent
        )
        if terminal is None:
            return rejected(error if error else "target is not a terminal")
        access_level = int(command.payload.get("access_level", 1))
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        terminal.id,
                        replace(
                            terminal.get_component(TerminalComponent),
                            booted=True,
                            access_level=access_level,
                        ),
                    ),
                )
            ),
            TerminalBootedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(terminal.id),),
                    terminal_id=str(terminal.id),
                    access_level=access_level,
                )
            ),
            ctx=ctx,
        )


# --- Old-world tech recovery (catalogue 9.5) ------------------------------------------


@dataclass(frozen=True)
class SettlementComponent(Component):
    name: str
    claimed_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        owner = "unclaimed" if self.claimed_by is None else "claimed"
        return (f"Settlement {_name(ctx.entity)}: {owner}.",)


@dataclass(frozen=True)
class SettlementSalvageComponent(Component):
    outputs: dict[str, int]
    durability_cost: float = 1.0
    depleted: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "depleted" if self.depleted else "available"
        return (f"Settlement salvage {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class WaterPurifierComponent(Component):
    output_per_day: int = 1
    built: bool = False
    scrap_cost: int = 2

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "built" if self.built else f"needs {self.scrap_cost} scrap"
        return (f"Water purifier {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class GeneratorComponent(Component):
    power_output: int = 5
    powered: bool = False
    fuel_cost: int = 1

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "powered" if self.powered else f"needs {self.fuel_cost} fuel"
        return (f"Generator {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class OldWorldTechComponent(Component):
    """A pre-war device that can be identified and then restored to working order."""

    tech_name: str
    identified: bool = False
    functional: bool = False
    restore_scrap: int = 3

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        label = self.tech_name if self.identified else "unknown device"
        if self.functional:
            state = "functional"
        elif self.identified:
            state = f"identified, needs {self.restore_scrap} scrap to restore"
        else:
            state = "unidentified"
        return (f"Old-world tech {_name(ctx.entity)}: {label} ({state}).",)


@dataclass(frozen=True)
class TechLeadComponent(Component):
    """A salvage lead pointing toward a piece of old-world tech."""

    target_tech: str
    location_hint: str = ""

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        hint = f" near {self.location_hint}" if self.location_hint else ""
        return (f"Tech lead: {self.target_tech}{hint}.",)


class OldWorldTechIdentifiedEvent(DomainEvent):
    item_id: str
    tech_name: str


class OldWorldTechRestoredEvent(DomainEvent):
    item_id: str
    tech_name: str
    scrap_spent: int


class SettlementClaimedEvent(DomainEvent):
    settlement_id: str
    name: str


class SettlementSalvagedEvent(DomainEvent):
    settlement_id: str
    output_ids: tuple[str, ...] = ()
    durability: float | None = None


class PurifierBuiltEvent(DomainEvent):
    settlement_id: str
    scrap_spent: int


class GeneratorPoweredEvent(DomainEvent):
    generator_id: str
    fuel_spent: int


class IdentifyTechHandler:
    command_type = "identify"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        if "tech_id" in command.payload:
            return True
        tech_id = _payload_entity_id(command, "tech_id", "target_id")
        return (
            tech_id is not None
            and ctx.world.has_entity(tech_id)
            and ctx.entity(tech_id).has_component(OldWorldTechComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        item, error = _reachable_component(
            ctx.world,
            character_id,
            _payload_entity_id(command, "tech_id", "target_id"),
            OldWorldTechComponent,
        )
        if item is None:
            return rejected(error if error else "target is not old-world tech")
        tech = item.get_component(OldWorldTechComponent)
        if tech.identified:
            return rejected("tech is already identified")
        return planned(
            MutationPlan((SetComponent(item.id, replace(tech, identified=True)),)),
            OldWorldTechIdentifiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    tech_name=tech.tech_name,
                )
            ),
            ctx=ctx,
        )


class RestoreTechHandler:
    command_type = "restore-tech"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        item, error = _reachable_component(
            ctx.world, character_id, command.payload.get("tech_id"), OldWorldTechComponent
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

        spend_operations = _spend_inventory_resource_operations(
            character,
            ctx.world,
            "scrap",
            tech.restore_scrap,
        )
        assert spend_operations is not None
        operations = [
            *spend_operations,
            SetComponent(item.id, replace(tech, functional=True)),
        ]
        return planned(
            MutationPlan(tuple(operations)),
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
            ),
            ctx=ctx,
        )


class ClaimSettlementHandler:
    command_type = "claim"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        target_id = parse_entity_id(command.payload.get("target_id"))
        return (
            target_id is not None
            and ctx.world.has_entity(target_id)
            and ctx.entity(target_id).has_component(SettlementComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        settlement, error = _reachable_component(
            ctx.world, character_id, command.payload.get("target_id"), SettlementComponent
        )
        if settlement is None:
            return rejected(error if error else "target is not a settlement")
        component = settlement.get_component(SettlementComponent)
        if component.claimed_by is not None:
            return rejected("settlement is already claimed")
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        settlement.id,
                        replace(component, claimed_by=str(character_id)),
                    ),
                )
            ),
            SettlementClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(settlement.id),),
                    settlement_id=str(settlement.id),
                    name=component.name,
                )
            ),
            ctx=ctx,
        )


class SalvageSettlementHandler:
    command_type = "salvage-settlement"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        settlement, error = _reachable_component(
            ctx.world, character_id, command.payload.get("settlement_id"), SettlementComponent
        )
        if settlement is None:
            return rejected(error if error else "target is not a settlement")
        component = settlement.get_component(SettlementComponent)
        if component.claimed_by != str(character_id):
            return rejected("claim the settlement first")
        if not settlement.has_component(SettlementSalvageComponent):
            return rejected("settlement has no salvage")
        salvage = settlement.get_component(SettlementSalvageComponent)
        if salvage.depleted:
            return rejected("settlement salvage is depleted")

        durability_value: float | None = None
        operations: list[MutationOperation] = []
        if settlement.has_component(DurabilityComponent):
            durability = settlement.get_component(DurabilityComponent)
            if durability.broken or durability.current <= 0.0:
                return rejected("settlement is too damaged to salvage")
            durability_value = max(0.0, durability.current - salvage.durability_cost)
            operations.append(
                SetComponent(
                    settlement.id,
                    replace(
                        durability,
                        current=durability_value,
                        broken=durability_value <= 0.0,
                    ),
                ),
            )

        character = ctx.entity(character_id)
        outputs: list[EntityId | EntityReference] = []
        for resource_type, quantity in salvage.outputs.items():
            if quantity <= 0:
                continue
            output_operations, output = _add_resource_operations(
                character,
                ctx.world,
                resource_type,
                quantity,
            )
            operations.extend(output_operations)
            outputs.append(output)
        operations.append(SetComponent(settlement.id, replace(salvage, depleted=True)))

        def salvaged_event() -> DomainEvent:
            output_ids = tuple(_entity_target_id(output) for output in outputs)
            return SettlementSalvagedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(settlement.id), *output_ids),
                    settlement_id=str(settlement.id),
                    output_ids=output_ids,
                    durability=durability_value,
                )
            )

        return planned(
            MutationPlan(tuple(operations)),
            salvaged_event,
            ctx=ctx,
        )


class BuildPurifierHandler:
    command_type = "build"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        target_id = parse_entity_id(command.payload.get("target_id"))
        return (
            target_id is not None
            and ctx.world.has_entity(target_id)
            and ctx.entity(target_id).has_component(SettlementComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        settlement, error = _reachable_component(
            ctx.world, character_id, command.payload.get("target_id"), SettlementComponent
        )
        if settlement is None:
            return rejected(error if error else "target is not a settlement")
        settlement_state = settlement.get_component(SettlementComponent)
        if settlement_state.claimed_by != str(character_id):
            return rejected("claim the settlement first")
        purifier = (
            settlement.get_component(WaterPurifierComponent)
            if settlement.has_component(WaterPurifierComponent)
            else WaterPurifierComponent()
        )
        if purifier.built:
            return rejected("purifier is already built")
        character = ctx.entity(character_id)
        spend_operations = _spend_inventory_resource_operations(
            character,
            ctx.world,
            "scrap",
            purifier.scrap_cost,
        )
        if spend_operations is None:
            return rejected("not enough scrap to build purifier")
        return planned(
            MutationPlan(
                (
                    *spend_operations,
                    SetComponent(settlement.id, replace(purifier, built=True)),
                )
            ),
            PurifierBuiltEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(settlement.id),),
                    settlement_id=str(settlement.id),
                    scrap_spent=purifier.scrap_cost,
                )
            ),
            ctx=ctx,
        )


class PowerGeneratorHandler:
    command_type = "power-generator"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        generator, error = _reachable_component(
            ctx.world, character_id, command.payload.get("generator_id"), GeneratorComponent
        )
        if generator is None:
            return rejected(error if error else "target is not a generator")
        component = generator.get_component(GeneratorComponent)
        if component.powered:
            return rejected("generator is already powered")
        character = ctx.entity(character_id)
        spend_operations = _spend_inventory_resource_operations(
            character,
            ctx.world,
            "fuel",
            component.fuel_cost,
        )
        if spend_operations is None:
            return rejected("not enough fuel to power generator")
        return planned(
            MutationPlan(
                (
                    *spend_operations,
                    SetComponent(generator.id, replace(component, powered=True)),
                )
            ),
            GeneratorPoweredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(generator.id),),
                    generator_id=str(generator.id),
                    fuel_spent=component.fuel_cost,
                )
            ),
            ctx=ctx,
        )


def nukesim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    ctx = ComponentPromptContext.for_entity(world, character)
    for component_type in (
        RadiationDoseComponent,
        RadiationSicknessComponent,
        RadiationMutationPressureComponent,
        MutationComponent,
        AddictionComponent,
    ):
        if character.has_component(component_type):
            lines.extend(character.get_component(component_type).prompt_fragments(ctx))

    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        entity_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, room=ctx.room, target=character
        )
        for component_type in (
            ChemComponent,
            WaterPurityComponent,
            RadiationSourceComponent,
            ScavengeSiteComponent,
            DecontaminationComponent,
            RadMedicineComponent,
            SuppressantComponent,
            SampleComponent,
            HotspotMarkerComponent,
            LockedCrateComponent,
            WastelandArtifactComponent,
            FactionSalvageComponent,
            SchematicComponent,
            ItemModComponent,
            FieldRepairComponent,
            ChemRecipeComponent,
            BeaconComponent,
            TraderRouteComponent,
            RaiderPressureComponent,
            TerminalComponent,
            JunkComponent,
            OldWorldTechComponent,
            TechLeadComponent,
            SettlementComponent,
            SettlementSalvageComponent,
            WaterPurifierComponent,
            GeneratorComponent,
        ):
            if entity.has_component(component_type):
                lines.extend(entity.get_component(component_type).prompt_fragments(entity_ctx))
    return sorted(lines)


def install_nukesim(actor) -> None:
    actor.register_consequence(RadiationExposureConsequence())
    actor.register_consequence(MutationResolutionConsequence())
    actor.register_consequence(AddictionWithdrawalConsequence())


__all__ = [
    "AddictionComponent",
    "AddictionWithdrawalConsequence",
    "ActivateBeaconHandler",
    "BeaconActivatedEvent",
    "BeaconComponent",
    "BootTerminalHandler",
    "BrewChemHandler",
    "BuildPurifierHandler",
    "ChemComponent",
    "ChemBrewedEvent",
    "ChemRecipeComponent",
    "ChemTakenEvent",
    "ClaimFactionSalvageHandler",
    "ContaminatedWaterDrunkEvent",
    "ClaimSettlementHandler",
    "CrateUnlockedEvent",
    "DecontaminateHandler",
    "DecontaminationAppliedEvent",
    "DecontaminationComponent",
    "DrinkContaminatedWaterHandler",
    "FactionSalvageClaimedEvent",
    "FactionSalvageComponent",
    "FieldRepairAppliedEvent",
    "FieldRepairComponent",
    "FieldRepairHandler",
    "GeneratorComponent",
    "GeneratorPoweredEvent",
    "HazardTriggeredEvent",
    "HarvestSampleHandler",
    "HotspotMarkedEvent",
    "HotspotMarkerComponent",
    "IdentifyTechHandler",
    "IncreaseRaiderPressureHandler",
    "InstallModHandler",
    "ItemScrappedEvent",
    "ItemModComponent",
    "JunkComponent",
    "LockedCrateComponent",
    "LootFoundEvent",
    "LootTableComponent",
    "OldWorldTechComponent",
    "OldWorldTechIdentifiedEvent",
    "OldWorldTechRestoredEvent",
    "OpenTraderRouteHandler",
    "PowerGeneratorHandler",
    "PurifierBuiltEvent",
    "MutationComponent",
    "MutationManifestedEvent",
    "MutationPressureChangedEvent",
    "MutationResistanceComponent",
    "MutationResolutionConsequence",
    "MutationStabilizedEvent",
    "MutationThresholdComponent",
    "PurifyWaterHandler",
    "RaiderPressureChangedEvent",
    "RaiderPressureComponent",
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
    "SampleComponent",
    "SampleHarvestedEvent",
    "SampleStudiedEvent",
    "ScanRadiationHandler",
    "ScavengeHandler",
    "ScavengeSiteComponent",
    "ScrapItemHandler",
    "SealRadiationSourceHandler",
    "SalvageSettlementHandler",
    "SettlementClaimedEvent",
    "SettlementComponent",
    "SettlementSalvageComponent",
    "SettlementSalvagedEvent",
    "SchematicComponent",
    "SiteScavengedEvent",
    "StabilizeMutationHandler",
    "StudySampleHandler",
    "StudyWastelandArtifactHandler",
    "SuppressantComponent",
    "SuppressantUsedEvent",
    "TakeChemHandler",
    "TerminalBootedEvent",
    "TerminalComponent",
    "TechLeadComponent",
    "TraderRouteComponent",
    "TraderRouteOpenedEvent",
    "UnlockCrateHandler",
    "UseRadMedicineHandler",
    "UseSuppressantHandler",
    "WastelandArtifactComponent",
    "WastelandArtifactStudiedEvent",
    "WaterPurifierComponent",
    "WaterPurifiedEvent",
    "WaterPurityComponent",
    "WithdrawalProgressedEvent",
    "install_nukesim",
    "nukesim_fragments",
]
