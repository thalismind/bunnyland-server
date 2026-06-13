"""Garden-sim crop mechanics.

This first slice covers explicit soil preparation, planting, watering, fertilizer, crop
growth, and harvest. It intentionally avoids farm animals, machines, fishing, festivals,
and economy until the basic crop loop is solid.
"""

from __future__ import annotations

from dataclasses import field, replace
from functools import partial

from pydantic.dataclasses import dataclass as pydantic_dataclass
from relics import Component, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import IdentityComponent, PortableComponent
from ..core.ecs import (
    container_of,
    contents,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ..core.ecs import (
    entity_room_id as _entity_room_id,
)
from ..core.ecs import (
    reachable_entity as _safe_reachable_entity,
)
from ..core.ecs import (
    remove_from_container as _remove_from_container,
)
from ..core.ecs import (
    room_id_for as _room_id,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility, event_base
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .colonysim import ResourceStackComponent, _consume_resource_stack
from .consumables import ConsumableComponent, DrinkableComponent, FoodComponent
from .environment import CalendarComponent

SECONDS_PER_DAY = 24 * 60 * 60


@pydantic_dataclass(frozen=True)
class SoilComponent(Component):
    quality: float = 1.0


@pydantic_dataclass(frozen=True)
class TilledComponent(Component):
    tilled_at_epoch: int


@pydantic_dataclass(frozen=True)
class WateredComponent(Component):
    watered_at_epoch: int
    expires_at_epoch: int


@pydantic_dataclass(frozen=True)
class FertilizerComponent(Component):
    kind: str = "basic"
    growth_multiplier: float = 1.0
    quality_bonus: float = 0.0


@pydantic_dataclass(frozen=True)
class SeedComponent(Component):
    crop_type: str
    growth_days: float
    yield_item: str
    yield_quantity: int = 1
    seasons: tuple[str, ...] = ("spring", "summer", "autumn")
    stage_count: int = 3
    edible_nutrition: float = 0.0
    edible_satiety: float = 0.0


@pydantic_dataclass(frozen=True)
class CropComponent(Component):
    crop_type: str
    planted_at_epoch: int
    stage: int = 0
    ready: bool = False
    dead: bool = False
    seasons: tuple[str, ...] = ("spring", "summer", "autumn")


@pydantic_dataclass(frozen=True)
class CropGrowthComponent(Component):
    progress_days: float
    required_days: float
    last_updated_epoch: int
    stage_count: int = 3


@pydantic_dataclass(frozen=True)
class HarvestableComponent(Component):
    yield_item: str
    quantity: int = 1
    ready: bool = False
    edible_nutrition: float = 0.0
    edible_satiety: float = 0.0


@pydantic_dataclass(frozen=True)
class CropQualityComponent(Component):
    quality: float = 1.0


@pydantic_dataclass(frozen=True)
class RegrowableComponent(Component):
    regrow_days: float
    regrowth_count: int = 0


@pydantic_dataclass(frozen=True)
class PestComponent(Component):
    severity: float = 1.0


@pydantic_dataclass(frozen=True)
class WeedComponent(Component):
    density: float = 1.0


@pydantic_dataclass(frozen=True)
class CropInspectionComponent(Component):
    inspected_at_epoch: int
    notes: str = ""


@pydantic_dataclass(frozen=True)
class MachineComponent(Component):
    machine_type: str
    busy: bool = False
    quality: float = 1.0


@pydantic_dataclass(frozen=True)
class MachineBreakdownComponent(Component):
    reason: str = "wear"
    repaired_at_epoch: int | None = None


@pydantic_dataclass(frozen=True)
class ProcessingRecipeComponent(Component):
    recipe_id: str
    machine_type: str
    inputs: dict[str, int]
    outputs: dict[str, int]
    duration_seconds: int
    output_entities: dict[str, dict[str, object]] = field(default_factory=dict)


@pydantic_dataclass(frozen=True)
class ProcessingTaskComponent(Component):
    recipe_id: str
    started_at_epoch: int
    ready_at_epoch: int
    ready: bool = False


@pydantic_dataclass(frozen=True)
class AnimalHomeComponent(Component):
    capacity: int = 4
    feed_type: str = "hay"


@pydantic_dataclass(frozen=True)
class FarmAnimalComponent(Component):
    species: str
    age_days: float = 0.0
    adult_age_days: float = 3.0
    friendship: float = 0.0
    mood: float = 50.0
    fed_until_epoch: int = 0
    last_petted_epoch: int | None = None
    sick: bool = False


@pydantic_dataclass(frozen=True)
class AnimalProductComponent(Component):
    product_type: str
    quantity: int = 1
    interval_seconds: int = SECONDS_PER_DAY
    last_produced_epoch: int = 0
    ready: bool = False
    quality: float = 1.0


@pydantic_dataclass(frozen=True)
class AnimalBreedingComponent(Component):
    mate_id: str | None = None
    due_epoch: int | None = None
    offspring_species: str = ""


@pydantic_dataclass(frozen=True)
class FishingSpotComponent(Component):
    fish_type: str
    quantity: int = 1
    season: str | None = None
    required_bait: str | None = None


@pydantic_dataclass(frozen=True)
class MiningNodeComponent(Component):
    resource_type: str
    quantity: int = 1
    hardness: int = 1


@pydantic_dataclass(frozen=True)
class MineLevelComponent(Component):
    level: int = 1


@pydantic_dataclass(frozen=True)
class LadderComponent(Component):
    target_room_id: str
    discovered: bool = False


@pydantic_dataclass(frozen=True)
class GeodeComponent(Component):
    resource_type: str = "gem"
    quantity: int = 1


@pydantic_dataclass(frozen=True)
class ForageComponent(Component):
    resource_type: str
    quantity: int = 1
    seasons: tuple[str, ...] = ()


@pydantic_dataclass(frozen=True)
class GiftPreferenceComponent(Component):
    likes: tuple[str, ...] = ()
    loves: tuple[str, ...] = ()
    dislikes: tuple[str, ...] = ()


@pydantic_dataclass(frozen=True)
class FriendshipComponent(Component):
    points: float = 0.0


@pydantic_dataclass(frozen=True)
class FestivalComponent(Component):
    name: str
    season: str
    day: int = 1
    joined_character_ids: tuple[str, ...] = ()


@pydantic_dataclass(frozen=True)
class BundleComponent(Component):
    bundle_id: str
    requirements: dict[str, int]
    contributed: dict[str, int] = field(default_factory=dict)
    completed: bool = False


@pydantic_dataclass(frozen=True)
class MailComponent(Component):
    subject: str
    body: str = ""
    claimed: bool = False
    reward_resource: str | None = None
    reward_quantity: int = 0


@pydantic_dataclass(frozen=True)
class FarmQuestComponent(Component):
    quest_id: str
    requested: dict[str, int]
    reward_resource: str | None = None
    reward_quantity: int = 0
    completed: bool = False


@pydantic_dataclass(frozen=True)
class ShippingBinComponent(Component):
    shipped: dict[str, int] = field(default_factory=dict)
    earnings: int = 0


@pydantic_dataclass(frozen=True)
class CollectionComponent(Component):
    entries: tuple[str, ...] = ()


@pydantic_dataclass(frozen=True)
class MuseumCollectionComponent(Component):
    donated: tuple[str, ...] = ()


@pydantic_dataclass(frozen=True)
class RewardComponent(Component):
    resource_type: str
    quantity: int = 1
    claimed: bool = False


@pydantic_dataclass(frozen=True)
class DailyFarmResetComponent(Component):
    last_reset_epoch: int = 0


@pydantic_dataclass(frozen=True)
class GreenhouseComponent(Component):
    enabled: bool = True


@pydantic_dataclass(frozen=True)
class TreeComponent(Component):
    tree_type: str
    planted_at_epoch: int
    maturity_days: float
    mature: bool = False
    dead: bool = False


@pydantic_dataclass(frozen=True)
class TreeTapComponent(Component):
    tapped_at_epoch: int
    last_collected_epoch: int
    collection_days: float = 1.0


class SoilTilledEvent(DomainEvent):
    soil_id: str


class SeedPlantedEvent(DomainEvent):
    soil_id: str
    seed_id: str
    crop_type: str


class CropWateredEvent(DomainEvent):
    soil_id: str
    expires_at_epoch: int


class FertilizerAppliedEvent(DomainEvent):
    soil_id: str
    fertilizer_id: str
    kind: str


class CropGrewEvent(DomainEvent):
    soil_id: str
    crop_type: str
    stage: int
    progress_days: float


class CropReadyEvent(DomainEvent):
    soil_id: str
    crop_type: str


class CropWitheredEvent(DomainEvent):
    soil_id: str
    crop_type: str
    season: str


class CropHarvestedEvent(DomainEvent):
    soil_id: str
    crop_type: str
    item_id: str
    quantity: int


class CropInspectedEvent(DomainEvent):
    soil_id: str
    notes: str


class CropWeededEvent(DomainEvent):
    soil_id: str


class CropPestsTreatedEvent(DomainEvent):
    soil_id: str


class DeadCropClearedEvent(DomainEvent):
    soil_id: str
    crop_type: str


class TreeMaturedEvent(DomainEvent):
    tree_id: str
    tree_type: str


class TreeTappedEvent(DomainEvent):
    tree_id: str
    tree_type: str


class SapReadyEvent(DomainEvent):
    tree_id: str
    tree_type: str


class SapHarvestedEvent(DomainEvent):
    tree_id: str
    tree_type: str
    item_id: str
    quantity: int


class MachineProcessingStartedEvent(DomainEvent):
    machine_id: str
    recipe_id: str
    ready_at_epoch: int


class MachineProcessingReadyEvent(DomainEvent):
    machine_id: str
    recipe_id: str


class MachineOutputCollectedEvent(DomainEvent):
    machine_id: str
    recipe_id: str
    output_ids: tuple[str, ...]


class MachineProcessingCancelledEvent(DomainEvent):
    machine_id: str
    recipe_id: str


class MachineRepairedEvent(DomainEvent):
    machine_id: str


class MachineBrokeDownEvent(DomainEvent):
    machine_id: str
    reason: str


class AnimalFedEvent(DomainEvent):
    animal_id: str
    feed_type: str


class AnimalPettedEvent(DomainEvent):
    animal_id: str
    friendship: float


class AnimalProductReadyEvent(DomainEvent):
    animal_id: str
    product_type: str


class AnimalProductCollectedEvent(DomainEvent):
    animal_id: str
    product_type: str
    item_id: str
    quantity: int


class AnimalBredEvent(DomainEvent):
    animal_id: str
    mate_id: str
    due_epoch: int


class AnimalBornEvent(DomainEvent):
    animal_id: str
    offspring_id: str


class FishCaughtEvent(DomainEvent):
    spot_id: str
    item_id: str
    fish_type: str
    quantity: int


class MiningNodeMinedEvent(DomainEvent):
    node_id: str
    item_id: str
    resource_type: str
    quantity: int


class LadderDiscoveredEvent(DomainEvent):
    ladder_id: str
    target_room_id: str


class GeodeOpenedEvent(DomainEvent):
    geode_id: str
    item_id: str
    resource_type: str
    quantity: int


class ForageCollectedEvent(DomainEvent):
    forage_id: str
    item_id: str
    resource_type: str
    quantity: int


class GiftGivenEvent(DomainEvent):
    target_id: str
    item_id: str
    friendship: float


class FestivalJoinedEvent(DomainEvent):
    festival_id: str
    name: str


class BundleContributedEvent(DomainEvent):
    bundle_id: str
    resource_type: str
    quantity: int
    completed: bool


class MailClaimedEvent(DomainEvent):
    mail_id: str
    subject: str


class FarmQuestCompletedEvent(DomainEvent):
    quest_id: str
    reward_item_id: str | None = None


class ItemsShippedEvent(DomainEvent):
    bin_id: str
    resource_type: str
    quantity: int
    earnings: int


class CollectionUpdatedEvent(DomainEvent):
    entry: str


class MuseumDonatedEvent(DomainEvent):
    museum_id: str
    resource_type: str


class RewardClaimedEvent(DomainEvent):
    reward_id: str
    item_id: str


class DailyFarmResetEvent(DomainEvent):
    reset_epoch: int


_event_base = partial(event_base, default_visibility=EventVisibility.ROOM)


def _reachable_entity(ctx: HandlerContext, character_id: EntityId, target_id: EntityId):
    return _safe_reachable_entity(ctx.world, character_id, target_id)


def _spawn_harvest_item(
    world: World,
    character: Entity,
    crop_type: str,
    item_name: str,
    quantity: int,
    *,
    edible_nutrition: float = 0.0,
    edible_satiety: float = 0.0,
) -> str:
    label = f"{item_name} x{quantity}" if quantity != 1 else item_name
    components: list[Component] = [
        IdentityComponent(name=label, kind="crop", tags=(crop_type,)),
        PortableComponent(can_pick_up=True),
        ResourceStackComponent(resource_type=item_name, quantity=quantity),
    ]
    if edible_satiety > 0 or edible_nutrition > 0:
        components.extend(
            [
                FoodComponent(nutrition=edible_nutrition, satiety=edible_satiety),
                ConsumableComponent(current_uses=quantity, max_uses=quantity),
            ]
        )
    item = spawn_entity(
        world,
        components,
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _spawn_product_item(
    world: World,
    character: Entity,
    resource_type: str,
    quantity: int,
    *,
    kind: str = "resource",
    metadata: dict[str, object] | None = None,
) -> str:
    metadata = metadata or {}
    name = str(metadata.get("display_name") or _resource_name(resource_type, quantity))
    components: list[Component] = [
        IdentityComponent(name=name, kind=kind, tags=(resource_type,)),
        ResourceStackComponent(resource_type=resource_type, quantity=quantity),
        PortableComponent(can_pick_up=True),
    ]
    if "satiety" in metadata or "nutrition" in metadata:
        components.append(
            FoodComponent(
                nutrition=float(metadata.get("nutrition", 0.0)),
                satiety=float(metadata.get("satiety", 0.0)),
                raw=bool(metadata.get("raw", False)),
                spoiled=bool(metadata.get("spoiled", False)),
            )
        )
    if "hydration" in metadata:
        components.append(
            DrinkableComponent(
                hydration=float(metadata.get("hydration", 0.0)),
                purity=float(metadata.get("purity", 1.0)),
            )
        )
    uses = int(metadata.get("uses", quantity if len(components) > 3 else 0))
    if uses > 0:
        components.append(ConsumableComponent(current_uses=uses, max_uses=uses))
    item = spawn_entity(world, components)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _resource_name(resource_type: str, quantity: int) -> str:
    return f"{resource_type} x{quantity}" if quantity != 1 else resource_type


def _find_processing_recipe(
    world: World, recipe_id: str, machine_type: str
) -> ProcessingRecipeComponent | None:
    for entity in world.query().with_all([ProcessingRecipeComponent]).execute_entities():
        recipe = entity.get_component(ProcessingRecipeComponent)
        if recipe.recipe_id == recipe_id and recipe.machine_type == machine_type:
            return recipe
    return None


def _spawn_sap_item(
    world: World, character: Entity, tree_type: str, item_name: str, quantity: int
) -> str:
    label = f"{item_name} x{quantity}" if quantity != 1 else item_name
    item = spawn_entity(
        world,
        [
            IdentityComponent(name=label, kind="resource", tags=(tree_type,)),
            PortableComponent(can_pick_up=True),
            ResourceStackComponent(resource_type=item_name, quantity=quantity),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _current_season(world: World) -> str | None:
    clocks = list(world.query().with_all([CalendarComponent]).execute_entities())
    if not clocks:
        return None
    return clocks[0].get_component(CalendarComponent).season


def _record_collection(world: World, character: Entity, entry: str) -> bool:
    existing = (
        character.get_component(CollectionComponent)
        if character.has_component(CollectionComponent)
        else CollectionComponent()
    )
    if entry in existing.entries:
        return False
    replace_component(
        character,
        CollectionComponent(entries=tuple(sorted({*existing.entries, entry}))),
    )
    return True


class CropGrowthConsequence:
    """Grow watered crops and wither crops that are out of season."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        season = _current_season(world)
        query = world.query().with_all([CropComponent, CropGrowthComponent])
        for soil in list(query.execute_entities()):
            crop = soil.get_component(CropComponent)
            growth = soil.get_component(CropGrowthComponent)
            if crop.dead or crop.ready:
                continue
            if season is not None and crop.seasons and season not in crop.seasons:
                replace_component(soil, replace(crop, dead=True, ready=False))
                if soil.has_component(HarvestableComponent):
                    soil.remove_component(HarvestableComponent)
                events.append(
                    CropWitheredEvent(
                        **_event_base(
                            epoch,
                            room_id=_entity_room_id(soil),
                            target_ids=(str(soil.id),),
                            soil_id=str(soil.id),
                            crop_type=crop.crop_type,
                            season=season,
                        )
                    )
                )
                continue

            if not soil.has_component(WateredComponent):
                if growth.last_updated_epoch != epoch:
                    replace_component(soil, replace(growth, last_updated_epoch=epoch))
                continue

            watered = soil.get_component(WateredComponent)
            growth_until = min(epoch, watered.expires_at_epoch)
            delta_days = max(0.0, (growth_until - growth.last_updated_epoch) / SECONDS_PER_DAY)
            fertilizer = (
                soil.get_component(FertilizerComponent)
                if soil.has_component(FertilizerComponent)
                else FertilizerComponent()
            )
            progress = growth.progress_days + delta_days * fertilizer.growth_multiplier
            stage = min(
                growth.stage_count,
                int((progress / growth.required_days) * growth.stage_count),
            )
            ready = progress >= growth.required_days
            updated_crop = replace(crop, stage=max(crop.stage, stage), ready=ready)
            updated_growth = replace(
                growth,
                progress_days=min(progress, growth.required_days),
                last_updated_epoch=epoch,
            )
            replace_component(soil, updated_crop)
            replace_component(soil, updated_growth)

            if soil.has_component(HarvestableComponent):
                harvestable = soil.get_component(HarvestableComponent)
                replace_component(soil, replace(harvestable, ready=ready))

            if updated_crop.stage != crop.stage:
                events.append(
                    CropGrewEvent(
                        **_event_base(
                            epoch,
                            room_id=_entity_room_id(soil),
                            target_ids=(str(soil.id),),
                            soil_id=str(soil.id),
                            crop_type=crop.crop_type,
                            stage=updated_crop.stage,
                            progress_days=round(updated_growth.progress_days, 3),
                        )
                    )
                )
            if ready and not crop.ready:
                events.append(
                    CropReadyEvent(
                        **_event_base(
                            epoch,
                            room_id=_entity_room_id(soil),
                            target_ids=(str(soil.id),),
                            soil_id=str(soil.id),
                            crop_type=crop.crop_type,
                        )
                    )
                )
            if watered.expires_at_epoch <= epoch:
                soil.remove_component(WateredComponent)
        return events


class TreeGrowthConsequence:
    """Mature trees over time and mark tapped trees ready to harvest sap."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all([TreeComponent])
        for tree in list(query.execute_entities()):
            component = tree.get_component(TreeComponent)
            if component.dead:
                continue
            mature = component.mature
            if not mature:
                elapsed_days = (epoch - component.planted_at_epoch) / SECONDS_PER_DAY
                mature = elapsed_days >= component.maturity_days
                if mature:
                    replace_component(tree, replace(component, mature=True))
                    events.append(
                        TreeMaturedEvent(
                            **_event_base(
                                epoch,
                                room_id=_entity_room_id(tree),
                                target_ids=(str(tree.id),),
                                tree_id=str(tree.id),
                                tree_type=component.tree_type,
                            )
                        )
                    )
            if not mature or not tree.has_component(TreeTapComponent):
                continue
            if not tree.has_component(HarvestableComponent):
                continue
            tap = tree.get_component(TreeTapComponent)
            harvestable = tree.get_component(HarvestableComponent)
            if harvestable.ready:
                continue
            elapsed_days = (epoch - tap.last_collected_epoch) / SECONDS_PER_DAY
            if elapsed_days < tap.collection_days:
                continue
            replace_component(tree, replace(harvestable, ready=True))
            events.append(
                SapReadyEvent(
                    **_event_base(
                        epoch,
                        room_id=_entity_room_id(tree),
                        target_ids=(str(tree.id),),
                        tree_id=str(tree.id),
                        tree_type=component.tree_type,
                    )
                )
            )
        return events


class MachineProcessingConsequence:
    """Mark processing machines ready after their recipe duration has elapsed."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for machine in (
            world.query()
            .with_all([MachineComponent, ProcessingTaskComponent])
            .execute_entities()
        ):
            task = machine.get_component(ProcessingTaskComponent)
            if task.ready or epoch < task.ready_at_epoch:
                continue
            replace_component(machine, replace(task, ready=True))
            events.append(
                MachineProcessingReadyEvent(
                    **_event_base(
                        epoch,
                        room_id=_entity_room_id(machine),
                        target_ids=(str(machine.id),),
                        machine_id=str(machine.id),
                        recipe_id=task.recipe_id,
                    )
                )
            )
        return events


class AnimalProductConsequence:
    """Advance animal age/mood and mark animal products ready on their interval."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for animal in world.query().with_all([FarmAnimalComponent]).execute_entities():
            component = animal.get_component(FarmAnimalComponent)
            fed = epoch <= component.fed_until_epoch
            mood_delta = 2.0 if fed else -4.0
            updated_animal = replace(
                component,
                age_days=max(component.age_days, epoch / SECONDS_PER_DAY),
                mood=max(0.0, min(100.0, component.mood + mood_delta)),
            )
            if updated_animal != component:
                replace_component(animal, updated_animal)
            if not animal.has_component(AnimalProductComponent):
                continue
            product = animal.get_component(AnimalProductComponent)
            if product.ready or updated_animal.sick:
                continue
            if updated_animal.age_days < updated_animal.adult_age_days:
                continue
            if epoch - product.last_produced_epoch < product.interval_seconds:
                continue
            quality = 1.0 + (updated_animal.friendship / 100.0) + (updated_animal.mood / 200.0)
            updated_product = replace(product, ready=True, quality=round(quality, 3))
            replace_component(animal, updated_product)
            events.append(
                AnimalProductReadyEvent(
                    **_event_base(
                        epoch,
                        room_id=_entity_room_id(animal),
                        target_ids=(str(animal.id),),
                        animal_id=str(animal.id),
                        product_type=product.product_type,
                    )
                )
            )
        return events


class AnimalBirthConsequence:
    """Create offspring for bred farm animals once gestation is due."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for animal in (
            world.query()
            .with_all([FarmAnimalComponent, AnimalBreedingComponent])
            .execute_entities()
        ):
            breeding = animal.get_component(AnimalBreedingComponent)
            if breeding.due_epoch is None or epoch < breeding.due_epoch:
                continue
            species = (
                breeding.offspring_species
                or animal.get_component(FarmAnimalComponent).species
            )
            offspring = spawn_entity(
                world,
                [
                    IdentityComponent(name=f"baby {species}", kind="farm_animal"),
                    FarmAnimalComponent(species=species, age_days=0.0),
                ],
            )
            room_id = container_of(animal)
            if room_id is not None:
                world.get_entity(room_id).add_relationship(
                    Contains(mode=ContainmentMode.ROOM_CONTENT), offspring.id
                )
            animal.remove_component(AnimalBreedingComponent)
            events.append(
                AnimalBornEvent(
                    **_event_base(
                        epoch,
                        room_id=str(room_id) if room_id is not None else None,
                        target_ids=(str(animal.id), str(offspring.id)),
                        animal_id=str(animal.id),
                        offspring_id=str(offspring.id),
                    )
                )
            )
        return events


class MachineBreakdownConsequence:
    """Mark worn-out machines as broken so repair is explicit ECS state."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for machine in world.query().with_all([MachineComponent]).execute_entities():
            component = machine.get_component(MachineComponent)
            if component.quality > 0.2 or machine.has_component(MachineBreakdownComponent):
                continue
            replace_component(machine, MachineBreakdownComponent(reason="low quality"))
            events.append(
                MachineBrokeDownEvent(
                    **_event_base(
                        epoch,
                        room_id=_entity_room_id(machine),
                        target_ids=(str(machine.id),),
                        machine_id=str(machine.id),
                        reason="low quality",
                    )
                )
            )
        return events


class DailyFarmResetConsequence:
    """Reset daily farm affordances such as forage after a full in-game day."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for state in world.query().with_all([DailyFarmResetComponent]).execute_entities():
            reset = state.get_component(DailyFarmResetComponent)
            if epoch - reset.last_reset_epoch < SECONDS_PER_DAY:
                continue
            replace_component(state, replace(reset, last_reset_epoch=epoch))
            for animal in world.query().with_all([FarmAnimalComponent]).execute_entities():
                component = animal.get_component(FarmAnimalComponent)
                replace_component(animal, replace(component, last_petted_epoch=None))
            events.append(
                DailyFarmResetEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.SYSTEM,
                        reset_epoch=epoch,
                    )
                )
            )
        return events


class TillHandler:
    command_type = "till"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(SoilComponent):
            return rejected("target is not soil")
        if soil.has_component(TilledComponent):
            return rejected("soil is already tilled")

        soil.add_component(TilledComponent(tilled_at_epoch=ctx.epoch))
        return ok(
            SoilTilledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                )
            )
        )


class PlantHandler:
    command_type = "plant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        seed_id = parse_entity_id(command.payload.get("seed_id"))
        if character_id is None or soil_id is None or seed_id is None:
            return rejected("invalid character, soil, or seed id")
        if not ctx.world.has_entity(soil_id) or not ctx.world.has_entity(seed_id):
            return rejected("soil or seed does not exist")

        soil = _reachable_entity(ctx, character_id, soil_id)
        seed_entity = _reachable_entity(ctx, character_id, seed_id)
        if soil is None or seed_entity is None:
            return rejected("soil or seed is not reachable")
        if not soil.has_component(SoilComponent) or not soil.has_component(TilledComponent):
            return rejected("soil is not prepared")
        if soil.has_component(CropComponent):
            return rejected("soil already has a crop")
        if not seed_entity.has_component(SeedComponent):
            return rejected("target seed is not plantable")

        seed = seed_entity.get_component(SeedComponent)
        season = _current_season(ctx.world)
        if (
            season is not None
            and seed.seasons
            and season not in seed.seasons
            and not soil.has_component(GreenhouseComponent)
        ):
            return rejected("seed cannot grow in this season")
        soil.add_component(
            CropComponent(
                crop_type=seed.crop_type,
                planted_at_epoch=ctx.epoch,
                seasons=seed.seasons,
            )
        )
        soil.add_component(
            CropGrowthComponent(
                progress_days=0.0,
                required_days=seed.growth_days,
                last_updated_epoch=ctx.epoch,
                stage_count=seed.stage_count,
            )
        )
        soil.add_component(
            HarvestableComponent(
                yield_item=seed.yield_item,
                quantity=seed.yield_quantity,
                ready=False,
                edible_nutrition=seed.edible_nutrition,
                edible_satiety=seed.edible_satiety,
            )
        )
        _remove_from_container(ctx.world, seed_id)
        return ok(
            SeedPlantedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id), str(seed_id)),
                    soil_id=str(soil_id),
                    seed_id=str(seed_id),
                    crop_type=seed.crop_type,
                )
            )
        )


class WaterCropHandler:
    command_type = "water-crop"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(SoilComponent):
            return rejected("target is not soil")

        expires_at = ctx.epoch + SECONDS_PER_DAY
        replace_component(
            soil,
            WateredComponent(watered_at_epoch=ctx.epoch, expires_at_epoch=expires_at),
        )
        if soil.has_component(CropGrowthComponent):
            growth = soil.get_component(CropGrowthComponent)
            replace_component(soil, replace(growth, last_updated_epoch=ctx.epoch))
        return ok(
            CropWateredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                    expires_at_epoch=expires_at,
                )
            )
        )


class FertilizeHandler:
    command_type = "fertilize"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        fertilizer_id = parse_entity_id(command.payload.get("fertilizer_id"))
        if character_id is None or soil_id is None or fertilizer_id is None:
            return rejected("invalid character, soil, or fertilizer id")
        if not ctx.world.has_entity(soil_id) or not ctx.world.has_entity(fertilizer_id):
            return rejected("soil or fertilizer does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        fertilizer_entity = _reachable_entity(ctx, character_id, fertilizer_id)
        if soil is None or fertilizer_entity is None:
            return rejected("soil or fertilizer is not reachable")
        if not soil.has_component(SoilComponent):
            return rejected("target is not soil")
        if not fertilizer_entity.has_component(FertilizerComponent):
            return rejected("target fertilizer is not usable")

        fertilizer = fertilizer_entity.get_component(FertilizerComponent)
        replace_component(soil, fertilizer)
        _remove_from_container(ctx.world, fertilizer_id)
        return ok(
            FertilizerAppliedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id), str(fertilizer_id)),
                    soil_id=str(soil_id),
                    fertilizer_id=str(fertilizer_id),
                    kind=fertilizer.kind,
                )
            )
        )


class InspectCropHandler:
    command_type = "inspect-crop"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(CropComponent):
            return rejected("soil has no crop")
        crop = soil.get_component(CropComponent)
        notes = f"{crop.crop_type} stage {crop.stage}"
        if soil.has_component(PestComponent):
            notes += ", pests present"
        if soil.has_component(WeedComponent):
            notes += ", weeds present"
        replace_component(soil, CropInspectionComponent(inspected_at_epoch=ctx.epoch, notes=notes))
        return ok(
            CropInspectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                    notes=notes,
                )
            )
        )


class WeedCropHandler:
    command_type = "weed-crop"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(WeedComponent):
            return rejected("soil has no weeds")
        soil.remove_component(WeedComponent)
        if soil.has_component(CropQualityComponent):
            quality = soil.get_component(CropQualityComponent)
            replace_component(soil, replace(quality, quality=min(2.0, quality.quality + 0.1)))
        return ok(
            CropWeededEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                )
            )
        )


class TreatPestsHandler:
    command_type = "treat-pests"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(PestComponent):
            return rejected("soil has no pests")
        soil.remove_component(PestComponent)
        if soil.has_component(CropQualityComponent):
            quality = soil.get_component(CropQualityComponent)
            replace_component(soil, replace(quality, quality=min(2.0, quality.quality + 0.15)))
        return ok(
            CropPestsTreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                )
            )
        )


class HarvestCropHandler:
    command_type = "harvest-crop"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        character = ctx.entity(character_id)
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(CropComponent) or not soil.has_component(HarvestableComponent):
            return rejected("soil has no harvestable crop")

        crop = soil.get_component(CropComponent)
        harvestable = soil.get_component(HarvestableComponent)
        if crop.dead:
            return rejected("crop is dead")
        if not crop.ready or not harvestable.ready:
            return rejected("crop is not ready")

        quality = (
            soil.get_component(CropQualityComponent).quality
            if soil.has_component(CropQualityComponent)
            else 1.0
        )
        quantity = max(1, int(round(harvestable.quantity * quality)))
        item_id = _spawn_harvest_item(
            ctx.world,
            character,
            crop.crop_type,
            harvestable.yield_item,
            quantity,
            edible_nutrition=harvestable.edible_nutrition,
            edible_satiety=harvestable.edible_satiety,
        )
        if soil.has_component(RegrowableComponent):
            regrow = soil.get_component(RegrowableComponent)
            replace_component(
                soil,
                replace(crop, ready=False, stage=0, planted_at_epoch=ctx.epoch),
            )
            replace_component(
                soil,
                CropGrowthComponent(
                    progress_days=0.0,
                    required_days=regrow.regrow_days,
                    last_updated_epoch=ctx.epoch,
                    stage_count=3,
                ),
            )
            replace_component(soil, replace(harvestable, ready=False))
            replace_component(soil, replace(regrow, regrowth_count=regrow.regrowth_count + 1))
        else:
            soil.remove_component(CropComponent)
            soil.remove_component(CropGrowthComponent)
            soil.remove_component(HarvestableComponent)
        if soil.has_component(WateredComponent):
            soil.remove_component(WateredComponent)
        return ok(
            CropHarvestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id), item_id),
                    soil_id=str(soil_id),
                    crop_type=crop.crop_type,
                    item_id=item_id,
                    quantity=quantity,
                )
            )
        )


class ClearDeadCropHandler:
    command_type = "clear-dead-crop"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(CropComponent):
            return rejected("soil has no crop")
        crop = soil.get_component(CropComponent)
        if not crop.dead:
            return rejected("crop is not dead")

        soil.remove_component(CropComponent)
        if soil.has_component(CropGrowthComponent):
            soil.remove_component(CropGrowthComponent)
        if soil.has_component(HarvestableComponent):
            soil.remove_component(HarvestableComponent)
        if soil.has_component(WateredComponent):
            soil.remove_component(WateredComponent)
        return ok(
            DeadCropClearedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                    crop_type=crop.crop_type,
                )
            )
        )


class TapTreeHandler:
    command_type = "tap-tree"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        tree_id = parse_entity_id(command.payload.get("tree_id"))
        if character_id is None or tree_id is None:
            return rejected("invalid character or tree id")
        if not ctx.world.has_entity(tree_id):
            return rejected("tree does not exist")
        tree = _reachable_entity(ctx, character_id, tree_id)
        if tree is None:
            return rejected("tree is not reachable")
        if not tree.has_component(TreeComponent):
            return rejected("target is not a tree")
        component = tree.get_component(TreeComponent)
        if component.dead:
            return rejected("tree is dead")
        if not component.mature:
            return rejected("tree is not ready to tap")
        if tree.has_component(TreeTapComponent):
            return rejected("tree is already tapped")

        tree.add_component(
            TreeTapComponent(tapped_at_epoch=ctx.epoch, last_collected_epoch=ctx.epoch)
        )
        tree.add_component(HarvestableComponent(yield_item="maple sap", quantity=4))
        return ok(
            TreeTappedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(tree_id),),
                    tree_id=str(tree_id),
                    tree_type=component.tree_type,
                )
            )
        )


class HarvestSapHandler:
    command_type = "harvest-sap"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        tree_id = parse_entity_id(command.payload.get("tree_id"))
        if character_id is None or tree_id is None:
            return rejected("invalid character or tree id")
        if not ctx.world.has_entity(tree_id):
            return rejected("tree does not exist")
        character = ctx.entity(character_id)
        tree = _reachable_entity(ctx, character_id, tree_id)
        if tree is None:
            return rejected("tree is not reachable")
        if not tree.has_component(TreeComponent):
            return rejected("target is not a tree")
        component = tree.get_component(TreeComponent)
        if component.dead:
            return rejected("tree is dead")
        if not tree.has_component(TreeTapComponent):
            return rejected("tree is not tapped")
        if not tree.has_component(HarvestableComponent):
            return rejected("tree has no sap bucket")
        harvestable = tree.get_component(HarvestableComponent)
        if not harvestable.ready:
            return rejected("sap is not ready")

        item_id = _spawn_sap_item(
            ctx.world,
            character,
            component.tree_type,
            harvestable.yield_item,
            harvestable.quantity,
        )
        tap = tree.get_component(TreeTapComponent)
        replace_component(tree, replace(tap, last_collected_epoch=ctx.epoch))
        replace_component(tree, replace(harvestable, ready=False))
        return ok(
            SapHarvestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(tree_id), item_id),
                    tree_id=str(tree_id),
                    tree_type=component.tree_type,
                    item_id=item_id,
                    quantity=harvestable.quantity,
                )
            )
        )


class StartMachineHandler:
    command_type = "start-machine"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        machine_id = parse_entity_id(command.payload.get("machine_id"))
        recipe_id = str(command.payload.get("recipe_id", "")).strip()
        if character_id is None or machine_id is None:
            return rejected("invalid character or machine id")
        if not recipe_id:
            return rejected("missing recipe id")
        if not ctx.world.has_entity(machine_id):
            return rejected("machine does not exist")
        character = ctx.entity(character_id)
        machine = _reachable_entity(ctx, character_id, machine_id)
        if machine is None:
            return rejected("machine is not reachable")
        if not machine.has_component(MachineComponent):
            return rejected("target is not a machine")
        if machine.has_component(MachineBreakdownComponent):
            return rejected("machine is broken")
        machine_component = machine.get_component(MachineComponent)
        if machine_component.busy or machine.has_component(ProcessingTaskComponent):
            return rejected("machine is busy")
        recipe = _find_processing_recipe(ctx.world, recipe_id, machine_component.machine_type)
        if recipe is None:
            return rejected("processing recipe does not exist")
        for resource_type, quantity in recipe.inputs.items():
            found = False
            for item_id in contents(character):
                item = ctx.entity(item_id)
                if (
                    item.has_component(ResourceStackComponent)
                    and item.get_component(ResourceStackComponent).resource_type == resource_type
                    and item.get_component(ResourceStackComponent).quantity >= quantity
                ):
                    found = True
                    break
            if not found:
                return rejected("missing processing inputs")
        for resource_type, quantity in recipe.inputs.items():
            _consume_resource_stack(character, ctx.world, resource_type, quantity)
        ready_at = ctx.epoch + recipe.duration_seconds
        replace_component(machine, replace(machine_component, busy=True))
        machine.add_component(
            ProcessingTaskComponent(
                recipe_id=recipe.recipe_id,
                started_at_epoch=ctx.epoch,
                ready_at_epoch=ready_at,
            )
        )
        return ok(
            MachineProcessingStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(machine_id),),
                    machine_id=str(machine_id),
                    recipe_id=recipe.recipe_id,
                    ready_at_epoch=ready_at,
                )
            )
        )


class CollectMachineOutputHandler:
    command_type = "collect-machine-output"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        machine_id = parse_entity_id(command.payload.get("machine_id"))
        if character_id is None or machine_id is None:
            return rejected("invalid character or machine id")
        if not ctx.world.has_entity(machine_id):
            return rejected("machine does not exist")
        character = ctx.entity(character_id)
        machine = _reachable_entity(ctx, character_id, machine_id)
        if machine is None:
            return rejected("machine is not reachable")
        if not machine.has_component(MachineComponent) or not machine.has_component(
            ProcessingTaskComponent
        ):
            return rejected("machine has no output")
        task = machine.get_component(ProcessingTaskComponent)
        if not task.ready:
            return rejected("machine output is not ready")
        machine_component = machine.get_component(MachineComponent)
        recipe = _find_processing_recipe(ctx.world, task.recipe_id, machine_component.machine_type)
        if recipe is None:
            return rejected("processing recipe does not exist")
        output_ids = tuple(
            _spawn_product_item(
                ctx.world,
                character,
                resource_type,
                quantity,
                metadata=recipe.output_entities.get(resource_type),
            )
            for resource_type, quantity in recipe.outputs.items()
        )
        machine.remove_component(ProcessingTaskComponent)
        replace_component(machine, replace(machine_component, busy=False))
        return ok(
            MachineOutputCollectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(machine_id), *output_ids),
                    machine_id=str(machine_id),
                    recipe_id=recipe.recipe_id,
                    output_ids=output_ids,
                )
            )
        )


class CancelMachineHandler:
    command_type = "cancel-machine"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        machine_id = parse_entity_id(command.payload.get("machine_id"))
        if character_id is None or machine_id is None:
            return rejected("invalid character or machine id")
        if not ctx.world.has_entity(machine_id):
            return rejected("machine does not exist")
        machine = _reachable_entity(ctx, character_id, machine_id)
        if machine is None:
            return rejected("machine is not reachable")
        if not machine.has_component(MachineComponent) or not machine.has_component(
            ProcessingTaskComponent
        ):
            return rejected("machine has no task")
        task = machine.get_component(ProcessingTaskComponent)
        machine_component = machine.get_component(MachineComponent)
        machine.remove_component(ProcessingTaskComponent)
        replace_component(machine, replace(machine_component, busy=False))
        return ok(
            MachineProcessingCancelledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(machine_id),),
                    machine_id=str(machine_id),
                    recipe_id=task.recipe_id,
                )
            )
        )


class RepairMachineHandler:
    command_type = "repair-machine"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        machine_id = parse_entity_id(command.payload.get("machine_id"))
        if character_id is None or machine_id is None:
            return rejected("invalid character or machine id")
        if not ctx.world.has_entity(machine_id):
            return rejected("machine does not exist")
        machine = _reachable_entity(ctx, character_id, machine_id)
        if machine is None:
            return rejected("machine is not reachable")
        if not machine.has_component(MachineComponent):
            return rejected("target is not a machine")
        machine_component = machine.get_component(MachineComponent)
        replace_component(
            machine,
            replace(machine_component, quality=max(0.8, machine_component.quality)),
        )
        if machine.has_component(MachineBreakdownComponent):
            machine.remove_component(MachineBreakdownComponent)
        return ok(
            MachineRepairedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(machine_id),),
                    machine_id=str(machine_id),
                )
            )
        )


class FeedAnimalHandler:
    command_type = "feed-animal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        animal_id = parse_entity_id(command.payload.get("animal_id"))
        feed_type = str(command.payload.get("feed_type", "hay")).strip() or "hay"
        if character_id is None or animal_id is None:
            return rejected("invalid character or animal id")
        if not ctx.world.has_entity(animal_id):
            return rejected("animal does not exist")
        character = ctx.entity(character_id)
        animal = _reachable_entity(ctx, character_id, animal_id)
        if animal is None:
            return rejected("animal is not reachable")
        if not animal.has_component(FarmAnimalComponent):
            return rejected("target is not a farm animal")
        if not _consume_resource_stack(character, ctx.world, feed_type, 1):
            return rejected("missing animal feed")
        component = animal.get_component(FarmAnimalComponent)
        replace_component(
            animal,
            replace(
                component,
                fed_until_epoch=ctx.epoch + SECONDS_PER_DAY,
                mood=min(100.0, component.mood + 15.0),
            ),
        )
        return ok(
            AnimalFedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(animal_id),),
                    animal_id=str(animal_id),
                    feed_type=feed_type,
                )
            )
        )


class PetAnimalHandler:
    command_type = "pet-animal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        animal_id = parse_entity_id(command.payload.get("animal_id"))
        if character_id is None or animal_id is None:
            return rejected("invalid character or animal id")
        if not ctx.world.has_entity(animal_id):
            return rejected("animal does not exist")
        animal = _reachable_entity(ctx, character_id, animal_id)
        if animal is None:
            return rejected("animal is not reachable")
        if not animal.has_component(FarmAnimalComponent):
            return rejected("target is not a farm animal")
        component = animal.get_component(FarmAnimalComponent)
        if (
            component.last_petted_epoch is not None
            and ctx.epoch - component.last_petted_epoch < SECONDS_PER_DAY
        ):
            return rejected("animal already petted today")
        friendship = min(100.0, component.friendship + 5.0)
        replace_component(
            animal,
            replace(
                component,
                friendship=friendship,
                mood=min(100.0, component.mood + 5.0),
                last_petted_epoch=ctx.epoch,
            ),
        )
        return ok(
            AnimalPettedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(animal_id),),
                    animal_id=str(animal_id),
                    friendship=friendship,
                )
            )
        )


class BreedAnimalHandler:
    command_type = "breed-animal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        animal_id = parse_entity_id(command.payload.get("animal_id"))
        mate_id = parse_entity_id(command.payload.get("mate_id"))
        if character_id is None or animal_id is None or mate_id is None:
            return rejected("invalid character or animal id")
        if not ctx.world.has_entity(animal_id) or not ctx.world.has_entity(mate_id):
            return rejected("animal or mate does not exist")
        animal = _reachable_entity(ctx, character_id, animal_id)
        mate = _reachable_entity(ctx, character_id, mate_id)
        if animal is None or mate is None:
            return rejected("animal or mate is not reachable")
        if not animal.has_component(FarmAnimalComponent) or not mate.has_component(
            FarmAnimalComponent
        ):
            return rejected("targets are not farm animals")
        if animal.has_component(AnimalBreedingComponent):
            return rejected("animal is already bred")
        species = animal.get_component(FarmAnimalComponent).species
        if mate.get_component(FarmAnimalComponent).species != species:
            return rejected("animals are different species")
        due_epoch = ctx.epoch + int(command.payload.get("gestation_seconds", SECONDS_PER_DAY))
        replace_component(
            animal,
            AnimalBreedingComponent(
                mate_id=str(mate_id),
                due_epoch=due_epoch,
                offspring_species=species,
            ),
        )
        return ok(
            AnimalBredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(animal_id), str(mate_id)),
                    animal_id=str(animal_id),
                    mate_id=str(mate_id),
                    due_epoch=due_epoch,
                )
            )
        )


class CollectAnimalProductHandler:
    command_type = "collect-animal-product"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        animal_id = parse_entity_id(command.payload.get("animal_id"))
        if character_id is None or animal_id is None:
            return rejected("invalid character or animal id")
        if not ctx.world.has_entity(animal_id):
            return rejected("animal does not exist")
        character = ctx.entity(character_id)
        animal = _reachable_entity(ctx, character_id, animal_id)
        if animal is None:
            return rejected("animal is not reachable")
        if not animal.has_component(AnimalProductComponent):
            return rejected("animal has no product")
        product = animal.get_component(AnimalProductComponent)
        if not product.ready:
            return rejected("animal product is not ready")
        item_id = _spawn_product_item(
            ctx.world,
            character,
            product.product_type,
            product.quantity,
            kind="animal_product",
        )
        replace_component(
            animal,
            replace(product, ready=False, last_produced_epoch=ctx.epoch),
        )
        return ok(
            AnimalProductCollectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(animal_id), item_id),
                    animal_id=str(animal_id),
                    product_type=product.product_type,
                    item_id=item_id,
                    quantity=product.quantity,
                )
            )
        )


class FishHandler:
    command_type = "fish"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        spot_id = parse_entity_id(command.payload.get("spot_id"))
        if character_id is None or spot_id is None:
            return rejected("invalid character or fishing spot id")
        if not ctx.world.has_entity(spot_id):
            return rejected("fishing spot does not exist")
        character = ctx.entity(character_id)
        spot = _reachable_entity(ctx, character_id, spot_id)
        if spot is None:
            return rejected("fishing spot is not reachable")
        if not spot.has_component(FishingSpotComponent):
            return rejected("target is not a fishing spot")
        fishing = spot.get_component(FishingSpotComponent)
        season = _current_season(ctx.world)
        if fishing.season is not None and season != fishing.season:
            return rejected("fish is not available this season")
        if fishing.required_bait and not _consume_resource_stack(
            character, ctx.world, fishing.required_bait, 1
        ):
            return rejected("missing bait")
        item_id = _spawn_product_item(
            ctx.world, character, fishing.fish_type, fishing.quantity, kind="fish"
        )
        return ok(
            FishCaughtEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(spot_id), item_id),
                    spot_id=str(spot_id),
                    item_id=item_id,
                    fish_type=fishing.fish_type,
                    quantity=fishing.quantity,
                )
            )
        )


class MineHandler:
    command_type = "mine"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        node_id = parse_entity_id(command.payload.get("node_id"))
        if character_id is None or node_id is None:
            return rejected("invalid character or mining node id")
        if not ctx.world.has_entity(node_id):
            return rejected("mining node does not exist")
        character = ctx.entity(character_id)
        node = _reachable_entity(ctx, character_id, node_id)
        if node is None:
            return rejected("mining node is not reachable")
        if not node.has_component(MiningNodeComponent):
            return rejected("target is not a mining node")
        mining = node.get_component(MiningNodeComponent)
        item_id = _spawn_product_item(ctx.world, character, mining.resource_type, mining.quantity)
        _remove_from_container(ctx.world, node_id)
        ctx.world.remove(node_id)
        return ok(
            MiningNodeMinedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(item_id,),
                    node_id=str(node_id),
                    item_id=item_id,
                    resource_type=mining.resource_type,
                    quantity=mining.quantity,
                )
            )
        )


class DiscoverLadderHandler:
    command_type = "discover-ladder"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        ladder_id = parse_entity_id(command.payload.get("ladder_id"))
        if character_id is None or ladder_id is None:
            return rejected("invalid character or ladder id")
        if not ctx.world.has_entity(ladder_id):
            return rejected("ladder does not exist")
        ladder_entity = _reachable_entity(ctx, character_id, ladder_id)
        if ladder_entity is None:
            return rejected("ladder is not reachable")
        if not ladder_entity.has_component(LadderComponent):
            return rejected("target is not a ladder")
        ladder = ladder_entity.get_component(LadderComponent)
        replace_component(ladder_entity, replace(ladder, discovered=True))
        return ok(
            LadderDiscoveredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ladder_id), ladder.target_room_id),
                    ladder_id=str(ladder_id),
                    target_room_id=ladder.target_room_id,
                )
            )
        )


class OpenGeodeHandler:
    command_type = "open-geode"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        geode_id = parse_entity_id(command.payload.get("geode_id"))
        if character_id is None or geode_id is None:
            return rejected("invalid character or geode id")
        if not ctx.world.has_entity(geode_id):
            return rejected("geode does not exist")
        character = ctx.entity(character_id)
        if geode_id not in contents(character):
            return rejected("geode is not in inventory")
        geode = ctx.entity(geode_id)
        if not geode.has_component(GeodeComponent):
            return rejected("target is not a geode")
        component = geode.get_component(GeodeComponent)
        item_id = _spawn_product_item(
            ctx.world,
            character,
            component.resource_type,
            component.quantity,
            kind="mineral",
        )
        _remove_from_container(ctx.world, geode_id)
        ctx.world.remove(geode_id)
        return ok(
            GeodeOpenedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(item_id,),
                    geode_id=str(geode_id),
                    item_id=item_id,
                    resource_type=component.resource_type,
                    quantity=component.quantity,
                )
            )
        )


class ForageHandler:
    command_type = "forage"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        forage_id = parse_entity_id(command.payload.get("forage_id"))
        if character_id is None or forage_id is None:
            return rejected("invalid character or forage id")
        if not ctx.world.has_entity(forage_id):
            return rejected("forage does not exist")
        character = ctx.entity(character_id)
        forage = _reachable_entity(ctx, character_id, forage_id)
        if forage is None:
            return rejected("forage is not reachable")
        if not forage.has_component(ForageComponent):
            return rejected("target is not forage")
        component = forage.get_component(ForageComponent)
        season = _current_season(ctx.world)
        if season is not None and component.seasons and season not in component.seasons:
            return rejected("forage is not available this season")
        item_id = _spawn_product_item(
            ctx.world, character, component.resource_type, component.quantity
        )
        _remove_from_container(ctx.world, forage_id)
        ctx.world.remove(forage_id)
        return ok(
            ForageCollectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(item_id,),
                    forage_id=str(forage_id),
                    item_id=item_id,
                    resource_type=component.resource_type,
                    quantity=component.quantity,
                )
            )
        )


class GiveGiftHandler:
    command_type = "give-gift"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        item_id = parse_entity_id(command.payload.get("item_id"))
        if character_id is None or target_id is None or item_id is None:
            return rejected("invalid character, target, or item id")
        if not ctx.world.has_entity(target_id) or not ctx.world.has_entity(item_id):
            return rejected("target or item does not exist")
        character = ctx.entity(character_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")
        if item_id not in contents(character):
            return rejected("gift is not in inventory")
        item = ctx.entity(item_id)
        target = ctx.entity(target_id)
        resource_type = (
            item.get_component(ResourceStackComponent).resource_type
            if item.has_component(ResourceStackComponent)
            else item.get_component(IdentityComponent).name
        )
        delta = 5.0
        if target.has_component(GiftPreferenceComponent):
            prefs = target.get_component(GiftPreferenceComponent)
            if resource_type in prefs.loves:
                delta = 20.0
            elif resource_type in prefs.likes:
                delta = 10.0
            elif resource_type in prefs.dislikes:
                delta = -10.0
        friendship = (
            target.get_component(FriendshipComponent)
            if target.has_component(FriendshipComponent)
            else FriendshipComponent()
        )
        updated = FriendshipComponent(points=max(-100.0, min(100.0, friendship.points + delta)))
        replace_component(target, updated)
        character.remove_relationship(Contains, item_id)
        target.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item_id)
        return ok(
            GiftGivenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id), str(item_id)),
                    target_id=str(target_id),
                    item_id=str(item_id),
                    friendship=updated.points,
                )
            )
        )


class JoinFestivalHandler:
    command_type = "join-festival"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        festival_id = parse_entity_id(command.payload.get("festival_id"))
        if character_id is None or festival_id is None:
            return rejected("invalid character or festival id")
        if not ctx.world.has_entity(festival_id):
            return rejected("festival does not exist")
        festival = _reachable_entity(ctx, character_id, festival_id)
        if festival is None:
            return rejected("festival is not reachable")
        if not festival.has_component(FestivalComponent):
            return rejected("target is not a festival")
        component = festival.get_component(FestivalComponent)
        season = _current_season(ctx.world)
        if season is not None and component.season != season:
            return rejected("festival is not active this season")
        joined = tuple(sorted({*component.joined_character_ids, str(character_id)}))
        replace_component(festival, replace(component, joined_character_ids=joined))
        return ok(
            FestivalJoinedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(festival_id),),
                    festival_id=str(festival_id),
                    name=component.name,
                )
            )
        )


class ContributeBundleHandler:
    command_type = "contribute-bundle"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        bundle_id = parse_entity_id(command.payload.get("bundle_id"))
        resource_type = str(command.payload.get("resource_type", "")).strip()
        quantity = int(command.payload.get("quantity", 1))
        if character_id is None or bundle_id is None:
            return rejected("invalid character or bundle id")
        if not resource_type:
            return rejected("missing resource type")
        if quantity <= 0:
            return rejected("quantity must be positive")
        if not ctx.world.has_entity(bundle_id):
            return rejected("bundle does not exist")
        character = ctx.entity(character_id)
        bundle = _reachable_entity(ctx, character_id, bundle_id)
        if bundle is None:
            return rejected("bundle is not reachable")
        if not bundle.has_component(BundleComponent):
            return rejected("target is not a bundle")
        component = bundle.get_component(BundleComponent)
        if component.completed:
            return rejected("bundle is already complete")
        required = component.requirements.get(resource_type, 0)
        already = component.contributed.get(resource_type, 0)
        if required <= 0 or already + quantity > required:
            return rejected("bundle does not need that contribution")
        if not _consume_resource_stack(character, ctx.world, resource_type, quantity):
            return rejected("missing bundle resource")
        contributed = dict(component.contributed)
        contributed[resource_type] = already + quantity
        completed = all(
            contributed.get(kind, 0) >= amount
            for kind, amount in component.requirements.items()
        )
        replace_component(bundle, replace(component, contributed=contributed, completed=completed))
        return ok(
            BundleContributedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(bundle_id),),
                    bundle_id=component.bundle_id,
                    resource_type=resource_type,
                    quantity=quantity,
                    completed=completed,
                )
            )
        )


class ClaimMailHandler:
    command_type = "claim-mail"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        mail_id = parse_entity_id(command.payload.get("mail_id"))
        if character_id is None or mail_id is None:
            return rejected("invalid character or mail id")
        if not ctx.world.has_entity(mail_id):
            return rejected("mail does not exist")
        character = ctx.entity(character_id)
        mail = _reachable_entity(ctx, character_id, mail_id)
        if mail is None:
            return rejected("mail is not reachable")
        if not mail.has_component(MailComponent):
            return rejected("target is not mail")
        component = mail.get_component(MailComponent)
        if component.claimed:
            return rejected("mail already claimed")
        if component.reward_resource and component.reward_quantity > 0:
            _spawn_product_item(
                ctx.world,
                character,
                component.reward_resource,
                component.reward_quantity,
            )
        replace_component(mail, replace(component, claimed=True))
        return ok(
            MailClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(str(mail_id),),
                    mail_id=str(mail_id),
                    subject=component.subject,
                )
            )
        )


class CompleteFarmQuestHandler:
    command_type = "complete-farm-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_id = parse_entity_id(command.payload.get("quest_id"))
        if character_id is None or quest_id is None:
            return rejected("invalid character or quest id")
        if not ctx.world.has_entity(quest_id):
            return rejected("quest does not exist")
        character = ctx.entity(character_id)
        quest = _reachable_entity(ctx, character_id, quest_id)
        if quest is None:
            return rejected("quest is not reachable")
        if not quest.has_component(FarmQuestComponent):
            return rejected("target is not a farm quest")
        component = quest.get_component(FarmQuestComponent)
        if component.completed:
            return rejected("quest already completed")
        for resource_type, quantity in component.requested.items():
            stack = next(
                (
                    ctx.entity(item_id)
                    for item_id in contents(character)
                    if ctx.entity(item_id).has_component(ResourceStackComponent)
                    and ctx.entity(item_id).get_component(ResourceStackComponent).resource_type
                    == resource_type
                ),
                None,
            )
            if stack is None or stack.get_component(ResourceStackComponent).quantity < quantity:
                return rejected("missing quest items")
        for resource_type, quantity in component.requested.items():
            _consume_resource_stack(character, ctx.world, resource_type, quantity)
        reward_item_id = None
        if component.reward_resource and component.reward_quantity > 0:
            reward_item_id = _spawn_product_item(
                ctx.world,
                character,
                component.reward_resource,
                component.reward_quantity,
            )
        replace_component(quest, replace(component, completed=True))
        return ok(
            FarmQuestCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=component.quest_id,
                    reward_item_id=reward_item_id,
                )
            )
        )


class ShipItemsHandler:
    command_type = "ship-items"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        bin_id = parse_entity_id(command.payload.get("bin_id"))
        resource_type = str(command.payload.get("resource_type", "")).strip()
        quantity = int(command.payload.get("quantity", 1))
        unit_price = int(command.payload.get("unit_price", 1))
        if character_id is None or bin_id is None:
            return rejected("invalid character or shipping bin id")
        if not resource_type:
            return rejected("resource type is required")
        if quantity <= 0 or unit_price < 0:
            return rejected("quantity and unit price are invalid")
        if not ctx.world.has_entity(bin_id):
            return rejected("shipping bin does not exist")
        character = ctx.entity(character_id)
        shipping_bin = _reachable_entity(ctx, character_id, bin_id)
        if shipping_bin is None:
            return rejected("shipping bin is not reachable")
        if not shipping_bin.has_component(ShippingBinComponent):
            return rejected("target is not a shipping bin")
        if not _consume_resource_stack(character, ctx.world, resource_type, quantity):
            return rejected("missing shipped resource")
        component = shipping_bin.get_component(ShippingBinComponent)
        shipped = dict(component.shipped)
        shipped[resource_type] = shipped.get(resource_type, 0) + quantity
        earnings = quantity * unit_price
        replace_component(
            shipping_bin,
            ShippingBinComponent(shipped=shipped, earnings=component.earnings + earnings),
        )
        events: list[DomainEvent] = [
            ItemsShippedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(bin_id),),
                    bin_id=str(bin_id),
                    resource_type=resource_type,
                    quantity=quantity,
                    earnings=earnings,
                )
            )
        ]
        if _record_collection(ctx.world, character, resource_type):
            events.append(
                CollectionUpdatedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        entry=resource_type,
                    )
                )
            )
        return ok(*events)


class DonateMuseumHandler:
    command_type = "donate-museum"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        museum_id = parse_entity_id(command.payload.get("museum_id"))
        resource_type = str(command.payload.get("resource_type", "")).strip()
        if character_id is None or museum_id is None:
            return rejected("invalid character or museum id")
        if not resource_type:
            return rejected("resource type is required")
        if not ctx.world.has_entity(museum_id):
            return rejected("museum does not exist")
        character = ctx.entity(character_id)
        museum = _reachable_entity(ctx, character_id, museum_id)
        if museum is None:
            return rejected("museum is not reachable")
        if not museum.has_component(MuseumCollectionComponent):
            return rejected("target is not a museum collection")
        component = museum.get_component(MuseumCollectionComponent)
        if resource_type in component.donated:
            return rejected("museum already has that donation")
        if not _consume_resource_stack(character, ctx.world, resource_type, 1):
            return rejected("missing donation resource")
        donated = tuple(sorted({*component.donated, resource_type}))
        replace_component(museum, MuseumCollectionComponent(donated=donated))
        events: list[DomainEvent] = [
            MuseumDonatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(museum_id),),
                    museum_id=str(museum_id),
                    resource_type=resource_type,
                )
            )
        ]
        if _record_collection(ctx.world, character, resource_type):
            events.append(
                CollectionUpdatedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        entry=resource_type,
                    )
                )
            )
        return ok(*events)


class ClaimRewardHandler:
    command_type = "claim-reward"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        reward_id = parse_entity_id(command.payload.get("reward_id"))
        if character_id is None or reward_id is None:
            return rejected("invalid character or reward id")
        if not ctx.world.has_entity(reward_id):
            return rejected("reward does not exist")
        character = ctx.entity(character_id)
        reward = _reachable_entity(ctx, character_id, reward_id)
        if reward is None:
            return rejected("reward is not reachable")
        if not reward.has_component(RewardComponent):
            return rejected("target is not a reward")
        component = reward.get_component(RewardComponent)
        if component.claimed:
            return rejected("reward already claimed")
        item_id = _spawn_product_item(
            ctx.world,
            character,
            component.resource_type,
            component.quantity,
        )
        replace_component(reward, replace(component, claimed=True))
        return ok(
            RewardClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(str(reward_id), item_id),
                    reward_id=str(reward_id),
                    item_id=item_id,
                )
            )
        )


def gardensim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        name = None
        if entity.has_component(IdentityComponent):
            name = entity.get_component(IdentityComponent).name
        if entity.has_component(SoilComponent):
            soil_name = name or "soil"
            if entity.has_component(CropComponent):
                crop = entity.get_component(CropComponent)
                state = "dead" if crop.dead else "ready" if crop.ready else f"stage {crop.stage}"
                if entity.has_component(PestComponent):
                    state += ", pests"
                if entity.has_component(WeedComponent):
                    state += ", weeds"
                lines.append(f"Nearby crop: {crop.crop_type} in {soil_name} ({state}).")
            elif entity.has_component(TilledComponent):
                lines.append(f"Nearby tilled soil: {soil_name}.")
            else:
                lines.append(f"Nearby soil: {soil_name}.")
        if entity.has_component(TreeComponent):
            tree = entity.get_component(TreeComponent)
            tree_name = name or "tree"
            if tree.dead:
                state = "dead"
            elif not tree.mature:
                state = "growing"
            elif not entity.has_component(TreeTapComponent):
                state = "ready to tap"
            elif entity.has_component(HarvestableComponent) and entity.get_component(
                HarvestableComponent
            ).ready:
                state = "sap ready"
            else:
                state = "tapped"
            lines.append(f"Nearby tree: {tree.tree_type} in {tree_name} ({state}).")
        if entity.has_component(MachineComponent):
            machine = entity.get_component(MachineComponent)
            if entity.has_component(MachineBreakdownComponent):
                state = "broken"
            elif entity.has_component(ProcessingTaskComponent):
                task = entity.get_component(ProcessingTaskComponent)
                state = "ready" if task.ready else f"processing {task.recipe_id}"
            else:
                state = "idle"
            lines.append(f"Nearby machine: {machine.machine_type} ({state}).")
        if entity.has_component(FarmAnimalComponent):
            animal = entity.get_component(FarmAnimalComponent)
            product = (
                entity.get_component(AnimalProductComponent)
                if entity.has_component(AnimalProductComponent)
                else None
            )
            product_text = f", {product.product_type} ready" if product and product.ready else ""
            breeding_text = ", bred" if entity.has_component(AnimalBreedingComponent) else ""
            lines.append(
                f"Nearby animal: {animal.species}, mood {animal.mood:.0f}, "
                f"friendship {animal.friendship:.0f}{product_text}{breeding_text}."
            )
        if entity.has_component(FishingSpotComponent):
            spot = entity.get_component(FishingSpotComponent)
            lines.append(f"Nearby fishing spot: {spot.fish_type}.")
        if entity.has_component(MiningNodeComponent):
            node = entity.get_component(MiningNodeComponent)
            lines.append(f"Nearby mining node: {node.resource_type} x{node.quantity}.")
        if entity.has_component(MineLevelComponent):
            level = entity.get_component(MineLevelComponent)
            lines.append(f"Mine level {level.level}.")
        if entity.has_component(LadderComponent):
            ladder = entity.get_component(LadderComponent)
            state = "discovered" if ladder.discovered else "hidden"
            lines.append(f"Nearby ladder: {state}.")
        if entity.has_component(GeodeComponent):
            geode = entity.get_component(GeodeComponent)
            lines.append(f"Nearby geode: {geode.resource_type} x{geode.quantity}.")
        if entity.has_component(ForageComponent):
            forage = entity.get_component(ForageComponent)
            lines.append(f"Nearby forage: {forage.resource_type} x{forage.quantity}.")
        if entity.has_component(FestivalComponent):
            festival = entity.get_component(FestivalComponent)
            lines.append(f"Nearby festival: {festival.name} ({festival.season}).")
        if entity.has_component(BundleComponent):
            bundle = entity.get_component(BundleComponent)
            state = "complete" if bundle.completed else "open"
            lines.append(f"Nearby bundle: {bundle.bundle_id} ({state}).")
        if entity.has_component(MailComponent):
            mail = entity.get_component(MailComponent)
            if not mail.claimed:
                lines.append(f"Nearby mail: {mail.subject}.")
        if entity.has_component(FarmQuestComponent):
            quest = entity.get_component(FarmQuestComponent)
            if not quest.completed:
                lines.append(f"Nearby farm quest: {quest.quest_id}.")
        if entity.has_component(ShippingBinComponent):
            shipping_bin = entity.get_component(ShippingBinComponent)
            lines.append(f"Nearby shipping bin: {shipping_bin.earnings} earnings recorded.")
        if entity.has_component(MuseumCollectionComponent):
            museum = entity.get_component(MuseumCollectionComponent)
            lines.append(f"Nearby museum collection: {len(museum.donated)} donations.")
        if entity.has_component(RewardComponent):
            reward = entity.get_component(RewardComponent)
            if not reward.claimed:
                lines.append(f"Nearby reward: {reward.resource_type} x{reward.quantity}.")
    if character.has_component(CollectionComponent):
        collection = character.get_component(CollectionComponent)
        if collection.entries:
            lines.append("Collection entries: " + ", ".join(collection.entries) + ".")
    return sorted(lines)


def install_gardensim(actor) -> None:
    actor.register_consequence(CropGrowthConsequence())
    actor.register_consequence(TreeGrowthConsequence())
    actor.register_consequence(MachineProcessingConsequence())
    actor.register_consequence(MachineBreakdownConsequence())
    actor.register_consequence(AnimalProductConsequence())
    actor.register_consequence(AnimalBirthConsequence())
    actor.register_consequence(DailyFarmResetConsequence())


__all__ = [
    "AnimalFedEvent",
    "AnimalBirthConsequence",
    "AnimalBornEvent",
    "AnimalBredEvent",
    "AnimalBreedingComponent",
    "BreedAnimalHandler",
    "AnimalHomeComponent",
    "AnimalPettedEvent",
    "AnimalProductCollectedEvent",
    "AnimalProductComponent",
    "AnimalProductConsequence",
    "AnimalProductReadyEvent",
    "BundleComponent",
    "BundleContributedEvent",
    "CancelMachineHandler",
    "ClearDeadCropHandler",
    "ClaimMailHandler",
    "ClaimRewardHandler",
    "CollectAnimalProductHandler",
    "CollectMachineOutputHandler",
    "CollectionComponent",
    "CollectionUpdatedEvent",
    "CompleteFarmQuestHandler",
    "ContributeBundleHandler",
    "CropComponent",
    "CropGrewEvent",
    "CropGrowthComponent",
    "CropGrowthConsequence",
    "CropHarvestedEvent",
    "CropInspectionComponent",
    "CropInspectedEvent",
    "CropPestsTreatedEvent",
    "CropQualityComponent",
    "CropReadyEvent",
    "CropWateredEvent",
    "CropWeededEvent",
    "CropWitheredEvent",
    "DailyFarmResetComponent",
    "DailyFarmResetConsequence",
    "DailyFarmResetEvent",
    "DeadCropClearedEvent",
    "DiscoverLadderHandler",
    "FarmAnimalComponent",
    "FarmQuestCompletedEvent",
    "FarmQuestComponent",
    "FeedAnimalHandler",
    "FertilizerAppliedEvent",
    "FertilizerComponent",
    "FertilizeHandler",
    "FestivalComponent",
    "FestivalJoinedEvent",
    "FishCaughtEvent",
    "FishHandler",
    "FishingSpotComponent",
    "ForageCollectedEvent",
    "ForageComponent",
    "ForageHandler",
    "FriendshipComponent",
    "GeodeComponent",
    "GeodeOpenedEvent",
    "GiftGivenEvent",
    "GiftPreferenceComponent",
    "GiveGiftHandler",
    "GreenhouseComponent",
    "HarvestCropHandler",
    "HarvestableComponent",
    "HarvestSapHandler",
    "InspectCropHandler",
    "JoinFestivalHandler",
    "LadderComponent",
    "LadderDiscoveredEvent",
    "MachineComponent",
    "MachineBreakdownComponent",
    "MachineBreakdownConsequence",
    "MachineBrokeDownEvent",
    "MachineOutputCollectedEvent",
    "MachineProcessingConsequence",
    "MachineProcessingCancelledEvent",
    "MachineProcessingReadyEvent",
    "MachineProcessingStartedEvent",
    "MachineRepairedEvent",
    "MailClaimedEvent",
    "MailComponent",
    "MineHandler",
    "MineLevelComponent",
    "MiningNodeComponent",
    "MiningNodeMinedEvent",
    "MuseumCollectionComponent",
    "MuseumDonatedEvent",
    "DonateMuseumHandler",
    "OpenGeodeHandler",
    "PetAnimalHandler",
    "PestComponent",
    "PlantHandler",
    "ProcessingRecipeComponent",
    "ProcessingTaskComponent",
    "RegrowableComponent",
    "RepairMachineHandler",
    "RewardClaimedEvent",
    "RewardComponent",
    "SapHarvestedEvent",
    "SapReadyEvent",
    "SeedComponent",
    "SeedPlantedEvent",
    "SoilComponent",
    "SoilTilledEvent",
    "TapTreeHandler",
    "TreatPestsHandler",
    "TilledComponent",
    "TillHandler",
    "TreeComponent",
    "TreeGrowthConsequence",
    "TreeMaturedEvent",
    "TreeTapComponent",
    "TreeTappedEvent",
    "WaterCropHandler",
    "WateredComponent",
    "WeedComponent",
    "WeedCropHandler",
    "ShipItemsHandler",
    "ShippingBinComponent",
    "ItemsShippedEvent",
    "gardensim_fragments",
    "install_gardensim",
]
