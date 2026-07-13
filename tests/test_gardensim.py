"""Tests for garden-sim soil, crop growth, and harvest."""

from __future__ import annotations

from conftest import build_scenario, execute_handler

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    PortableComponent,
    WorldClockComponent,
    build_submitted_command,
    container_of,
    contents,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.foundation.consumables.components import FoodComponent
from bunnyland.foundation.environment.mechanics import CalendarComponent
from bunnyland.prompts import ComponentPromptContext
from bunnyland.simpacks.colonysim.mechanics import ResourceStackComponent
from bunnyland.simpacks.gardensim.mechanics import (
    AnimalBornEvent,
    AnimalBreedingComponent,
    AnimalProductCollectedEvent,
    AnimalProductComponent,
    AnimalProductConsequence,
    BreedAnimalHandler,
    BundleComponent,
    CancelMachineHandler,
    ClaimMailHandler,
    ClaimRewardHandler,
    ClearDeadCropHandler,
    CollectAnimalProductHandler,
    CollectionComponent,
    CollectionUpdatedEvent,
    CollectMachineOutputHandler,
    CompleteFarmQuestHandler,
    ContributeBundleHandler,
    CropComponent,
    CropGrewEvent,
    CropGrowthComponent,
    CropGrowthConsequence,
    CropHarvestedEvent,
    CropInspectedEvent,
    CropInspectionComponent,
    CropQualityComponent,
    CropReadyEvent,
    CropWeededEvent,
    DailyFarmResetComponent,
    DeadCropClearedEvent,
    DiscoverLadderHandler,
    DonateMuseumHandler,
    FarmAnimalComponent,
    FarmQuestComponent,
    FeedAnimalHandler,
    FertilizeHandler,
    FertilizerComponent,
    FestivalComponent,
    FishCaughtEvent,
    FishHandler,
    FishingSpotComponent,
    ForageComponent,
    ForageHandler,
    FriendshipComponent,
    GeodeComponent,
    GeodeOpenedEvent,
    GiftPreferenceComponent,
    GiveGiftHandler,
    GreenhouseComponent,
    HarvestableComponent,
    HarvestCropHandler,
    HarvestSapHandler,
    InspectCropHandler,
    ItemsShippedEvent,
    JoinFestivalHandler,
    LadderComponent,
    LadderDiscoveredEvent,
    MachineBreakdownComponent,
    MachineBrokeDownEvent,
    MachineComponent,
    MachineOutputCollectedEvent,
    MachineProcessingCancelledEvent,
    MachineProcessingReadyEvent,
    MachineRepairedEvent,
    MailClaimedEvent,
    MailComponent,
    MemberOfFestival,
    MineHandler,
    MineLevelComponent,
    MiningNodeComponent,
    MuseumCollectionComponent,
    MuseumDonatedEvent,
    OpenGeodeHandler,
    PestComponent,
    PetAnimalHandler,
    PlantHandler,
    ProcessingRecipeComponent,
    ProcessingTaskComponent,
    RegrowableComponent,
    RepairMachineHandler,
    RewardComponent,
    SapHarvestedEvent,
    SapReadyEvent,
    SeedComponent,
    ShipItemsHandler,
    ShippingBinComponent,
    SoilComponent,
    SoilTilledEvent,
    StartMachineHandler,
    TapTreeHandler,
    TilledComponent,
    TillHandler,
    TreatPestsHandler,
    TreeComponent,
    TreeGrowthConsequence,
    TreeMaturedEvent,
    TreeTapComponent,
    TreeTappedEvent,
    WaterCropHandler,
    WateredComponent,
    WeedComponent,
    WeedCropHandler,
    gardensim_fragments,
    install_gardensim,
)

DAY = 24 * 60 * 60
HOUR = 60 * 60


def _install(actor):
    actor.register_handler(TillHandler())
    actor.register_handler(PlantHandler())
    actor.register_handler(WaterCropHandler())
    actor.register_handler(FertilizeHandler())
    actor.register_handler(InspectCropHandler())
    actor.register_handler(WeedCropHandler())
    actor.register_handler(TreatPestsHandler())
    actor.register_handler(HarvestCropHandler())
    actor.register_handler(ClearDeadCropHandler())
    actor.register_handler(TapTreeHandler())
    actor.register_handler(HarvestSapHandler())
    actor.register_handler(StartMachineHandler())
    actor.register_handler(CollectMachineOutputHandler())
    actor.register_handler(CancelMachineHandler())
    actor.register_handler(RepairMachineHandler())
    actor.register_handler(FeedAnimalHandler())
    actor.register_handler(PetAnimalHandler())
    actor.register_handler(BreedAnimalHandler())
    actor.register_handler(CollectAnimalProductHandler())
    actor.register_handler(FishHandler())
    actor.register_handler(MineHandler())
    actor.register_handler(DiscoverLadderHandler())
    actor.register_handler(OpenGeodeHandler())
    actor.register_handler(ForageHandler())
    actor.register_handler(GiveGiftHandler())
    actor.register_handler(JoinFestivalHandler())
    actor.register_handler(ContributeBundleHandler())
    actor.register_handler(ClaimMailHandler())
    actor.register_handler(CompleteFarmQuestHandler())
    actor.register_handler(ShipItemsHandler())
    actor.register_handler(DonateMuseumHandler())
    actor.register_handler(ClaimRewardHandler())
    actor.register_consequence(CropGrowthConsequence())
    actor.register_consequence(TreeGrowthConsequence())
    from bunnyland.simpacks.gardensim.mechanics import (
        AnimalBirthConsequence,
        AnimalProductConsequence,
        DailyFarmResetConsequence,
        MachineBreakdownConsequence,
        MachineProcessingConsequence,
    )

    actor.register_consequence(MachineProcessingConsequence())
    actor.register_consequence(MachineBreakdownConsequence())
    actor.register_consequence(AnimalProductConsequence())
    actor.register_consequence(AnimalBirthConsequence())
    actor.register_consequence(DailyFarmResetConsequence())


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _handler_cmd(scenario, command_type, *, character_id=None, **payload):
    return build_submitted_command(
        character_id=str(scenario.character) if character_id is None else character_id,
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def test_gardensim_reachable_entity_rejects_missing_character_without_crashing():
    scenario = build_scenario()
    result = execute_handler(
        TillHandler(),
        HandlerContext(scenario.actor.world, scenario.actor.epoch),
        _handler_cmd(
            scenario,
            "till",
            character_id="entity_999999",
            soil_id=str(scenario.room_a),
        ),
    )

    assert not result.ok
    assert result.reason == "soil is not reachable"


def _soil(scenario, name="garden bed"):
    soil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="soil"), SoilComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id
    )
    return soil.id


def _seed(
    scenario,
    crop_type="turnip",
    growth_days=1.0,
    seasons=("spring", "summer", "autumn"),
    edible_satiety=0.0,
):
    seed = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{crop_type} seeds", kind="seed"),
            SeedComponent(
                crop_type=crop_type,
                growth_days=growth_days,
                yield_item=crop_type,
                yield_quantity=2,
                seasons=seasons,
                edible_nutrition=2.0 if edible_satiety else 0.0,
                edible_satiety=edible_satiety,
            ),
            PortableComponent(can_pick_up=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), seed.id
    )
    return seed.id


def _fertilizer(scenario):
    fertilizer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="speed fertilizer", kind="fertilizer"),
            FertilizerComponent(kind="speed", growth_multiplier=2.0),
            PortableComponent(can_pick_up=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), fertilizer.id
    )
    return fertilizer.id


def _tree(scenario, *, mature=False, maturity_days=1.0, name="sugar maple"):
    tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="tree"),
            TreeComponent(
                tree_type="sugar maple",
                planted_at_epoch=0,
                maturity_days=maturity_days,
                mature=mature,
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), tree.id
    )
    return tree.id


async def test_till_plant_water_grow_and_harvest_crop():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario)
    tilled: list[SoilTilledEvent] = []
    grew: list[CropGrewEvent] = []
    ready: list[CropReadyEvent] = []
    harvested: list[CropHarvestedEvent] = []
    scenario.actor.bus.subscribe(SoilTilledEvent, tilled.append)
    scenario.actor.bus.subscribe(CropGrewEvent, grew.append)
    scenario.actor.bus.subscribe(CropReadyEvent, ready.append)
    scenario.actor.bus.subscribe(CropHarvestedEvent, harvested.append)

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "water-crop", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(DAY)

    soil_entity = scenario.actor.world.get_entity(soil)
    assert tilled[0].soil_id == str(soil)
    assert container_of(scenario.actor.world.get_entity(seed)) is None
    assert soil_entity.get_component(CropComponent).ready is True
    assert soil_entity.get_component(HarvestableComponent).ready is True
    assert grew[-1].stage == 3
    assert ready[0].crop_type == "turnip"

    await scenario.actor.submit(_cmd(scenario, "harvest", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)

    assert not soil_entity.has_component(CropComponent)
    item = scenario.actor.world.get_entity(parse_entity_id(harvested[0].item_id))
    assert item.get_component(IdentityComponent).name == "turnip x2"
    assert item.get_component(ResourceStackComponent).resource_type == "turnip"
    assert container_of(item) == scenario.character


async def test_edible_crop_harvest_creates_food_resource_stack():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario, crop_type="strawberry", edible_satiety=12.0)

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "water-crop", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(DAY)
    await scenario.actor.submit(_cmd(scenario, "harvest", soil_id=str(soil)))
    await scenario.actor.tick(0.0)

    item_id = next(
        iter(scenario.actor.world.get_entity(scenario.character).get_relationships(Contains))
    )[1]
    item = scenario.actor.world.get_entity(item_id)
    assert item.get_component(ResourceStackComponent).resource_type == "strawberry"
    assert item.get_component(FoodComponent).satiety == 12.0


async def test_fertilizer_speeds_crop_growth():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario, growth_days=2.0)
    fertilizer = _fertilizer(scenario)

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "fertilize", soil_id=str(soil), fertilizer_id=str(fertilizer))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "water-crop", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(DAY)

    soil_entity = scenario.actor.world.get_entity(soil)
    assert soil_entity.get_component(CropGrowthComponent).progress_days == 2.0
    assert soil_entity.get_component(CropComponent).ready is True
    assert container_of(scenario.actor.world.get_entity(fertilizer)) is None


async def test_watering_starts_growth_from_watered_epoch():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario, growth_days=1.0)

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(0.0)

    await scenario.actor.submit(_cmd(scenario, "water-crop", soil_id=str(soil)))
    await scenario.actor.tick(DAY)

    soil_entity = scenario.actor.world.get_entity(soil)
    assert soil_entity.get_component(CropGrowthComponent).progress_days == 0.0
    assert soil_entity.get_component(CropComponent).ready is False

    await scenario.actor.tick(DAY)

    assert soil_entity.get_component(CropGrowthComponent).progress_days == 1.0
    assert soil_entity.get_component(CropComponent).ready is True


async def test_harvest_rejects_before_crop_is_ready():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "harvest", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "crop is not ready" for event in rejects)


