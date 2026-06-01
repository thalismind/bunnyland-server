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
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.environment import CalendarComponent
from bunnyland.mechanics.gardensim import (
    CropComponent,
    CropGrewEvent,
    CropGrowthComponent,
    CropGrowthConsequence,
    CropHarvestedEvent,
    CropReadyEvent,
    FertilizeHandler,
    FertilizerComponent,
    HarvestableComponent,
    HarvestCropHandler,
    PlantHandler,
    SeedComponent,
    SoilComponent,
    SoilTilledEvent,
    TillHandler,
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
    actor.register_consequence(CropGrowthConsequence())


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


def _soil(scenario, name="garden bed"):
    soil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="soil"), SoilComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id
    )
    return soil.id


def _seed(scenario, crop_type="turnip", growth_days=1.0):
    seed = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{crop_type} seeds", kind="seed"),
            SeedComponent(
                crop_type=crop_type,
                growth_days=growth_days,
                yield_item=crop_type,
                yield_quantity=2,
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
    assert container_of(item) == scenario.character


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


async def test_crop_withers_out_of_season():
    scenario = build_scenario()
    _install(scenario.actor)
    soil = _soil(scenario)
    seed = _seed(scenario)
    clock = list(
        scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities()
    )[0]
    clock.add_component(CalendarComponent(season="winter"))

    await scenario.actor.submit(_cmd(scenario, "till", soil_id=str(soil)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "plant", soil_id=str(soil), seed_id=str(seed)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(0.0)

    soil_entity = scenario.actor.world.get_entity(soil)
    assert soil_entity.get_component(CropComponent).dead is True


def test_gardensim_fragments_show_nearby_crop_state():
    scenario = build_scenario()
    soil = scenario.actor.world.get_entity(_soil(scenario))
    soil.add_component(CropComponent(crop_type="turnip", planted_at_epoch=0, stage=2))

    fragments = gardensim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("Nearby crop: turnip" in line for line in fragments)
