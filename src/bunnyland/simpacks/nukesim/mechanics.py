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
    entity_name as _name,
)
from ...core.ecs import (
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ...core.ecs import (
    reachable_component as _reachable_component,
)
from ...core.ecs import (
    remove_from_container as _remove_from_container,
)
from ...core.ecs import (
    room_id_for as _room_id,
)
from ...core.edges import ContainmentMode, Contains
from ...core.events import DomainEvent, EventVisibility, event_base
from ...core.handlers import HandlerContext, HandlerResult, ok, rejected, require_character
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


def _add_resource_stack(character: Entity, world: World, resource_type: str, quantity: int) -> str:
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


def _spend_inventory_resource(
    character: Entity, world: World, resource_type: str, quantity: int
) -> bool:
    stack_entity = _resource_stack_in_inventory(character, world, resource_type)
    have = (
        stack_entity.get_component(ResourceStackComponent).quantity
        if stack_entity is not None
        else 0
    )
    if have < quantity:
        return False
    stack = stack_entity.get_component(ResourceStackComponent)
    remaining = stack.quantity - quantity
    if remaining > 0:
        replace_component(stack_entity, replace(stack, quantity=remaining))
        replace_component(
            stack_entity,
            IdentityComponent(name=_stack_name(resource_type, remaining), kind="resource"),
        )
    else:
        _remove_from_container(world, stack_entity.id)
    return True


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
    pressure_delta = (
        amount * max(0.0, mutation_pressure_per_rad) * max(0.0, resistance.pressure_multiplier)
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
            ctx.world, character_id, command.payload.get("target_id"), RadiationSourceComponent
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
            ctx.world, character_id, command.payload.get("target_id"), RadiationSourceComponent
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
            ctx.world, character_id, command.payload.get("chem_id"), ChemComponent
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
            character.add_component(AddictionComponent(levels=levels, last_updated_epoch=ctx.epoch))
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
            ctx.world, character_id, command.payload.get("water_id"), WaterPurityComponent
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
            ctx.world, character_id, command.payload.get("item_id"), JunkComponent
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
        from ...core.ecs import spawn_entity

        label = str(command.payload.get("label", "hotspot")).strip() or "hotspot"
        marker = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=f"{label} marker", kind="hotspot-marker"),
                PortableComponent(can_pick_up=True),
                HotspotMarkerComponent(
                    source_id=str(source.id),
                    marked_by=str(character_id),
                    label=label,
                ),
            ],
        )
        ctx.entity(character_id).add_relationship(
            Contains(mode=ContainmentMode.INVENTORY), marker.id
        )
        return ok(
            HotspotMarkedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(source.id), str(marker.id)),
                    source_id=str(source.id),
                    marker_id=str(marker.id),
                )
            )
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
        replace_component(
            character,
            replace(pressure, amount=updated_pressure, last_updated_epoch=ctx.epoch),
        )
        replace_component(item, replace(suppressant, uses=max(0, suppressant.uses - 1)))
        return ok(
            SuppressantUsedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    pressure=updated_pressure,
                )
            )
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
        from ...core.ecs import spawn_entity

        sample = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=sample_type, kind="sample"),
                PortableComponent(can_pick_up=True),
                SampleComponent(sample_type=sample_type),
            ],
        )
        ctx.entity(character_id).add_relationship(
            Contains(mode=ContainmentMode.INVENTORY), sample.id
        )
        return ok(
            SampleHarvestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(sample.id),),
                    sample_id=str(sample.id),
                    sample_type=sample_type,
                )
            )
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
        replace_component(
            sample,
            replace(
                component, studied_by=tuple(sorted((*component.studied_by, str(character_id))))
            ),
        )
        return ok(
            SampleStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(sample.id),),
                    sample_id=str(sample.id),
                    sample_type=component.sample_type,
                )
            )
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
        replace_component(crate, replace(component, locked=False))
        return ok(
            CrateUnlockedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(crate.id),),
                    crate_id=str(crate.id),
                )
            )
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
        replace_component(artifact, replace(component, studied=True))
        return ok(
            WastelandArtifactStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(artifact.id),),
                    artifact_id=str(artifact.id),
                    artifact_type=component.artifact_type,
                )
            )
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
        replace_component(salvage, replace(component, claimed_by=str(character_id)))
        return ok(
            FactionSalvageClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(salvage.id),),
                    salvage_id=str(salvage.id),
                    faction_id=component.faction_id,
                )
            )
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
        item = ctx.entity(item_id)
        schematic, error = _reachable_component(
            ctx.world, character_id, command.payload.get("schematic_id"), SchematicComponent
        )
        if schematic is None:
            return rejected(error if error else "target is not a schematic")
        component = schematic.get_component(SchematicComponent)
        replace_component(item, ItemModComponent(mod_name=component.mod_name, installed=True))
        return ok(
            ModInstalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id), str(schematic.id)),
                    item_id=str(item_id),
                    mod_name=component.mod_name,
                )
            )
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
        replace_component(item, updated)
        return ok(
            FieldRepairAppliedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id), str(kit.id)),
                    item_id=str(item_id),
                    durability=updated.current,
                )
            )
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
        for resource, quantity in component.resource_inputs:
            if not _spend_inventory_resource(character, ctx.world, resource, quantity):
                return rejected("missing chem ingredients")
        from ...core.ecs import spawn_entity

        chem = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=component.chem_type, kind="chem"),
                PortableComponent(can_pick_up=True),
                ChemComponent(chem_type=component.chem_type),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), chem.id)
        return ok(
            ChemBrewedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(chem.id),),
                    chem_id=str(chem.id),
                    chem_type=component.chem_type,
                )
            )
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
        replace_component(beacon, replace(component, active=True))
        return ok(
            BeaconActivatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(beacon.id),),
                    beacon_id=str(beacon.id),
                    message=component.message,
                )
            )
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
        replace_component(route, replace(component, open=True))
        return ok(
            TraderRouteOpenedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(route.id),),
                    route_id=str(route.id),
                    destination=component.destination,
                )
            )
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
        replace_component(target, updated)
        return ok(
            RaiderPressureChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    pressure=updated.pressure,
                )
            )
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
        replace_component(
            terminal,
            replace(
                terminal.get_component(TerminalComponent),
                booted=True,
                access_level=access_level,
            ),
        )
        return ok(
            TerminalBootedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(terminal.id),),
                    terminal_id=str(terminal.id),
                    access_level=access_level,
                )
            )
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
        replace_component(settlement, replace(component, claimed_by=str(character_id)))
        return ok(
            SettlementClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(settlement.id),),
                    settlement_id=str(settlement.id),
                    name=component.name,
                )
            )
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
        if settlement.has_component(DurabilityComponent):
            durability = settlement.get_component(DurabilityComponent)
            if durability.broken or durability.current <= 0.0:
                return rejected("settlement is too damaged to salvage")
            durability_value = max(0.0, durability.current - salvage.durability_cost)
            replace_component(
                settlement,
                replace(
                    durability,
                    current=durability_value,
                    broken=durability_value <= 0.0,
                ),
            )

        character = ctx.entity(character_id)
        output_ids = tuple(
            _add_resource_stack(character, ctx.world, resource_type, quantity)
            for resource_type, quantity in salvage.outputs.items()
            if quantity > 0
        )
        replace_component(settlement, replace(salvage, depleted=True))
        return ok(
            SettlementSalvagedEvent(
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
        if not _spend_inventory_resource(character, ctx.world, "scrap", purifier.scrap_cost):
            return rejected("not enough scrap to build purifier")
        replace_component(settlement, replace(purifier, built=True))
        return ok(
            PurifierBuiltEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(settlement.id),),
                    settlement_id=str(settlement.id),
                    scrap_spent=purifier.scrap_cost,
                )
            )
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
        if not _spend_inventory_resource(character, ctx.world, "fuel", component.fuel_cost):
            return rejected("not enough fuel to power generator")
        replace_component(generator, replace(component, powered=True))
        return ok(
            GeneratorPoweredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(generator.id),),
                    generator_id=str(generator.id),
                    fuel_spent=component.fuel_cost,
                )
            )
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