async def test_wait_tap_tree_wait_and_harvest_sap():
    scenario = build_scenario()
    _install(scenario.actor)
    tree = _tree(scenario)
    rejects: list[CommandRejectedEvent] = []
    matured: list[TreeMaturedEvent] = []
    tapped: list[TreeTappedEvent] = []
    ready: list[SapReadyEvent] = []
    harvested: list[SapHarvestedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    scenario.actor.bus.subscribe(TreeMaturedEvent, matured.append)
    scenario.actor.bus.subscribe(TreeTappedEvent, tapped.append)
    scenario.actor.bus.subscribe(SapReadyEvent, ready.append)
    scenario.actor.bus.subscribe(SapHarvestedEvent, harvested.append)

    await scenario.actor.submit(_cmd(scenario, "tap-tree", tree_id=str(tree)))
    await scenario.actor.tick(HOUR)

    tree_entity = scenario.actor.world.get_entity(tree)
    assert rejects[-1].reason == "tree is not ready to tap"
    assert tree_entity.get_component(TreeComponent).mature is False

    await scenario.actor.tick(DAY)

    assert matured[0].tree_id == str(tree)
    assert tree_entity.get_component(TreeComponent).mature is True

    await scenario.actor.submit(_cmd(scenario, "tap-tree", tree_id=str(tree)))
    await scenario.actor.tick(HOUR)

    assert tapped[0].tree_id == str(tree)
    assert tree_entity.has_component(TreeTapComponent)
    assert tree_entity.get_component(HarvestableComponent).ready is False

    await scenario.actor.submit(_cmd(scenario, "harvest", tree_id=str(tree)))
    await scenario.actor.tick(HOUR)

    assert rejects[-1].reason == "sap is not ready"

    await scenario.actor.tick(DAY)

    assert ready[0].tree_id == str(tree)
    assert tree_entity.get_component(HarvestableComponent).ready is True

    await scenario.actor.submit(_cmd(scenario, "harvest", tree_id=str(tree)))
    await scenario.actor.tick(HOUR)

    sap = scenario.actor.world.get_entity(parse_entity_id(harvested[0].item_id))
    assert sap.get_component(IdentityComponent).name == "maple sap x4"
    assert sap.get_component(ResourceStackComponent).resource_type == "maple sap"
    assert sap.get_component(ResourceStackComponent).quantity == 4
    assert container_of(sap) == scenario.character
    assert tree_entity.get_component(HarvestableComponent).ready is False
    assert tree_entity.get_component(TreeTapComponent).last_collected_epoch == scenario.actor.epoch


async def test_machine_processing_consumes_inputs_waits_and_collects_output():
    scenario = build_scenario()
    _install(scenario.actor)
    flour = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="wheat x2", kind="resource"),
            ResourceStackComponent(resource_type="wheat", quantity=2),
            PortableComponent(can_pick_up=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), flour.id
    )
    machine = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="mill", kind="machine"), MachineComponent(machine_type="mill")],
    )
    recipe = spawn_entity(
        scenario.actor.world,
        [
            ProcessingRecipeComponent(
                recipe_id="flour",
                machine_type="mill",
                inputs={"wheat": 2},
                outputs={"flour": 1},
                duration_seconds=HOUR,
            )
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), machine.id
    )
    outputs: list[MachineOutputCollectedEvent] = []
    scenario.actor.bus.subscribe(MachineOutputCollectedEvent, outputs.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-machine", machine_id=str(machine.id), recipe_id="flour")
    )
    await scenario.actor.tick(0.0)
    assert recipe.has_component(ProcessingRecipeComponent)
    assert machine.get_component(MachineComponent).busy is True
    assert container_of(flour) is None

    await scenario.actor.tick(HOUR)
    assert machine.get_component(ProcessingTaskComponent).ready is True

    await scenario.actor.submit(
        _cmd(scenario, "collect-machine-output", machine_id=str(machine.id))
    )
    await scenario.actor.tick(0.0)

    output = scenario.actor.world.get_entity(parse_entity_id(outputs[0].output_ids[0]))
    assert output.get_component(ResourceStackComponent).resource_type == "flour"
    assert machine.get_component(MachineComponent).busy is False


async def test_feed_pet_and_collect_animal_product():
    scenario = build_scenario()
    _install(scenario.actor)
    hay = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hay x1", kind="resource"),
            ResourceStackComponent(resource_type="hay", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    animal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Henrietta", kind="animal"),
            FarmAnimalComponent(species="chicken", age_days=3.0, adult_age_days=3.0),
            AnimalProductComponent(product_type="egg", quantity=1, last_produced_epoch=0),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), hay.id
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), animal.id
    )
    collected: list[AnimalProductCollectedEvent] = []
    scenario.actor.bus.subscribe(AnimalProductCollectedEvent, collected.append)

    await scenario.actor.submit(_cmd(scenario, "feed-animal", animal_id=str(animal.id)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "pet-animal", animal_id=str(animal.id)))
    await scenario.actor.tick(DAY)

    assert animal.get_component(FarmAnimalComponent).friendship == 5.0
    assert animal.get_component(AnimalProductComponent).ready is True

    await scenario.actor.submit(_cmd(scenario, "collect-animal-product", animal_id=str(animal.id)))
    await scenario.actor.tick(0.0)

    egg = scenario.actor.world.get_entity(parse_entity_id(collected[0].item_id))
    assert egg.get_component(ResourceStackComponent).resource_type == "egg"
    assert animal.get_component(AnimalProductComponent).ready is False


async def test_crop_withers_out_of_season():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario)
    clock = list(scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities())[0]
    clock.add_component(CalendarComponent(season="spring"))

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(HOUR)
    clock.remove_component(CalendarComponent)
    clock.add_component(CalendarComponent(season="winter"))
    await scenario.actor.tick(0.0)

    soil_entity = scenario.actor.world.get_entity(soil)
    assert soil_entity.get_component(CropComponent).dead is True


def test_growth_consequences_skip_not_ready_edge_states():
    scenario = build_scenario()
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    clock = list(world.query().with_all([WorldClockComponent]).execute_entities())[0]
    clock.add_component(CalendarComponent(season="winter"))
    dead_crop = spawn_entity(
        world,
        [
            IdentityComponent(name="dead crop", kind="soil"),
            CropComponent(crop_type="turnip", planted_at_epoch=0, dead=True),
            CropGrowthComponent(progress_days=0.0, required_days=1.0, last_updated_epoch=0),
        ],
    )
    ready_crop = spawn_entity(
        world,
        [
            IdentityComponent(name="ready crop", kind="soil"),
            CropComponent(crop_type="turnip", planted_at_epoch=0, ready=True),
            CropGrowthComponent(progress_days=1.0, required_days=1.0, last_updated_epoch=0),
        ],
    )
    unwatered_crop = spawn_entity(
        world,
        [
            IdentityComponent(name="unwatered crop", kind="soil"),
            CropComponent(crop_type="winter root", planted_at_epoch=0, seasons=("winter",)),
            CropGrowthComponent(progress_days=0.0, required_days=1.0, last_updated_epoch=DAY),
        ],
    )
    dry_wither_crop = spawn_entity(
        world,
        [
            IdentityComponent(name="dry summer crop", kind="soil"),
            CropComponent(crop_type="melon", planted_at_epoch=0, seasons=("summer",)),
            CropGrowthComponent(progress_days=0.0, required_days=1.0, last_updated_epoch=0),
        ],
    )
    slow_crop = spawn_entity(
        world,
        [
            IdentityComponent(name="slow crop", kind="soil"),
            CropComponent(crop_type="winter root", planted_at_epoch=0, seasons=("winter",)),
            CropGrowthComponent(progress_days=0.0, required_days=10.0, last_updated_epoch=0),
            WateredComponent(watered_at_epoch=0, expires_at_epoch=2 * DAY),
        ],
    )
    for entity in (dead_crop, ready_crop, unwatered_crop, dry_wither_crop, slow_crop):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    crop_events = CropGrowthConsequence().process(world, DAY)

    assert crop_events
    assert unwatered_crop.get_component(CropGrowthComponent).last_updated_epoch == DAY
    assert dry_wither_crop.get_component(CropComponent).dead is True
    assert slow_crop.get_component(CropComponent).ready is False
    assert slow_crop.has_component(WateredComponent)

    dead_tree = spawn_entity(
        world,
        [TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=1.0, dead=True)],
    )
    young_tree = spawn_entity(
        world,
        [TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=10.0)],
    )
    untapped_tree = spawn_entity(
        world,
        [TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0.0, mature=True)],
    )
    bucketless_tree = spawn_entity(
        world,
        [
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0.0, mature=True),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0),
        ],
    )
    ready_bucket_tree = spawn_entity(
        world,
        [
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0.0, mature=True),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0),
            HarvestableComponent(yield_item="sap", ready=True),
        ],
    )
    early_tree = spawn_entity(
        world,
        [
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0.0, mature=True),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=DAY),
            HarvestableComponent(yield_item="sap", ready=False),
        ],
    )
    for entity in (
        dead_tree,
        young_tree,
        untapped_tree,
        bucketless_tree,
        ready_bucket_tree,
        early_tree,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    assert TreeGrowthConsequence().process(world, DAY) == []

    no_product = spawn_entity(world, [FarmAnimalComponent(species="chicken")])
    ready_product = spawn_entity(
        world,
        [
            FarmAnimalComponent(species="chicken", age_days=3.0, adult_age_days=3.0),
            AnimalProductComponent(product_type="egg", ready=True),
        ],
    )
    sick_animal = spawn_entity(
        world,
        [
            FarmAnimalComponent(species="chicken", age_days=3.0, adult_age_days=3.0, sick=True),
            AnimalProductComponent(product_type="egg"),
        ],
    )
    young_animal = spawn_entity(
        world,
        [
            FarmAnimalComponent(species="chicken", age_days=1.0, adult_age_days=3.0),
            AnimalProductComponent(product_type="egg"),
        ],
    )
    cooldown_animal = spawn_entity(
        world,
        [
            FarmAnimalComponent(species="chicken", age_days=3.0, adult_age_days=3.0),
            AnimalProductComponent(product_type="egg", last_produced_epoch=DAY),
        ],
    )
    # Unfed animal already at mood 0 and past the day's age: age/mood are unchanged, so the
    # FarmAnimalComponent is not replaced (branch 1015 -> 1017 false). No product either.
    stable_animal = spawn_entity(
        world,
        [FarmAnimalComponent(species="chicken", age_days=2.0, mood=0.0, fed_until_epoch=0)],
    )
    for entity in (
        no_product,
        ready_product,
        sick_animal,
        young_animal,
        cooldown_animal,
        stable_animal,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    assert AnimalProductConsequence().process(world, DAY) == []
    # The unchanged animal kept its original component instance values.
    assert stable_animal.get_component(FarmAnimalComponent).mood == 0.0
    assert stable_animal.get_component(FarmAnimalComponent).age_days == 2.0


async def test_fishing_mining_foraging_gifts_festivals_and_bundles():
    scenario = build_scenario(action_current=10.0)
    _install(scenario.actor)
    spot = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="pond", kind="water"), FishingSpotComponent(fish_type="trout")],
    )
    node = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="copper node", kind="ore"),
            MiningNodeComponent(resource_type="copper ore"),
        ],
    )
    forage = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="wild leek", kind="forage"), ForageComponent(resource_type="leek")],
    )
    friend = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Marnie", kind="character"),
            GiftPreferenceComponent(likes=("leek",)),
        ],
    )
    festival = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Egg Festival", kind="festival"),
            FestivalComponent(name="Egg Festival", season="spring"),
        ],
    )
    bundle = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Spring Bundle", kind="bundle"),
            BundleComponent(bundle_id="spring", requirements={"trout": 1}),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    for entity in (spot, node, forage, friend, festival, bundle):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    clock = list(scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities())[0]
    clock.add_component(CalendarComponent(season="spring"))
    fish_events: list[FishCaughtEvent] = []
    scenario.actor.bus.subscribe(FishCaughtEvent, fish_events.append)

    await scenario.actor.submit(_cmd(scenario, "fish", spot_id=str(spot.id)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "mine", node_id=str(node.id)))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "forage", forage_id=str(forage.id)))
    await scenario.actor.tick(0.0)

    leek_id = next(
        item_id
        for item_id in contents(scenario.actor.world.get_entity(scenario.character))
        if scenario.actor.world.get_entity(item_id).has_component(ResourceStackComponent)
        and scenario.actor.world.get_entity(item_id)
        .get_component(ResourceStackComponent)
        .resource_type
        == "leek"
    )
    await scenario.actor.submit(
        _cmd(scenario, "give-gift", target_id=str(friend.id), item_id=str(leek_id))
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "join-festival", festival_id=str(festival.id)))
    await scenario.actor.tick(0.0)
    repeated_join = execute_handler(
        JoinFestivalHandler(),
        HandlerContext(scenario.actor.world, scenario.actor.epoch),
        _handler_cmd(scenario, "join-festival", festival_id=str(festival.id)),
    )
    assert repeated_join.ok is True
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "contribute-bundle",
            bundle_id=str(bundle.id),
            resource_type="trout",
            quantity=1,
        )
    )
    await scenario.actor.tick(0.0)

    assert fish_events[0].fish_type == "trout"
    assert not scenario.actor.world.has_entity(node.id)
    assert not scenario.actor.world.has_entity(forage.id)
    assert friend.get_component(FriendshipComponent).points == 10.0
    assert scenario.actor.world.get_entity(scenario.character).get_relationships(
        MemberOfFestival
    ) == [(MemberOfFestival(), festival.id)]
    assert bundle.get_component(BundleComponent).completed is True


async def test_planting_respects_seed_season_unless_soil_is_greenhouse():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    winter_seed = _seed(scenario, "snow yam", seasons=("winter",))
    spring_seed = _seed(scenario, "turnip", seasons=("spring",))
    clock = list(scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities())[0]
    clock.add_component(CalendarComponent(season="winter"))
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "plant", soil_id=str(soil), seed_id=str(spring_seed))
    )
    await scenario.actor.tick(HOUR)

    soil_entity = scenario.actor.world.get_entity(soil)
    assert rejects[-1].reason == "seed cannot grow in this season"
    assert not soil_entity.has_component(CropComponent)
    assert container_of(scenario.actor.world.get_entity(spring_seed)) == scenario.character

    await scenario.actor.submit(
        _cmd(scenario, "plant", soil_id=str(soil), seed_id=str(winter_seed))
    )
    await scenario.actor.tick(HOUR)

    assert soil_entity.get_component(CropComponent).crop_type == "snow yam"

    greenhouse_soil = _soil(scenario, name="greenhouse bed")
    greenhouse_entity = scenario.actor.world.get_entity(greenhouse_soil)
    greenhouse_entity.add_component(GreenhouseComponent())
    greenhouse_seed = _seed(scenario, "tomato", seasons=("summer",))

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(greenhouse_soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "plant", soil_id=str(greenhouse_soil), seed_id=str(greenhouse_seed))
    )
    await scenario.actor.tick(HOUR)

    assert greenhouse_entity.get_component(CropComponent).crop_type == "tomato"


