"""Tests for garden-sim soil, crop growth, and harvest."""

from __future__ import annotations

from conftest import build_scenario

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
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.mechanics.colonysim import ResourceStackComponent
from bunnyland.mechanics.consumables import FoodComponent
from bunnyland.mechanics.environment import CalendarComponent
from bunnyland.mechanics.gardensim import (
    AnimalProductCollectedEvent,
    AnimalProductComponent,
    BundleComponent,
    ClearDeadCropHandler,
    CollectAnimalProductHandler,
    CollectMachineOutputHandler,
    ContributeBundleHandler,
    CropComponent,
    CropGrewEvent,
    CropGrowthComponent,
    CropGrowthConsequence,
    CropHarvestedEvent,
    CropReadyEvent,
    DeadCropClearedEvent,
    FarmAnimalComponent,
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
    GiftPreferenceComponent,
    GiveGiftHandler,
    GreenhouseComponent,
    HarvestableComponent,
    HarvestCropHandler,
    HarvestSapHandler,
    JoinFestivalHandler,
    MachineComponent,
    MachineOutputCollectedEvent,
    MineHandler,
    MiningNodeComponent,
    PetAnimalHandler,
    PlantHandler,
    ProcessingRecipeComponent,
    ProcessingTaskComponent,
    SapHarvestedEvent,
    SapReadyEvent,
    SeedComponent,
    SoilComponent,
    SoilTilledEvent,
    StartMachineHandler,
    TapTreeHandler,
    TilledComponent,
    TillHandler,
    TreeComponent,
    TreeGrowthConsequence,
    TreeMaturedEvent,
    TreeTapComponent,
    TreeTappedEvent,
    WaterCropHandler,
    gardensim_fragments,
)

DAY = 24 * 60 * 60
HOUR = 60 * 60


def _install(actor):
    actor.register_handler(TillHandler())
    actor.register_handler(PlantHandler())
    actor.register_handler(WaterCropHandler())
    actor.register_handler(FertilizeHandler())
    actor.register_handler(HarvestCropHandler())
    actor.register_handler(ClearDeadCropHandler())
    actor.register_handler(TapTreeHandler())
    actor.register_handler(HarvestSapHandler())
    actor.register_handler(StartMachineHandler())
    actor.register_handler(CollectMachineOutputHandler())
    actor.register_handler(FeedAnimalHandler())
    actor.register_handler(PetAnimalHandler())
    actor.register_handler(CollectAnimalProductHandler())
    actor.register_handler(FishHandler())
    actor.register_handler(MineHandler())
    actor.register_handler(ForageHandler())
    actor.register_handler(GiveGiftHandler())
    actor.register_handler(JoinFestivalHandler())
    actor.register_handler(ContributeBundleHandler())
    actor.register_consequence(CropGrowthConsequence())
    actor.register_consequence(TreeGrowthConsequence())
    from bunnyland.mechanics.gardensim import (
        AnimalProductConsequence,
        DailyFarmResetConsequence,
        MachineProcessingConsequence,
    )

    actor.register_consequence(MachineProcessingConsequence())
    actor.register_consequence(AnimalProductConsequence())
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

    await scenario.actor.submit(_cmd(scenario, "harvest-crop", soil_id=str(soil)))
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
    await scenario.actor.submit(_cmd(scenario, "harvest-crop", soil_id=str(soil)))
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
    await scenario.actor.submit(_cmd(scenario, "harvest-crop", soil_id=str(soil)))
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

    await scenario.actor.submit(_cmd(scenario, "harvest-sap", tree_id=str(tree)))
    await scenario.actor.tick(HOUR)

    assert rejects[-1].reason == "sap is not ready"

    await scenario.actor.tick(DAY)

    assert ready[0].tree_id == str(tree)
    assert tree_entity.get_component(HarvestableComponent).ready is True

    await scenario.actor.submit(_cmd(scenario, "harvest-sap", tree_id=str(tree)))
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
    clock = list(
        scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities()
    )[0]
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
    assert str(scenario.character) in festival.get_component(FestivalComponent).joined_character_ids
    assert bundle.get_component(BundleComponent).completed is True


async def test_planting_respects_seed_season_unless_soil_is_greenhouse():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    winter_seed = _seed(scenario, "snow yam", seasons=("winter",))
    spring_seed = _seed(scenario, "turnip", seasons=("spring",))
    clock = list(
        scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities()
    )[0]
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
    clock = list(
        scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities()
    )[0]
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
            _handler_cmd(scenario, "harvest-crop", soil_id=str(distant_soil.id)),
            "soil is not reachable",
        ),
        (
            HarvestCropHandler(),
            _handler_cmd(scenario, "harvest-crop", soil_id=str(soil.id)),
            "soil has no harvestable crop",
        ),
        (
            HarvestCropHandler(),
            _handler_cmd(scenario, "harvest-crop", soil_id=str(dead_soil.id)),
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
            _handler_cmd(scenario, "harvest-sap", character_id="not-an-id",
                         tree_id=str(tapped_tree.id)),
            "invalid character or tree id",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest-sap", tree_id="entity_999"),
            "tree does not exist",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest-sap", tree_id=str(distant_tree.id)),
            "tree is not reachable",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest-sap", tree_id=str(wrong_kind.id)),
            "target is not a tree",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest-sap", tree_id=str(dead_tree.id)),
            "tree is dead",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest-sap", tree_id=str(mature_tree.id)),
            "tree is not tapped",
        ),
        (
            HarvestSapHandler(),
            _handler_cmd(scenario, "harvest-sap", tree_id=str(tapped_tree.id)),
            "sap is not ready",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


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