async def test_clear_dead_crop_removes_crop_state_from_soil():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario)
    clock = list(scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities())[0]
    clock.add_component(CalendarComponent(season="spring"))
    cleared: list[DeadCropClearedEvent] = []
    scenario.actor.bus.subscribe(DeadCropClearedEvent, cleared.append)

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(HOUR)
    clock.remove_component(CalendarComponent)
    clock.add_component(CalendarComponent(season="winter"))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "clear-dead-crop", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)

    soil_entity = scenario.actor.world.get_entity(soil)
    assert cleared[0].crop_type == "turnip"
    assert not soil_entity.has_component(CropComponent)
    assert not soil_entity.has_component(CropGrowthComponent)
    assert not soil_entity.has_component(HarvestableComponent)


def test_gardensim_handlers_reject_invalid_and_unreachable_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain stone", kind="prop")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    soil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="garden bed", kind="soil"), SoilComponent()],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id)
    tilled_soil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="tilled bed", kind="soil"),
            SoilComponent(),
            TilledComponent(tilled_at_epoch=0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), tilled_soil.id)
    cropped_soil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="cropped bed", kind="soil"),
            SoilComponent(),
            TilledComponent(tilled_at_epoch=0),
            CropComponent(crop_type="turnip", planted_at_epoch=0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), cropped_soil.id)
    dead_soil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="dead crop bed", kind="soil"),
            CropComponent(crop_type="turnip", planted_at_epoch=0, dead=True),
            HarvestableComponent(yield_item="turnip", quantity=1, ready=True),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), dead_soil.id)
    dead_soil_full = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="messy dead crop bed", kind="soil"),
            CropComponent(crop_type="turnip", planted_at_epoch=0, dead=True),
            CropGrowthComponent(progress_days=1.0, required_days=1.0, last_updated_epoch=0),
            HarvestableComponent(yield_item="turnip", quantity=1, ready=False),
            WateredComponent(watered_at_epoch=0, expires_at_epoch=DAY),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), dead_soil_full.id)
    young_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="young maple", kind="tree"),
            TreeComponent(tree_type="sugar maple", planted_at_epoch=0, maturity_days=1.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), young_tree.id)
    mature_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ready maple", kind="tree"),
            TreeComponent(
                tree_type="sugar maple",
                planted_at_epoch=0,
                maturity_days=0.0,
                mature=True,
            ),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), mature_tree.id)
    tapped_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="tapped maple", kind="tree"),
            TreeComponent(
                tree_type="sugar maple",
                planted_at_epoch=0,
                maturity_days=0.0,
                mature=True,
            ),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0),
            HarvestableComponent(yield_item="maple sap", quantity=4, ready=False),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), tapped_tree.id)
    bucketless_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bucketless maple", kind="tree"),
            TreeComponent(
                tree_type="sugar maple",
                planted_at_epoch=0,
                maturity_days=0.0,
                mature=True,
            ),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), bucketless_tree.id)
    dead_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="dead maple", kind="tree"),
            TreeComponent(
                tree_type="sugar maple",
                planted_at_epoch=0,
                maturity_days=0.0,
                mature=True,
                dead=True,
            ),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), dead_tree.id)
    seed = _seed(scenario)
    fertilizer = _fertilizer(scenario)
    distant_soil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far bed", kind="soil"), SoilComponent()],
    )
    distant_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far maple", kind="tree"),
            TreeComponent(
                tree_type="sugar maple",
                planted_at_epoch=0,
                maturity_days=0.0,
                mature=True,
            ),
        ],
    )
    distant_seed = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far seeds", kind="seed"),
            SeedComponent(crop_type="carrot", growth_days=1.0, yield_item="carrot"),
        ],
    )
    distant_fertilizer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far fertilizer", kind="fertilizer"),
            FertilizerComponent(),
        ],
    )

    cases = [
        (
            TillHandler(),
            _handler_cmd(
                scenario,
                "till",
                character_id="not-an-id",
                soil_id=str(soil.id),
            ),
            "invalid character or soil id",
        ),
        (
            TillHandler(),
            _handler_cmd(scenario, "till", soil_id="entity_999"),
            "soil does not exist",
        ),
        (
            TillHandler(),
            _handler_cmd(scenario, "till", soil_id=str(distant_soil.id)),
            "soil is not reachable",
        ),
        (
            TillHandler(),
            _handler_cmd(scenario, "till", soil_id=str(wrong_kind.id)),
            "target is not soil",
        ),
        (
            TillHandler(),
            _handler_cmd(scenario, "till", soil_id=str(tilled_soil.id)),
            "soil is already tilled",
        ),
        (
            PlantHandler(),
            _handler_cmd(
                scenario,
                "plant",
                character_id="not-an-id",
                soil_id=str(tilled_soil.id),
                seed_id=str(seed),
            ),
            "invalid character, soil, or seed id",
        ),
        (
            PlantHandler(),
            _handler_cmd(
                scenario,
                "plant",
                soil_id="entity_999",
                seed_id=str(seed),
            ),
            "soil or seed does not exist",
        ),
        (
            PlantHandler(),
            _handler_cmd(
                scenario,
                "plant",
                soil_id=str(distant_soil.id),
                seed_id=str(seed),
            ),
            "soil or seed is not reachable",
        ),
        (
            PlantHandler(),
            _handler_cmd(
                scenario,
                "plant",
                soil_id=str(tilled_soil.id),
                seed_id=str(distant_seed.id),
            ),
            "soil or seed is not reachable",
        ),
        (
            PlantHandler(),
            _handler_cmd(scenario, "plant", soil_id=str(soil.id), seed_id=str(seed)),
            "soil is not prepared",
        ),
        (
            PlantHandler(),
            _handler_cmd(
                scenario,
                "plant",
                soil_id=str(cropped_soil.id),
                seed_id=str(seed),
            ),
            "soil already has a crop",
        ),
        (
            PlantHandler(),
            _handler_cmd(
                scenario,
                "plant",
                soil_id=str(tilled_soil.id),
                seed_id=str(wrong_kind.id),
            ),
            "target seed is not plantable",
        ),
        (
            WaterCropHandler(),
            _handler_cmd(
                scenario,
                "water-crop",
                character_id="not-an-id",
                soil_id=str(soil.id),
            ),
            "invalid character or soil id",
        ),
        (
            WaterCropHandler(),
            _handler_cmd(scenario, "water-crop", soil_id="entity_999"),
            "soil does not exist",
        ),
        (
            WaterCropHandler(),
            _handler_cmd(scenario, "water-crop", soil_id=str(distant_soil.id)),
            "soil is not reachable",
        ),
        (
            WaterCropHandler(),
            _handler_cmd(scenario, "water-crop", soil_id=str(wrong_kind.id)),
            "target is not soil",
        ),
        (
            FertilizeHandler(),
            _handler_cmd(
                scenario,
                "fertilize",
                character_id="not-an-id",
                soil_id=str(soil.id),
                fertilizer_id=str(fertilizer),
            ),
            "invalid character, soil, or fertilizer id",
        ),
        (
            FertilizeHandler(),
            _handler_cmd(
                scenario,
                "fertilize",
                soil_id="entity_999",
                fertilizer_id=str(fertilizer),
            ),
            "soil or fertilizer does not exist",
        ),
        (
            FertilizeHandler(),
            _handler_cmd(
                scenario,
                "fertilize",
                soil_id=str(distant_soil.id),
                fertilizer_id=str(fertilizer),
            ),
            "soil or fertilizer is not reachable",
        ),
        (
            FertilizeHandler(),
            _handler_cmd(
                scenario,
                "fertilize",
                soil_id=str(soil.id),
                fertilizer_id=str(distant_fertilizer.id),
            ),
            "soil or fertilizer is not reachable",
        ),
        (
            FertilizeHandler(),
            _handler_cmd(
                scenario,
                "fertilize",
                soil_id=str(wrong_kind.id),
                fertilizer_id=str(fertilizer),
            ),
            "target is not soil",
        ),
        (
            FertilizeHandler(),
            _handler_cmd(
                scenario,
                "fertilize",
                soil_id=str(soil.id),
                fertilizer_id=str(wrong_kind.id),
            ),
            "target fertilizer is not usable",
        ),
        (
            HarvestCropHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                character_id="not-an-id",
                soil_id=str(soil.id),
            ),
            "invalid character or soil id",
        ),
        (
            HarvestCropHandler(),
            _handler_cmd(scenario, "harvest", soil_id="entity_999"),
            "soil does not exist",
        ),
        (
            HarvestCropHandler(),
            _handler_cmd(scenario, "harvest", soil_id=str(distant_soil.id)),
            "soil is not reachable",
        ),
        (
            HarvestCropHandler(),
            _handler_cmd(scenario, "harvest", soil_id=str(soil.id)),
            "soil has no harvestable crop",
        ),
        (
            HarvestCropHandler(),
            _handler_cmd(scenario, "harvest", soil_id=str(dead_soil.id)),
            "crop is dead",
        ),
        (
            ClearDeadCropHandler(),
            _handler_cmd(scenario, "clear-dead-crop", soil_id="not-an-id"),
            "invalid character or soil id",
        ),
        (
            ClearDeadCropHandler(),
            _handler_cmd(scenario, "clear-dead-crop", soil_id="entity_999"),
            "soil does not exist",
        ),
        (
            ClearDeadCropHandler(),
            _handler_cmd(scenario, "clear-dead-crop", soil_id=str(distant_soil.id)),
            "soil is not reachable",
        ),
        (
            ClearDeadCropHandler(),
            _handler_cmd(scenario, "clear-dead-crop", soil_id=str(soil.id)),
            "soil has no crop",
        ),
        (
            ClearDeadCropHandler(),
            _handler_cmd(scenario, "clear-dead-crop", soil_id=str(cropped_soil.id)),
            "crop is not dead",
        ),
        (
            TapTreeHandler(),
            _handler_cmd(
                scenario,
                "tap-tree",
                character_id="not-an-id",
                tree_id=str(mature_tree.id),
            ),
            "invalid character or tree id",
        ),
        (
            TapTreeHandler(),
            _handler_cmd(scenario, "tap-tree", tree_id="entity_999"),
            "tree does not exist",
        ),
        (
            TapTreeHandler(),
            _handler_cmd(scenario, "tap-tree", tree_id=str(distant_tree.id)),
            "tree is not reachable",
        ),
        (
            TapTreeHandler(),
            _handler_cmd(scenario, "tap-tree", tree_id=str(wrong_kind.id)),
            "target is not a tree",
        ),
        (
            TapTreeHandler(),
            _handler_cmd(scenario, "tap-tree", tree_id=str(dead_tree.id)),
            "tree is dead",
        ),
        (
            TapTreeHandler(),
            _handler_cmd(scenario, "tap-tree", tree_id=str(young_tree.id)),
            "tree is not ready to tap",
        ),
        (
            TapTreeHandler(),
            _handler_cmd(scenario, "tap-tree", tree_id=str(tapped_tree.id)),
            "tree is already tapped",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(
                scenario, "harvest", character_id="not-an-id", tree_id=str(tapped_tree.id)
            ),
            "invalid character or tree id",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest", tree_id="entity_999"),
            "tree does not exist",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest", tree_id=str(distant_tree.id)),
            "tree is not reachable",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest", tree_id=str(wrong_kind.id)),
            "target is not a tree",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest", tree_id=str(dead_tree.id)),
            "tree is dead",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest", tree_id=str(mature_tree.id)),
            "tree is not tapped",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest", tree_id=str(bucketless_tree.id)),
            "tree has no sap bucket",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest", tree_id=str(tapped_tree.id)),
            "sap is not ready",
        ),
    ]

    for handler, command, reason in cases:
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    water_result = execute_handler(
        WaterCropHandler(),
        ctx,
        _handler_cmd(scenario, "water-crop", soil_id=str(soil.id)),
    )
    assert water_result.ok is True
    assert soil.get_component(WateredComponent).expires_at_epoch == DAY

    simple_clear = execute_handler(
        ClearDeadCropHandler(),
        ctx,
        _handler_cmd(scenario, "clear-dead-crop", soil_id=str(dead_soil.id)),
    )
    assert simple_clear.ok is True
    assert not dead_soil.has_component(CropComponent)
    assert not dead_soil.has_component(HarvestableComponent)

    result = execute_handler(
        ClearDeadCropHandler(),
        ctx,
        _handler_cmd(scenario, "clear-dead-crop", soil_id=str(dead_soil_full.id)),
    )
    assert result.ok is True
    assert not dead_soil_full.has_component(CropComponent)
    assert not dead_soil_full.has_component(CropGrowthComponent)
    assert not dead_soil_full.has_component(HarvestableComponent)
    assert not dead_soil_full.has_component(WateredComponent)


def test_farm_loop_handlers_reject_invalid_and_unavailable_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    clock = list(scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities())[0]
    clock.add_component(CalendarComponent(season="winter"))
    character = scenario.actor.world.get_entity(scenario.character)

    wrong_kind = spawn_entity(scenario.actor.world, [IdentityComponent(name="crate", kind="prop")])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    machine = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="keg", kind="machine"), MachineComponent(machine_type="keg")],
    )
    busy_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="busy keg", kind="machine"),
            MachineComponent(machine_type="keg", busy=True),
        ],
    )
    animal = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="hen", kind="animal"), FarmAnimalComponent(species="chicken")],
    )
    product_animal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="young hen", kind="animal"),
            FarmAnimalComponent(species="chicken"),
            AnimalProductComponent(product_type="egg", ready=False),
        ],
    )
    petted_animal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="petted hen", kind="animal"),
            FarmAnimalComponent(species="chicken", last_petted_epoch=0),
        ],
    )
    ready_animal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ready hen", kind="animal"),
            FarmAnimalComponent(species="chicken"),
            AnimalProductComponent(product_type="egg", ready=True),
        ],
    )
    spot = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="spring pond", kind="water"),
            FishingSpotComponent(fish_type="trout", season="spring"),
        ],
    )
    baited_spot = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bait pond", kind="water"),
            FishingSpotComponent(fish_type="catfish", required_bait="bait"),
        ],
    )
    node = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="ore", kind="ore"), MiningNodeComponent(resource_type="ore")],
    )
    forage = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="berry", kind="forage"),
            ForageComponent(resource_type="berry", seasons=("spring",)),
        ],
    )
    target = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Robin", kind="character"), GiftPreferenceComponent()],
    )
    gift = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="stone x1", kind="resource"),
            ResourceStackComponent(resource_type="stone", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    festival = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Flower Dance", kind="festival"),
            FestivalComponent(name="Flower Dance", season="spring"),
        ],
    )
    bundle = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Pantry", kind="bundle"),
            BundleComponent(bundle_id="pantry", requirements={"turnip": 2}),
        ],
    )
    complete_bundle = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Done Bundle", kind="bundle"),
            BundleComponent(bundle_id="done", requirements={"turnip": 1}, completed=True),
        ],
    )
    partial_bundle = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Quality Crops", kind="bundle"),
            BundleComponent(bundle_id="quality", requirements={"stone": 2}),
        ],
    )
    for entity in (
        machine,
        busy_machine,
        animal,
        product_animal,
        petted_animal,
        ready_animal,
        spot,
        baited_spot,
        node,
        forage,
        target,
        festival,
        bundle,
        complete_bundle,
        partial_bundle,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    spawn_entity(
        scenario.actor.world,
        [
            ProcessingRecipeComponent(
                recipe_id="juice",
                machine_type="keg",
                inputs={"fruit": 1},
                outputs={"juice": 1},
                duration_seconds=HOUR,
            )
        ],
    )
    ready_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ready keg", kind="machine"),
            MachineComponent(machine_type="keg", busy=True),
            ProcessingTaskComponent(
                recipe_id="missing",
                started_at_epoch=0,
                ready_at_epoch=0,
                ready=True,
            ),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), ready_machine.id)
    pending_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="pending keg", kind="machine"),
            MachineComponent(machine_type="keg", busy=True),
            ProcessingTaskComponent(
                recipe_id="juice",
                started_at_epoch=0,
                ready_at_epoch=HOUR,
                ready=False,
            ),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), pending_machine.id)
    distant_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant keg", kind="machine"),
            MachineComponent(machine_type="keg"),
        ],
    )
    distant_animal = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far hen", kind="animal"), FarmAnimalComponent(species="chicken")],
    )
    distant_spot = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far pond", kind="water"), FishingSpotComponent(fish_type="bass")],
    )
    distant_node = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far ore", kind="ore"), MiningNodeComponent(resource_type="ore")],
    )
    distant_forage = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far berry", kind="forage"),
            ForageComponent(resource_type="berry"),
        ],
    )
    distant_target = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Far Robin", kind="character")],
    )
    distant_festival = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Fair", kind="festival"),
            FestivalComponent(name="Far Fair", season="winter"),
        ],
    )
    distant_bundle = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Bundle", kind="bundle"),
            BundleComponent(bundle_id="far", requirements={"stone": 1}),
        ],
    )
    assert container_of(scenario.actor.world.get_entity(distant_machine.id)) is None
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), gift.id)
    assert gift.id in contents(character)

    cases = [
        (
            StartMachineHandler(),
            _handler_cmd(scenario, "start-machine", character_id="bad", machine_id=str(machine.id)),
            "invalid character or machine id",
        ),
        (
            StartMachineHandler(),
            _handler_cmd(scenario, "start-machine", machine_id=str(machine.id), recipe_id=" "),
            "missing recipe id",
        ),
        (
            StartMachineHandler(),
            _handler_cmd(scenario, "start-machine", machine_id="entity_999", recipe_id="juice"),
            "machine does not exist",
        ),
        (
            StartMachineHandler(),
            _handler_cmd(
                scenario,
                "start-machine",
                machine_id=str(distant_machine.id),
                recipe_id="juice",
            ),
            "machine is not reachable",
        ),
        (
            StartMachineHandler(),
            _handler_cmd(
                scenario,
                "start-machine",
                machine_id=str(wrong_kind.id),
                recipe_id="juice",
            ),
            "target is not a machine",
        ),
        (
            StartMachineHandler(),
            _handler_cmd(
                scenario,
                "start-machine",
                machine_id=str(busy_machine.id),
                recipe_id="juice",
            ),
            "machine is busy",
        ),
        (
            StartMachineHandler(),
            _handler_cmd(
                scenario,
                "start-machine",
                machine_id=str(machine.id),
                recipe_id="missing",
            ),
            "processing recipe does not exist",
        ),
        (
            StartMachineHandler(),
            _handler_cmd(scenario, "start-machine", machine_id=str(machine.id), recipe_id="juice"),
            "missing processing inputs",
        ),
        (
            CollectMachineOutputHandler(),
            _handler_cmd(
                scenario, "collect-machine-output", character_id="bad", machine_id=str(machine.id)
            ),
            "invalid character or machine id",
        ),
        (
            CollectMachineOutputHandler(),
            _handler_cmd(scenario, "collect-machine-output", machine_id="entity_999"),
            "machine does not exist",
        ),
        (
            CollectMachineOutputHandler(),
            _handler_cmd(
                scenario,
                "collect-machine-output",
                machine_id=str(distant_machine.id),
            ),
            "machine is not reachable",
        ),
        (
            CollectMachineOutputHandler(),
            _handler_cmd(scenario, "collect-machine-output", machine_id=str(machine.id)),
            "machine has no output",
        ),
        (
            CollectMachineOutputHandler(),
            _handler_cmd(scenario, "collect-machine-output", machine_id=str(pending_machine.id)),
            "machine output is not ready",
        ),
        (
            CollectMachineOutputHandler(),
            _handler_cmd(
                scenario,
                "collect-machine-output",
                machine_id=str(busy_machine.id),
            ),
            "machine has no output",
        ),
        (
            CollectMachineOutputHandler(),
            _handler_cmd(scenario, "collect-machine-output", machine_id=str(ready_machine.id)),
            "processing recipe does not exist",
        ),
        (
            FeedAnimalHandler(),
            _handler_cmd(scenario, "feed-animal", character_id="bad", animal_id=str(animal.id)),
            "invalid character or animal id",
        ),
        (
            FeedAnimalHandler(),
            _handler_cmd(scenario, "feed-animal", animal_id="entity_999"),
            "animal does not exist",
        ),
        (
            FeedAnimalHandler(),
            _handler_cmd(scenario, "feed-animal", animal_id=str(distant_animal.id)),
            "animal is not reachable",
        ),
        (
            FeedAnimalHandler(),
            _handler_cmd(scenario, "feed-animal", animal_id=str(animal.id)),
            "missing animal feed",
        ),
        (
            FeedAnimalHandler(),
            _handler_cmd(scenario, "feed-animal", animal_id=str(wrong_kind.id)),
            "target is not a farm animal",
        ),
        (
            PetAnimalHandler(),
            _handler_cmd(scenario, "pet-animal", character_id="bad", animal_id=str(animal.id)),
            "invalid character or animal id",
        ),
        (
            PetAnimalHandler(),
            _handler_cmd(scenario, "pet-animal", animal_id="entity_999"),
            "animal does not exist",
        ),
        (
            PetAnimalHandler(),
            _handler_cmd(scenario, "pet-animal", animal_id=str(distant_animal.id)),
            "animal is not reachable",
        ),
        (
            PetAnimalHandler(),
            _handler_cmd(scenario, "pet-animal", animal_id=str(wrong_kind.id)),
            "target is not a farm animal",
        ),
        (
            PetAnimalHandler(),
            _handler_cmd(scenario, "pet-animal", animal_id=str(petted_animal.id)),
            "animal already petted today",
        ),
        (
            CollectAnimalProductHandler(),
            _handler_cmd(
                scenario,
                "collect-animal-product",
                character_id="bad",
                animal_id=str(ready_animal.id),
            ),
            "invalid character or animal id",
        ),
        (
            CollectAnimalProductHandler(),
            _handler_cmd(scenario, "collect-animal-product", animal_id="entity_999"),
            "animal does not exist",
        ),
        (
            CollectAnimalProductHandler(),
            _handler_cmd(
                scenario,
                "collect-animal-product",
                animal_id=str(distant_animal.id),
            ),
            "animal is not reachable",
        ),
        (
            CollectAnimalProductHandler(),
            _handler_cmd(scenario, "collect-animal-product", animal_id=str(animal.id)),
            "animal has no product",
        ),
        (
            CollectAnimalProductHandler(),
            _handler_cmd(scenario, "collect-animal-product", animal_id=str(wrong_kind.id)),
            "animal has no product",
        ),
        (
            CollectAnimalProductHandler(),
            _handler_cmd(scenario, "collect-animal-product", animal_id=str(product_animal.id)),
            "animal product is not ready",
        ),
        (
            FishHandler(),
            _handler_cmd(scenario, "fish", character_id="bad", spot_id=str(spot.id)),
            "invalid character or fishing spot id",
        ),
        (
            FishHandler(),
            _handler_cmd(scenario, "fish", spot_id="entity_999"),
            "fishing spot does not exist",
        ),
        (
            FishHandler(),
            _handler_cmd(scenario, "fish", spot_id=str(distant_spot.id)),
            "fishing spot is not reachable",
        ),
        (
            FishHandler(),
            _handler_cmd(scenario, "fish", spot_id=str(spot.id)),
            "fish is not available this season",
        ),
        (
            FishHandler(),
            _handler_cmd(scenario, "fish", spot_id=str(baited_spot.id)),
            "missing bait",
        ),
        (
            FishHandler(),
            _handler_cmd(scenario, "fish", spot_id=str(wrong_kind.id)),
            "target is not a fishing spot",
        ),
        (
            MineHandler(),
            _handler_cmd(scenario, "mine", character_id="bad", node_id=str(node.id)),
            "invalid character or mining node id",
        ),
        (
            MineHandler(),
            _handler_cmd(scenario, "mine", node_id="entity_999"),
            "mining node does not exist",
        ),
        (
            MineHandler(),
            _handler_cmd(scenario, "mine", node_id=str(distant_node.id)),
            "mining node is not reachable",
        ),
        (
            MineHandler(),
            _handler_cmd(scenario, "mine", node_id=str(wrong_kind.id)),
            "target is not a mining node",
        ),
        (
            ForageHandler(),
            _handler_cmd(scenario, "forage", character_id="bad", forage_id=str(forage.id)),
            "invalid character or forage id",
        ),
        (
            ForageHandler(),
            _handler_cmd(scenario, "forage", forage_id="entity_999"),
            "forage does not exist",
        ),
        (
            ForageHandler(),
            _handler_cmd(scenario, "forage", forage_id=str(distant_forage.id)),
            "forage is not reachable",
        ),
        (
            ForageHandler(),
            _handler_cmd(scenario, "forage", forage_id=str(forage.id)),
            "forage is not available this season",
        ),
        (
            ForageHandler(),
            _handler_cmd(scenario, "forage", forage_id=str(wrong_kind.id)),
            "target is not forage",
        ),
        (
            GiveGiftHandler(),
            _handler_cmd(
                scenario,
                "give-gift",
                character_id="bad",
                target_id=str(target.id),
                item_id=str(gift.id),
            ),
            "invalid character, target, or item id",
        ),
        (
            GiveGiftHandler(),
            _handler_cmd(scenario, "give-gift", target_id="entity_999", item_id=str(gift.id)),
            "target or item does not exist",
        ),
        (
            GiveGiftHandler(),
            _handler_cmd(
                scenario,
                "give-gift",
                target_id=str(distant_target.id),
                item_id=str(gift.id),
            ),
            "target is not reachable",
        ),
        (
            GiveGiftHandler(),
            _handler_cmd(
                scenario,
                "give-gift",
                target_id=str(target.id),
                item_id=str(wrong_kind.id),
            ),
            "gift is not in inventory",
        ),
        (
            JoinFestivalHandler(),
            _handler_cmd(
                scenario,
                "join-festival",
                character_id="bad",
                festival_id=str(festival.id),
            ),
            "invalid character or festival id",
        ),
        (
            JoinFestivalHandler(),
            _handler_cmd(scenario, "join-festival", festival_id="entity_999"),
            "festival does not exist",
        ),
        (
            JoinFestivalHandler(),
            _handler_cmd(scenario, "join-festival", festival_id=str(distant_festival.id)),
            "festival is not reachable",
        ),
        (
            JoinFestivalHandler(),
            _handler_cmd(scenario, "join-festival", festival_id=str(wrong_kind.id)),
            "target is not a festival",
        ),
        (
            JoinFestivalHandler(),
            _handler_cmd(scenario, "join-festival", festival_id=str(festival.id)),
            "festival is not active this season",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                character_id="bad",
                bundle_id=str(bundle.id),
                resource_type="turnip",
            ),
            "invalid character or bundle id",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(scenario, "contribute-bundle", bundle_id=str(bundle.id)),
            "missing resource type",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                bundle_id=str(bundle.id),
                resource_type="turnip",
                quantity=0,
            ),
            "quantity must be positive",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                bundle_id="entity_999",
                resource_type="turnip",
            ),
            "bundle does not exist",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                bundle_id=str(distant_bundle.id),
                resource_type="stone",
            ),
            "bundle is not reachable",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                bundle_id=str(wrong_kind.id),
                resource_type="stone",
            ),
            "target is not a bundle",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                bundle_id=str(complete_bundle.id),
                resource_type="turnip",
            ),
            "bundle is already complete",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                bundle_id=str(bundle.id),
                resource_type="turnip",
                quantity=3,
            ),
            "bundle does not need that contribution",
        ),
        (
            ContributeBundleHandler(),
            _handler_cmd(
                scenario,
                "contribute-bundle",
                bundle_id=str(bundle.id),
                resource_type="turnip",
                quantity=1,
            ),
            "missing bundle resource",
        ),
    ]

    for handler, command, reason in cases:
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    result = execute_handler(
        ContributeBundleHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "contribute-bundle",
            bundle_id=str(partial_bundle.id),
            resource_type="stone",
            quantity=1,
        ),
    )
    assert result.ok is True
    assert partial_bundle.get_component(BundleComponent).completed is False


async def test_farm_consequences_and_metadata_outputs_cover_state_edges():
    scenario = build_scenario(action_current=10.0)
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    room = scenario.actor.world.get_entity(scenario.room_a)
    grape = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="grape x1", kind="resource"),
            ResourceStackComponent(resource_type="grape", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), grape.id)
    machine = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="keg", kind="machine"), MachineComponent(machine_type="keg")],
    )
    recipe = spawn_entity(
        scenario.actor.world,
        [
            ProcessingRecipeComponent(
                recipe_id="wine",
                machine_type="keg",
                inputs={"grape": 1},
                outputs={"wine": 1, "raisins": 1},
                duration_seconds=HOUR,
                output_entities={
                    "wine": {
                        "display_name": "aged wine",
                        "hydration": 1.0,
                        "purity": 0.9,
                        "uses": 2,
                    },
                    "raisins": {
                        "display_name": "raisins",
                        "nutrition": 2.0,
                        "satiety": 8.0,
                        "uses": 1,
                    },
                },
            )
        ],
    )
    animal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hen", kind="animal"),
            FarmAnimalComponent(
                species="chicken",
                age_days=3.0,
                adult_age_days=3.0,
                last_petted_epoch=0,
            ),
            AnimalProductComponent(product_type="egg", interval_seconds=HOUR),
        ],
    )
    reset = spawn_entity(scenario.actor.world, [DailyFarmResetComponent(last_reset_epoch=0)])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), machine.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), animal.id)
    ready_events: list[MachineProcessingReadyEvent] = []
    scenario.actor.bus.subscribe(MachineProcessingReadyEvent, ready_events.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-machine", machine_id=str(machine.id), recipe_id="wine")
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "collect-machine-output", machine_id=str(machine.id))
    )
    await scenario.actor.tick(DAY)

    assert recipe.has_component(ProcessingRecipeComponent)
    assert ready_events[0].recipe_id == "wine"
    output_id = next(
        item_id
        for item_id in contents(character)
        if scenario.actor.world.get_entity(item_id).has_component(ResourceStackComponent)
        and scenario.actor.world.get_entity(item_id)
        .get_component(ResourceStackComponent)
        .resource_type
        == "wine"
    )
    wine = scenario.actor.world.get_entity(output_id)
    from bunnyland.foundation.consumables.components import ConsumableComponent, DrinkableComponent

    assert wine.get_component(IdentityComponent).name == "aged wine"
    assert wine.get_component(DrinkableComponent).hydration == 1.0
    assert wine.get_component(ConsumableComponent).current_uses == 2
    raisins_id = next(
        item_id
        for item_id in contents(character)
        if scenario.actor.world.get_entity(item_id).has_component(ResourceStackComponent)
        and scenario.actor.world.get_entity(item_id)
        .get_component(ResourceStackComponent)
        .resource_type
        == "raisins"
    )
    raisins = scenario.actor.world.get_entity(raisins_id)
    assert raisins.get_component(FoodComponent).satiety == 8.0
    assert animal.get_component(AnimalProductComponent).ready is True
    assert animal.get_component(FarmAnimalComponent).last_petted_epoch is None
    assert reset.get_component(DailyFarmResetComponent).last_reset_epoch == scenario.actor.epoch


def test_gift_preferences_apply_loved_disliked_and_plain_item_deltas():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    character = scenario.actor.world.get_entity(scenario.character)
    loved_target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Loved Target", kind="character"),
            GiftPreferenceComponent(loves=("diamond",)),
        ],
    )
    disliked_target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Disliked Target", kind="character"),
            GiftPreferenceComponent(dislikes=("trash",)),
            FriendshipComponent(points=-95.0),
        ],
    )
    plain_target = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Plain Target", kind="character")],
    )
    # Has preferences, but the gift matches none of loves/likes/dislikes (2246 -> 2248):
    # the default delta of 5.0 is used.
    neutral_target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Neutral Target", kind="character"),
            GiftPreferenceComponent(likes=("apple",)),
        ],
    )
    diamond = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="diamond x1", kind="resource"),
            ResourceStackComponent(resource_type="diamond", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    trash = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="trash x1", kind="resource"),
            ResourceStackComponent(resource_type="trash", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    shell = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="shell", kind="gift"), PortableComponent(can_pick_up=True)],
    )
    pebble = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="pebble", kind="gift"), PortableComponent(can_pick_up=True)],
    )
    for entity in (loved_target, disliked_target, plain_target, neutral_target):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    for item in (diamond, trash, shell, pebble):
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)

    for target, item in (
        (loved_target, diamond),
        (disliked_target, trash),
        (plain_target, shell),
        (neutral_target, pebble),
    ):
        result = execute_handler(
            GiveGiftHandler(),
            ctx,
            _handler_cmd(
                scenario,
                "give-gift",
                target_id=str(target.id),
                item_id=str(item.id),
            ),
        )
        assert result.ok is True

    assert loved_target.get_component(FriendshipComponent).points == 20.0
    assert disliked_target.get_component(FriendshipComponent).points == -100.0
    assert plain_target.get_component(FriendshipComponent).points == 5.0
    assert neutral_target.get_component(FriendshipComponent).points == 5.0
    assert container_of(shell) == plain_target.id


def test_gardensim_fragments_show_nearby_crop_state():
    scenario = build_scenario()
    soil = scenario.actor.world.get_entity(_soil(scenario))
    soil.add_component(CropComponent(crop_type="turnip", planted_at_epoch=0, stage=2))
    tree = scenario.actor.world.get_entity(_tree(scenario, mature=True, name="sugar maple"))
    tree.add_component(TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0))
    tree.add_component(HarvestableComponent(yield_item="maple sap", quantity=4, ready=True))

    fragments = gardensim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("Nearby crop: turnip" in line for line in fragments)
    assert any("Nearby tree: sugar maple in sugar maple (sap ready)." in line for line in fragments)


def test_gardensim_fragments_show_farm_loop_affordances():
    scenario = build_scenario()
    room = scenario.actor.world.get_entity(scenario.room_a)
    tilled = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="tilled bed", kind="soil"),
            SoilComponent(),
            TilledComponent(tilled_at_epoch=0),
        ],
    )
    ready_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="oak", kind="tree"),
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0, mature=True),
        ],
    )
    growing_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="sapling", kind="tree"),
            TreeComponent(tree_type="maple", planted_at_epoch=0, maturity_days=10, mature=False),
        ],
    )
    tapped_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="tapped oak", kind="tree"),
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0, mature=True),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0),
            HarvestableComponent(yield_item="sap", ready=False),
        ],
    )
    dead_tree = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="dead oak", kind="tree"),
            TreeComponent(
                tree_type="oak",
                planted_at_epoch=0,
                maturity_days=0,
                mature=True,
                dead=True,
            ),
        ],
    )
    idle_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="keg", kind="machine"),
            MachineComponent(machine_type="keg"),
        ],
    )
    ready_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="jar", kind="machine"),
            MachineComponent(machine_type="preserves jar"),
            ProcessingTaskComponent(
                recipe_id="jam",
                started_at_epoch=0,
                ready_at_epoch=0,
                ready=True,
            ),
        ],
    )
    machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="loom", kind="machine"),
            MachineComponent(machine_type="loom", busy=True),
            ProcessingTaskComponent(
                recipe_id="cloth",
                started_at_epoch=0,
                ready_at_epoch=HOUR,
                ready=False,
            ),
        ],
    )
    animal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="cow", kind="animal"),
            FarmAnimalComponent(species="cow", mood=80.0, friendship=25.0),
            AnimalProductComponent(product_type="milk", ready=True),
        ],
    )
    spot = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="lake", kind="water"), FishingSpotComponent(fish_type="bass")],
    )
    node = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="rock", kind="ore"), MiningNodeComponent(resource_type="stone")],
    )
    forage = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="mushroom", kind="forage"),
            ForageComponent(resource_type="mushroom"),
        ],
    )
    festival = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Luau", kind="festival"),
            FestivalComponent(name="Luau", season="summer"),
        ],
    )
    bundle = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Fish Tank", kind="bundle"),
            BundleComponent(bundle_id="fish_tank", requirements={"bass": 1}),
        ],
    )
    complete_bundle = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Done Tank", kind="bundle"),
            BundleComponent(bundle_id="done_tank", requirements={"bass": 1}, completed=True),
        ],
    )
    for entity in (
        tilled,
        ready_tree,
        growing_tree,
        tapped_tree,
        dead_tree,
        idle_machine,
        ready_machine,
        machine,
        animal,
        spot,
        node,
        forage,
        festival,
        bundle,
        complete_bundle,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    fragments = gardensim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    expected = (
        "Nearby tilled soil: tilled bed.",
        "Nearby tree: oak in oak (ready to tap).",
        "Nearby tree: maple in sapling (growing).",
        "Nearby tree: oak in tapped oak (tapped).",
        "Nearby tree: oak in dead oak (dead).",
        "Nearby machine: keg (idle).",
        "Nearby machine: preserves jar (ready).",
        "Nearby machine: loom (processing cloth).",
        "Nearby animal: cow, mood 80, friendship 25, milk ready.",
        "Nearby fishing spot: bass.",
        "Nearby mining node: stone x1.",
        "Nearby forage: mushroom x1.",
        "Nearby festival: Luau (summer).",
        "Nearby bundle: fish_tank (open).",
        "Nearby bundle: done_tank (complete).",
    )
    for line in expected:
        assert line in fragments


def test_gardensim_component_prompt_fragments_cover_compound_entity_state():
    scenario = build_scenario()
    world = scenario.actor.world
    soil = spawn_entity(
        world,
        [
            IdentityComponent(name="ready bed", kind="soil"),
            SoilComponent(),
            CropComponent(crop_type="turnip", planted_at_epoch=0, ready=True),
            PestComponent(),
        ],
    )
    machine = spawn_entity(
        world,
        [
            MachineComponent(machine_type="preserves-jar"),
            ProcessingTaskComponent(recipe_id="jam", started_at_epoch=0, ready_at_epoch=10),
        ],
    )

    soil_ctx = ComponentPromptContext.for_entity(world, soil)
    machine_ctx = ComponentPromptContext.for_entity(world, machine)

    assert soil.get_component(SoilComponent).prompt_fragments(soil_ctx) == (
        "Nearby crop: turnip in ready bed (ready, pests).",
    )
    assert machine.get_component(MachineComponent).prompt_fragments(machine_ctx) == (
        "Nearby machine: preserves-jar (processing jam).",
    )


async def test_gardensim_catalogue_crops_machines_animals_mines_and_collections():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    room = scenario.actor.world.get_entity(scenario.room_a)
    soil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="berry patch", kind="soil"),
            SoilComponent(),
            TilledComponent(tilled_at_epoch=0),
            CropComponent(crop_type="berry", planted_at_epoch=0, stage=3, ready=True),
            CropGrowthComponent(progress_days=1.0, required_days=1.0, last_updated_epoch=0),
            HarvestableComponent(yield_item="berry", quantity=2, ready=True),
            CropQualityComponent(quality=1.5),
            RegrowableComponent(regrow_days=1.0),
            PestComponent(),
            WeedComponent(),
        ],
    )
    task_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="busy keg", kind="machine"),
            MachineComponent(machine_type="keg", busy=True),
            ProcessingTaskComponent(recipe_id="juice", started_at_epoch=0, ready_at_epoch=DAY),
        ],
    )
    broken_machine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="old loom", kind="machine"),
            MachineComponent(machine_type="loom", quality=0.1),
        ],
    )
    cow = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="cow", kind="animal"), FarmAnimalComponent(species="cow")],
    )
    mate = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="mate cow", kind="animal"), FarmAnimalComponent(species="cow")],
    )
    ladder = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ladder", kind="mine"),
            LadderComponent(target_room_id=str(scenario.room_b)),
        ],
    )
    geode = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="geode", kind="geode"),
            GeodeComponent(resource_type="amethyst", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    shipping_bin = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="shipping bin", kind="shipping"), ShippingBinComponent()],
    )
    quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="melon request", kind="quest"),
            FarmQuestComponent(
                quest_id="melon-request",
                requested={"melon": 1},
                reward_resource="coin",
                reward_quantity=5,
            ),
        ],
    )
    mail = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="mayor mail", kind="mail"),
            MailComponent(subject="Thanks", reward_resource="coin", reward_quantity=1),
        ],
    )
    reward = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="museum reward", kind="reward"),
            RewardComponent(resource_type="star token", quantity=1),
        ],
    )
    for entity in (
        soil,
        task_machine,
        broken_machine,
        cow,
        mate,
        ladder,
        shipping_bin,
        quest,
        mail,
        reward,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), geode.id)
    for resource_type in ("grape", "melon"):
        stack = spawn_entity(
            scenario.actor.world,
            [
                IdentityComponent(name=resource_type, kind="resource"),
                ResourceStackComponent(resource_type=resource_type, quantity=1),
                PortableComponent(can_pick_up=True),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), stack.id)

    inspected: list[CropInspectedEvent] = []
    weeded: list[CropWeededEvent] = []
    harvested: list[CropHarvestedEvent] = []
    cancelled: list[MachineProcessingCancelledEvent] = []
    broke_down: list[MachineBrokeDownEvent] = []
    repaired: list[MachineRepairedEvent] = []
    born: list[AnimalBornEvent] = []
    ladders: list[LadderDiscoveredEvent] = []
    geodes: list[GeodeOpenedEvent] = []
    shipped: list[ItemsShippedEvent] = []
    mail_claimed: list[MailClaimedEvent] = []
    scenario.actor.bus.subscribe(CropInspectedEvent, inspected.append)
    scenario.actor.bus.subscribe(CropWeededEvent, weeded.append)
    scenario.actor.bus.subscribe(CropHarvestedEvent, harvested.append)
    scenario.actor.bus.subscribe(MachineProcessingCancelledEvent, cancelled.append)
    scenario.actor.bus.subscribe(MachineBrokeDownEvent, broke_down.append)
    scenario.actor.bus.subscribe(MachineRepairedEvent, repaired.append)
    scenario.actor.bus.subscribe(AnimalBornEvent, born.append)
    scenario.actor.bus.subscribe(LadderDiscoveredEvent, ladders.append)
    scenario.actor.bus.subscribe(GeodeOpenedEvent, geodes.append)
    scenario.actor.bus.subscribe(ItemsShippedEvent, shipped.append)
    scenario.actor.bus.subscribe(MailClaimedEvent, mail_claimed.append)

    await scenario.actor.submit(_cmd(scenario, "inspect", soil_id=str(soil.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "weed-crop", soil_id=str(soil.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "treat-pests", soil_id=str(soil.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "harvest", soil_id=str(soil.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "cancel-machine", machine_id=str(task_machine.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "repair-machine", machine_id=str(broken_machine.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "breed-animal",
            animal_id=str(cow.id),
            mate_id=str(mate.id),
            gestation_seconds=0,
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "discover-ladder", ladder_id=str(ladder.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "open-geode", geode_id=str(geode.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "ship-items",
            bin_id=str(shipping_bin.id),
            resource_type="grape",
            quantity=1,
            unit_price=3,
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "complete-farm-quest", quest_id=str(quest.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "claim-mail", mail_id=str(mail.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "claim-reward", reward_id=str(reward.id)))
    await scenario.actor.tick(HOUR)

    assert inspected[0].notes == "berry stage 3, pests present, weeds present"
    assert weeded[0].soil_id == str(soil.id)
    assert harvested[0].quantity == 4
    assert soil.has_component(CropComponent)
    assert soil.get_component(RegrowableComponent).regrowth_count == 1
    assert not soil.has_component(PestComponent)
    assert not soil.has_component(WeedComponent)
    assert soil.get_component(CropInspectionComponent).notes.startswith("berry")
    assert cancelled[0].recipe_id == "juice"
    assert not task_machine.has_component(ProcessingTaskComponent)
    assert broke_down[0].machine_id == str(broken_machine.id)
    assert repaired[0].machine_id == str(broken_machine.id)
    assert not broken_machine.has_component(MachineBreakdownComponent)
    assert not cow.has_component(AnimalBreedingComponent)
    assert born[0].animal_id == str(cow.id)
    assert ladders[0].target_room_id == str(scenario.room_b)
    assert ladder.get_component(LadderComponent).discovered is True
    assert geodes[0].resource_type == "amethyst"
    assert not scenario.actor.world.has_entity(geode.id)
    assert shipped[0].earnings == 3
    assert shipping_bin.get_component(ShippingBinComponent).shipped == {"grape": 1}
    assert character.get_component(CollectionComponent).entries == ("grape",)
    assert quest.get_component(FarmQuestComponent).completed is True
    assert mail_claimed[0].subject == "Thanks"
    assert mail.get_component(MailComponent).claimed is True
    assert reward.get_component(RewardComponent).claimed is True
    fragments = gardensim_fragments(scenario.actor.world, character)
    assert "Collection entries: grape." in fragments


async def test_gardensim_museum_donations_update_collections_and_reject_duplicates():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    room = scenario.actor.world.get_entity(scenario.room_a)
    museum = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="museum shelf", kind="museum"), MuseumCollectionComponent()],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), museum.id)
    stack = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ruby", kind="resource"),
            ResourceStackComponent(resource_type="ruby", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), stack.id)
    donated: list[MuseumDonatedEvent] = []
    collected: list[CollectionUpdatedEvent] = []
    rejected_events: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(MuseumDonatedEvent, donated.append)
    scenario.actor.bus.subscribe(CollectionUpdatedEvent, collected.append)
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejected_events.append)

    await scenario.actor.submit(
        _cmd(scenario, "donate-museum", museum_id=str(museum.id), resource_type="ruby")
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "donate-museum", museum_id=str(museum.id), resource_type="ruby")
    )
    await scenario.actor.tick(HOUR)

    assert donated[0].resource_type == "ruby"
    assert collected[0].entry == "ruby"
    assert museum.get_component(MuseumCollectionComponent).donated == ("ruby",)
    assert character.get_component(CollectionComponent).entries == ("ruby",)
    assert rejected_events[-1].reason == "museum already has that donation"
    fragments = gardensim_fragments(scenario.actor.world, character)
    assert "Nearby museum collection: 1 donations." in fragments
    assert "Collection entries: ruby." in fragments


def test_gardensim_catalogue_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    other_room = scenario.actor.world.get_entity(scenario.room_b)
    character = scenario.actor.world.get_entity(scenario.character)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain crate", kind="prop")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    no_crop_soil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="empty bed", kind="soil"), SoilComponent()],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), no_crop_soil.id)
    unreachable_crop = spawn_entity(
        scenario.actor.world,
        [CropComponent(crop_type="turnip", planted_at_epoch=0)],
    )
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unreachable_crop.id)
    crop_no_weeds = spawn_entity(
        scenario.actor.world,
        [CropComponent(crop_type="turnip", planted_at_epoch=0)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), crop_no_weeds.id)
    crop_no_pests = spawn_entity(
        scenario.actor.world,
        [CropComponent(crop_type="turnip", planted_at_epoch=0)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), crop_no_pests.id)
    unreachable_machine = spawn_entity(
        scenario.actor.world,
        [MachineComponent(machine_type="keg")],
    )
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unreachable_machine.id)
    idle_machine = spawn_entity(
        scenario.actor.world,
        [MachineComponent(machine_type="keg")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), idle_machine.id)
    animal = spawn_entity(
        scenario.actor.world,
        [FarmAnimalComponent(species="cow")],
    )
    mate = spawn_entity(
        scenario.actor.world,
        [FarmAnimalComponent(species="cow"), AnimalBreedingComponent()],
    )
    goat = spawn_entity(
        scenario.actor.world,
        [FarmAnimalComponent(species="goat")],
    )
    distant_animal = spawn_entity(
        scenario.actor.world,
        [FarmAnimalComponent(species="cow")],
    )
    for entity in (animal, mate, goat):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_animal.id)
    ladder = spawn_entity(
        scenario.actor.world,
        [LadderComponent(target_room_id=str(scenario.room_b))],
    )
    distant_ladder = spawn_entity(
        scenario.actor.world,
        [LadderComponent(target_room_id=str(scenario.room_b))],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), ladder.id)
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_ladder.id)
    geode_in_room = spawn_entity(
        scenario.actor.world,
        [GeodeComponent(resource_type="amethyst")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), geode_in_room.id)
    not_geode = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="inventory stone", kind="prop")],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), not_geode.id)
    claimed_mail = spawn_entity(
        scenario.actor.world,
        [MailComponent(subject="done", claimed=True)],
    )
    distant_mail = spawn_entity(
        scenario.actor.world,
        [MailComponent(subject="far")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), claimed_mail.id)
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_mail.id)
    completed_quest = spawn_entity(
        scenario.actor.world,
        [FarmQuestComponent(quest_id="done", requested={}, completed=True)],
    )
    hungry_quest = spawn_entity(
        scenario.actor.world,
        [FarmQuestComponent(quest_id="hungry", requested={"melon": 1})],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), completed_quest.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hungry_quest.id)
    shipping_bin = spawn_entity(
        scenario.actor.world,
        [ShippingBinComponent()],
    )
    distant_bin = spawn_entity(
        scenario.actor.world,
        [ShippingBinComponent()],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), shipping_bin.id)
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_bin.id)
    museum = spawn_entity(
        scenario.actor.world,
        [MuseumCollectionComponent()],
    )
    distant_museum = spawn_entity(
        scenario.actor.world,
        [MuseumCollectionComponent()],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), museum.id)
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_museum.id)
    claimed_reward = spawn_entity(
        scenario.actor.world,
        [RewardComponent(resource_type="coin", claimed=True)],
    )
    distant_reward = spawn_entity(
        scenario.actor.world,
        [RewardComponent(resource_type="coin")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), claimed_reward.id)
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_reward.id)

    cases = [
        (
            InspectCropHandler(),
            "inspect",
            {"soil_id": "not-an-id"},
            "invalid character or soil id",
        ),
        (InspectCropHandler(), "inspect", {"soil_id": "entity_999"}, "soil does not exist"),
        (
            InspectCropHandler(),
            "inspect",
            {"soil_id": str(unreachable_crop.id)},
            "soil is not reachable",
        ),
        (
            InspectCropHandler(),
            "inspect",
            {"soil_id": str(no_crop_soil.id)},
            "soil has no crop",
        ),
        (WeedCropHandler(), "weed-crop", {"soil_id": "entity_999"}, "soil does not exist"),
        (
            WeedCropHandler(),
            "weed-crop",
            {"soil_id": str(unreachable_crop.id)},
            "soil is not reachable",
        ),
        (
            WeedCropHandler(),
            "weed-crop",
            {"soil_id": str(crop_no_weeds.id)},
            "soil has no weeds",
        ),
        (TreatPestsHandler(), "treat-pests", {"soil_id": "entity_999"}, "soil does not exist"),
        (
            TreatPestsHandler(),
            "treat-pests",
            {"soil_id": str(unreachable_crop.id)},
            "soil is not reachable",
        ),
        (
            TreatPestsHandler(),
            "treat-pests",
            {"soil_id": str(crop_no_pests.id)},
            "soil has no pests",
        ),
        (
            CancelMachineHandler(),
            "cancel-machine",
            {"machine_id": "not-an-id"},
            "invalid character or machine id",
        ),
        (
            CancelMachineHandler(),
            "cancel-machine",
            {"machine_id": "entity_999"},
            "machine does not exist",
        ),
        (
            CancelMachineHandler(),
            "cancel-machine",
            {"machine_id": str(unreachable_machine.id)},
            "machine is not reachable",
        ),
        (
            CancelMachineHandler(),
            "cancel-machine",
            {"machine_id": str(idle_machine.id)},
            "machine has no task",
        ),
        (
            RepairMachineHandler(),
            "repair-machine",
            {"machine_id": "entity_999"},
            "machine does not exist",
        ),
        (
            RepairMachineHandler(),
            "repair-machine",
            {"machine_id": str(unreachable_machine.id)},
            "machine is not reachable",
        ),
        (
            RepairMachineHandler(),
            "repair-machine",
            {"machine_id": str(wrong_kind.id)},
            "target is not a machine",
        ),
        (
            BreedAnimalHandler(),
            "breed-animal",
            {"animal_id": "not-an-id", "mate_id": str(mate.id)},
            "invalid character or animal id",
        ),
        (
            BreedAnimalHandler(),
            "breed-animal",
            {"animal_id": str(animal.id), "mate_id": "entity_999"},
            "animal or mate does not exist",
        ),
        (
            BreedAnimalHandler(),
            "breed-animal",
            {"animal_id": str(animal.id), "mate_id": str(distant_animal.id)},
            "animal or mate is not reachable",
        ),
        (
            BreedAnimalHandler(),
            "breed-animal",
            {"animal_id": str(animal.id), "mate_id": str(wrong_kind.id)},
            "targets are not farm animals",
        ),
        (
            BreedAnimalHandler(),
            "breed-animal",
            {"animal_id": str(mate.id), "mate_id": str(animal.id)},
            "animal is already bred",
        ),
        (
            BreedAnimalHandler(),
            "breed-animal",
            {"animal_id": str(animal.id), "mate_id": str(goat.id)},
            "animals are different species",
        ),
        (
            DiscoverLadderHandler(),
            "discover-ladder",
            {"ladder_id": "not-an-id"},
            "invalid character or ladder id",
        ),
        (
            DiscoverLadderHandler(),
            "discover-ladder",
            {"ladder_id": "entity_999"},
            "ladder does not exist",
        ),
        (
            DiscoverLadderHandler(),
            "discover-ladder",
            {"ladder_id": str(distant_ladder.id)},
            "ladder is not reachable",
        ),
        (
            DiscoverLadderHandler(),
            "discover-ladder",
            {"ladder_id": str(wrong_kind.id)},
            "target is not a ladder",
        ),
        (
            OpenGeodeHandler(),
            "open-geode",
            {"geode_id": "not-an-id"},
            "invalid character or geode id",
        ),
        (OpenGeodeHandler(), "open-geode", {"geode_id": "entity_999"}, "geode does not exist"),
        (
            OpenGeodeHandler(),
            "open-geode",
            {"geode_id": str(geode_in_room.id)},
            "geode is not in inventory",
        ),
        (
            OpenGeodeHandler(),
            "open-geode",
            {"geode_id": str(not_geode.id)},
            "target is not a geode",
        ),
        (
            ClaimMailHandler(),
            "claim-mail",
            {"mail_id": "not-an-id"},
            "invalid character or mail id",
        ),
        (ClaimMailHandler(), "claim-mail", {"mail_id": "entity_999"}, "mail does not exist"),
        (
            ClaimMailHandler(),
            "claim-mail",
            {"mail_id": str(distant_mail.id)},
            "mail is not reachable",
        ),
        (
            ClaimMailHandler(),
            "claim-mail",
            {"mail_id": str(wrong_kind.id)},
            "target is not mail",
        ),
        (
            ClaimMailHandler(),
            "claim-mail",
            {"mail_id": str(claimed_mail.id)},
            "mail already claimed",
        ),
        (
            CompleteFarmQuestHandler(),
            "complete-farm-quest",
            {"quest_id": "not-an-id"},
            "invalid character or quest id",
        ),
        (
            CompleteFarmQuestHandler(),
            "complete-farm-quest",
            {"quest_id": "entity_999"},
            "quest does not exist",
        ),
        (
            CompleteFarmQuestHandler(),
            "complete-farm-quest",
            {"quest_id": str(wrong_kind.id)},
            "target is not a farm quest",
        ),
        (
            CompleteFarmQuestHandler(),
            "complete-farm-quest",
            {"quest_id": str(completed_quest.id)},
            "quest already completed",
        ),
        (
            CompleteFarmQuestHandler(),
            "complete-farm-quest",
            {"quest_id": str(hungry_quest.id)},
            "missing quest items",
        ),
        (
            ShipItemsHandler(),
            "ship-items",
            {"bin_id": "not-an-id", "resource_type": "melon"},
            "invalid character or shipping bin id",
        ),
        (
            ShipItemsHandler(),
            "ship-items",
            {"bin_id": str(shipping_bin.id)},
            "resource type is required",
        ),
        (
            ShipItemsHandler(),
            "ship-items",
            {"bin_id": str(shipping_bin.id), "resource_type": "melon", "quantity": 0},
            "quantity and unit price are invalid",
        ),
        (
            ShipItemsHandler(),
            "ship-items",
            {"bin_id": "entity_999", "resource_type": "melon"},
            "shipping bin does not exist",
        ),
        (
            ShipItemsHandler(),
            "ship-items",
            {"bin_id": str(distant_bin.id), "resource_type": "melon"},
            "shipping bin is not reachable",
        ),
        (
            ShipItemsHandler(),
            "ship-items",
            {"bin_id": str(wrong_kind.id), "resource_type": "melon"},
            "target is not a shipping bin",
        ),
        (
            ShipItemsHandler(),
            "ship-items",
            {"bin_id": str(shipping_bin.id), "resource_type": "melon"},
            "missing shipped resource",
        ),
        (
            DonateMuseumHandler(),
            "donate-museum",
            {"museum_id": "not-an-id", "resource_type": "ruby"},
            "invalid character or museum id",
        ),
        (
            DonateMuseumHandler(),
            "donate-museum",
            {"museum_id": str(museum.id)},
            "resource type is required",
        ),
        (
            DonateMuseumHandler(),
            "donate-museum",
            {"museum_id": "entity_999", "resource_type": "ruby"},
            "museum does not exist",
        ),
        (
            DonateMuseumHandler(),
            "donate-museum",
            {"museum_id": str(distant_museum.id), "resource_type": "ruby"},
            "museum is not reachable",
        ),
        (
            DonateMuseumHandler(),
            "donate-museum",
            {"museum_id": str(wrong_kind.id), "resource_type": "ruby"},
            "target is not a museum collection",
        ),
        (
            DonateMuseumHandler(),
            "donate-museum",
            {"museum_id": str(museum.id), "resource_type": "ruby"},
            "missing donation resource",
        ),
        (
            ClaimRewardHandler(),
            "claim-reward",
            {"reward_id": "not-an-id"},
            "invalid character or reward id",
        ),
        (
            ClaimRewardHandler(),
            "claim-reward",
            {"reward_id": "entity_999"},
            "reward does not exist",
        ),
        (
            ClaimRewardHandler(),
            "claim-reward",
            {"reward_id": str(distant_reward.id)},
            "reward is not reachable",
        ),
        (
            ClaimRewardHandler(),
            "claim-reward",
            {"reward_id": str(wrong_kind.id)},
            "target is not a reward",
        ),
        (
            ClaimRewardHandler(),
            "claim-reward",
            {"reward_id": str(claimed_reward.id)},
            "reward already claimed",
        ),
    ]
    for handler, command_type, payload, reason in cases:
        result = execute_handler(handler, ctx, _handler_cmd(scenario, command_type, **payload))
        assert result.ok is False
        assert result.reason == reason


def test_gardensim_fragments_cover_catalogue_state_variants():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    room = scenario.actor.world.get_entity(scenario.room_a)
    fixtures = [
        [
            IdentityComponent(name="dead bed", kind="soil"),
            SoilComponent(),
            CropComponent(crop_type="turnip", planted_at_epoch=0, dead=True),
        ],
        [
            IdentityComponent(name="ready bed", kind="soil"),
            SoilComponent(),
            CropComponent(crop_type="berry", planted_at_epoch=0, ready=True),
            PestComponent(),
            WeedComponent(),
        ],
        [
            IdentityComponent(name="tilled bed", kind="soil"),
            SoilComponent(),
            TilledComponent(tilled_at_epoch=0),
        ],
        [IdentityComponent(name="empty bed", kind="soil"), SoilComponent()],
        [
            IdentityComponent(name="dead tree", kind="tree"),
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0, dead=True),
        ],
        [
            IdentityComponent(name="young tree", kind="tree"),
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=2),
        ],
        [
            IdentityComponent(name="ready tree", kind="tree"),
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0, mature=True),
        ],
        [
            IdentityComponent(name="sap tree", kind="tree"),
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0, mature=True),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0, collection_days=1),
            HarvestableComponent(yield_item="sap", ready=True),
        ],
        [
            IdentityComponent(name="tapped tree", kind="tree"),
            TreeComponent(tree_type="oak", planted_at_epoch=0, maturity_days=0, mature=True),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0, collection_days=1),
        ],
        [
            IdentityComponent(name="broken keg", kind="machine"),
            MachineComponent(machine_type="keg"),
            MachineBreakdownComponent(),
        ],
        [
            IdentityComponent(name="ready keg", kind="machine"),
            MachineComponent(machine_type="keg"),
            ProcessingTaskComponent(
                recipe_id="juice", started_at_epoch=0, ready_at_epoch=0, ready=True
            ),
        ],
        [
            IdentityComponent(name="bred cow", kind="animal"),
            FarmAnimalComponent(species="cow"),
            AnimalProductComponent(product_type="milk", ready=True),
            AnimalBreedingComponent(),
        ],
        [IdentityComponent(name="pond", kind="water"), FishingSpotComponent(fish_type="trout")],
        [
            IdentityComponent(name="ore", kind="rock"),
            MiningNodeComponent(resource_type="copper", quantity=2),
        ],
        [IdentityComponent(name="mine", kind="mine"), MineLevelComponent(level=4)],
        [
            IdentityComponent(name="hidden ladder", kind="ladder"),
            LadderComponent(target_room_id="next"),
        ],
        [
            IdentityComponent(name="open ladder", kind="ladder"),
            LadderComponent(target_room_id="next", discovered=True),
        ],
        [
            IdentityComponent(name="geode", kind="geode"),
            GeodeComponent(resource_type="opal", quantity=2),
        ],
        [
            IdentityComponent(name="leek", kind="forage"),
            ForageComponent(resource_type="leek", quantity=1),
        ],
        [
            IdentityComponent(name="fair", kind="festival"),
            FestivalComponent(name="Fair", season="spring"),
        ],
        [
            IdentityComponent(name="open bundle", kind="bundle"),
            BundleComponent(bundle_id="spring", requirements={}),
        ],
        [
            IdentityComponent(name="done bundle", kind="bundle"),
            BundleComponent(bundle_id="fish", requirements={}, completed=True),
        ],
        [IdentityComponent(name="letter", kind="mail"), MailComponent(subject="Hello")],
        [
            IdentityComponent(name="quest", kind="quest"),
            FarmQuestComponent(quest_id="help", requested={}),
        ],
        [IdentityComponent(name="bin", kind="bin"), ShippingBinComponent(earnings=12)],
        [
            IdentityComponent(name="museum", kind="museum"),
            MuseumCollectionComponent(donated=("opal",)),
        ],
        [
            IdentityComponent(name="reward", kind="reward"),
            RewardComponent(resource_type="seed", quantity=3),
        ],
    ]
    for components in fixtures:
        entity = spawn_entity(scenario.actor.world, components)
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    replace_component(character, CollectionComponent(entries=("opal", "leek")))

    fragments = gardensim_fragments(scenario.actor.world, character)

    assert "Nearby crop: turnip in dead bed (dead)." in fragments
    assert "Nearby crop: berry in ready bed (ready, pests, weeds)." in fragments
    assert "Nearby tilled soil: tilled bed." in fragments
    assert "Nearby soil: empty bed." in fragments
    assert "Nearby tree: oak in dead tree (dead)." in fragments
    assert "Nearby tree: oak in young tree (growing)." in fragments
    assert "Nearby tree: oak in ready tree (ready to tap)." in fragments
    assert "Nearby tree: oak in sap tree (sap ready)." in fragments
    assert "Nearby tree: oak in tapped tree (tapped)." in fragments
    assert "Nearby machine: keg (broken)." in fragments
    assert "Nearby machine: keg (ready)." in fragments
    assert "Nearby animal: cow, mood 50, friendship 0, milk ready, bred." in fragments
    assert "Nearby fishing spot: trout." in fragments
    assert "Nearby mining node: copper x2." in fragments
    assert "Mine level 4." in fragments
    assert "Nearby ladder: hidden." in fragments
    assert "Nearby ladder: discovered." in fragments
    assert "Nearby geode: opal x2." in fragments
    assert "Nearby forage: leek x1." in fragments
    assert "Nearby festival: Fair (spring)." in fragments
    assert "Nearby bundle: spring (open)." in fragments
    assert "Nearby bundle: fish (complete)." in fragments
    assert "Nearby mail: Hello." in fragments
    assert "Nearby farm quest: help." in fragments
    assert "Nearby shipping bin: 12 earnings recorded." in fragments
    assert "Nearby museum collection: 1 donations." in fragments
    assert "Nearby reward: seed x3." in fragments
    assert "Collection entries: opal, leek." in fragments


def test_collection_component_first_person_fragment_empty_when_no_entries():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # First-person view but no entries -> empty fragment (line 396 guard true).
    ctx = ComponentPromptContext.for_entity(world, character, target=character)
    assert CollectionComponent(entries=()).prompt_fragments(ctx) == ()


def test_inspect_crop_notes_omit_absent_pests_and_weeds_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    # Crop with neither pests nor weeds: both note branches are skipped
    # (1341 -> 1343 and 1343 -> 1345 false).
    soil = spawn_entity(
        world,
        [
            IdentityComponent(name="clean bed", kind="soil"),
            SoilComponent(),
            CropComponent(crop_type="turnip", planted_at_epoch=0, stage=1),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id)

    result = execute_handler(
        InspectCropHandler(), ctx, _handler_cmd(scenario, "inspect", soil_id=str(soil.id))
    )
    assert result.ok
    assert soil.get_component(CropInspectionComponent).notes == "turnip stage 1"


def test_weed_and_treat_without_quality_component_skip_quality_bump_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    # Soil has weeds and pests but no CropQualityComponent: the quality bump is skipped
    # (1375 -> 1378 and 1407 -> 1410 false).
    soil = spawn_entity(
        world,
        [
            IdentityComponent(name="rough bed", kind="soil"),
            SoilComponent(),
            CropComponent(crop_type="turnip", planted_at_epoch=0),
            WeedComponent(),
            PestComponent(),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id)

    assert execute_handler(
        WeedCropHandler(), ctx, _handler_cmd(scenario, "weed-crop", soil_id=str(soil.id))
    ).ok
    assert execute_handler(
        TreatPestsHandler(), ctx, _handler_cmd(scenario, "treat-pests", soil_id=str(soil.id))
    ).ok
    assert not soil.has_component(WeedComponent)
    assert not soil.has_component(PestComponent)
    assert not soil.has_component(CropQualityComponent)


def test_weed_treat_repair_reject_unparseable_character_id_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # Unparseable character id short-circuits each handler (lines 1366, 1398, 1815).
    assert (
        execute_handler(
            WeedCropHandler(),
            ctx,
            _handler_cmd(scenario, "weed-crop", character_id="bad", soil_id="entity_1"),
        ).reason
        == "invalid character or soil id"
    )
    assert (
        execute_handler(
            TreatPestsHandler(),
            ctx,
            _handler_cmd(scenario, "treat-pests", character_id="bad", soil_id="entity_1"),
        ).reason
        == "invalid character or soil id"
    )
    assert (
        execute_handler(
            RepairMachineHandler(),
            ctx,
            _handler_cmd(scenario, "repair-machine", character_id="bad", machine_id="entity_1"),
        ).reason
        == "invalid character or machine id"
    )


def test_start_machine_rejects_broken_machine_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    # Broken machine is rejected before the busy check (line 1675).
    machine = spawn_entity(
        world,
        [
            IdentityComponent(name="cracked keg", kind="machine"),
            MachineComponent(machine_type="keg"),
            MachineBreakdownComponent(),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), machine.id)

    result = execute_handler(
        StartMachineHandler(),
        ctx,
        _handler_cmd(scenario, "start-machine", machine_id=str(machine.id), recipe_id="juice"),
    )
    assert result.ok is False
    assert result.reason == "machine is broken"


def test_repair_intact_machine_skips_breakdown_removal_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    # Machine without a breakdown component: the removal branch is skipped (1828 -> 1830).
    machine = spawn_entity(
        world,
        [
            IdentityComponent(name="sturdy keg", kind="machine"),
            MachineComponent(machine_type="keg", quality=0.2),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), machine.id)

    result = execute_handler(
        RepairMachineHandler(),
        ctx,
        _handler_cmd(scenario, "repair-machine", machine_id=str(machine.id)),
    )
    assert result.ok
    assert machine.get_component(MachineComponent).quality == 0.8


def test_claim_mail_and_complete_quest_without_reward_skip_spawn_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    # Mail with no reward: the spawn branch is skipped (2380 -> 2387).
    mail = spawn_entity(
        world,
        [IdentityComponent(name="plain note", kind="mail"), MailComponent(subject="Hi")],
    )
    # Quest with no reward and no requirements: reward spawn skipped (2436 -> 2443).
    quest = spawn_entity(
        world,
        [
            IdentityComponent(name="easy task", kind="quest"),
            FarmQuestComponent(quest_id="easy", requested={}),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), mail.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), quest.id)

    assert execute_handler(
        ClaimMailHandler(), ctx, _handler_cmd(scenario, "claim-mail", mail_id=str(mail.id))
    ).ok
    assert mail.get_component(MailComponent).claimed is True

    assert execute_handler(
        CompleteFarmQuestHandler(),
        ctx,
        _handler_cmd(scenario, "complete-farm-quest", quest_id=str(quest.id)),
    ).ok
    assert quest.get_component(FarmQuestComponent).completed is True


def test_complete_farm_quest_rejects_unreachable_quest_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    other_room = world.get_entity(scenario.room_b)
    quest = spawn_entity(
        world,
        [
            IdentityComponent(name="far task", kind="quest"),
            FarmQuestComponent(quest_id="far", requested={}),
        ],
    )
    # In another room -> not reachable (line 2414).
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), quest.id)

    result = execute_handler(
        CompleteFarmQuestHandler(),
        ctx,
        _handler_cmd(scenario, "complete-farm-quest", quest_id=str(quest.id)),
    )
    assert result.ok is False
    assert result.reason == "quest is not reachable"


def test_ship_and_donate_skip_collection_event_for_known_entry_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    # Resource is already in the character's collection, so no CollectionUpdatedEvent is
    # appended on ship (2505 -> 2515) or donate (2556 -> 2566).
    replace_component(character, CollectionComponent(entries=("ruby",)))
    shipping_bin = spawn_entity(
        world,
        [IdentityComponent(name="bin", kind="shipping"), ShippingBinComponent()],
    )
    museum = spawn_entity(
        world,
        [IdentityComponent(name="museum", kind="museum"), MuseumCollectionComponent()],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), shipping_bin.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), museum.id)
    for _ in range(2):
        stack = spawn_entity(
            world,
            [
                IdentityComponent(name="ruby", kind="resource"),
                ResourceStackComponent(resource_type="ruby", quantity=1),
                PortableComponent(can_pick_up=True),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), stack.id)

    ship_result = execute_handler(
        ShipItemsHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "ship-items",
            bin_id=str(shipping_bin.id),
            resource_type="ruby",
            quantity=1,
            unit_price=2,
        ),
    )
    assert ship_result.ok
    assert not any(isinstance(e, CollectionUpdatedEvent) for e in ship_result.events)

    donate_result = execute_handler(
        DonateMuseumHandler(),
        ctx,
        _handler_cmd(scenario, "donate-museum", museum_id=str(museum.id), resource_type="ruby"),
    )
    assert donate_result.ok
    assert not any(isinstance(e, CollectionUpdatedEvent) for e in donate_result.events)


def test_record_collection_returns_false_for_existing_entry_directly():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    replace_component(character, CollectionComponent(entries=("ruby",)))
    from bunnyland.simpacks.gardensim.mechanics import _record_collection

    # Entry already present -> returns False without changing the collection (line 819).
    assert _record_collection(world, character, "ruby") is False
    assert character.get_component(CollectionComponent).entries == ("ruby",)
    # A new entry returns True and is recorded.
    assert _record_collection(world, character, "opal") is True
    assert "opal" in character.get_component(CollectionComponent).entries


def test_plan_migration_alternate_dispatch_and_optional_operations():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    soil = spawn_entity(
        world,
        [
            IdentityComponent(name="ready bed", kind="soil"),
            CropComponent(crop_type="turnip", planted_at_epoch=0, ready=True),
            CropGrowthComponent(progress_days=1.0, required_days=1.0, last_updated_epoch=0),
            HarvestableComponent(yield_item="turnip", quantity=1, ready=True),
            WateredComponent(watered_at_epoch=0, expires_at_epoch=DAY),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id)

    inspect = InspectCropHandler()
    harvest = HarvestCropHandler()
    target_command = _handler_cmd(scenario, "inspect", target_id=str(soil.id))
    assert inspect.can_handle(ctx, target_command) is True
    assert harvest.can_handle(ctx, target_command) is True
    invalid_target = _handler_cmd(scenario, "inspect", target_id="not-an-id")
    assert inspect.can_handle(ctx, invalid_target) is False
    assert harvest.can_handle(ctx, invalid_target) is False
    missing_target = _handler_cmd(scenario, "inspect", target_id="entity_999")
    assert inspect.can_handle(ctx, missing_target) is False
    assert harvest.can_handle(ctx, missing_target) is False
    wrong_target = _handler_cmd(scenario, "inspect", target_id=str(scenario.room_a))
    assert inspect.can_handle(ctx, wrong_target) is False
    assert harvest.can_handle(ctx, wrong_target) is False

    result = execute_handler(
        harvest,
        ctx,
        _handler_cmd(scenario, "harvest", target_id=str(soil.id)),
    )
    assert result.ok is True
    assert not soil.has_component(WateredComponent)

    bait = spawn_entity(
        world,
        [
            IdentityComponent(name="bait", kind="resource"),
            ResourceStackComponent(resource_type="bait", quantity=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    spot = spawn_entity(
        world,
        [
            IdentityComponent(name="bait pond", kind="water"),
            FishingSpotComponent(fish_type="catfish", required_bait="bait"),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), bait.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), spot.id)
    result = execute_handler(
        FishHandler(),
        ctx,
        _handler_cmd(scenario, "fish", spot_id=str(spot.id)),
    )
    assert result.ok is True
    assert bait.id not in contents(character)

    install_gardensim(scenario.actor)


def test_animal_birth_skips_when_not_due_and_handles_uncontained_parent_directly():
    from bunnyland.simpacks.gardensim.mechanics import AnimalBirthConsequence

    scenario = build_scenario()
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    # Breeding not yet due -> skipped (line 1055).
    not_due = spawn_entity(
        world,
        [
            IdentityComponent(name="pending cow", kind="animal"),
            FarmAnimalComponent(species="cow"),
            AnimalBreedingComponent(due_epoch=DAY * 2),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), not_due.id)
    # Due but the parent is not in any room: offspring is created without a room link
    # (1068 -> 1072 false).
    uncontained = spawn_entity(
        world,
        [
            IdentityComponent(name="loose cow", kind="animal"),
            FarmAnimalComponent(species="cow"),
            AnimalBreedingComponent(due_epoch=0, offspring_species="cow"),
        ],
    )
    assert container_of(uncontained) is None

    events = AnimalBirthConsequence().process(world, DAY)

    assert any(isinstance(e, AnimalBornEvent) for e in events)
    assert not_due.has_component(AnimalBreedingComponent)
    assert not uncontained.has_component(AnimalBreedingComponent)
    born = next(
        entity
        for entity in world.query().with_all([FarmAnimalComponent]).execute_entities()
        if entity.get_component(IdentityComponent).name == "baby cow"
    )
    assert container_of(born) is None
