"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.core.components import (
    IdentityComponent,
)
from bunnyland.core.ecs import replace_component
from bunnyland.simpacks.dragonsim.demos import add_demo_quest
from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


async def gardensim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import PortableComponent
    from bunnyland.simpacks.gardensim.mechanics import (
        CropComponent,
        CropGrowthComponent,
        CropQualityComponent,
        FarmQuestComponent,
        GeodeComponent,
        HarvestableComponent,
        LadderComponent,
        MachineComponent,
        MailComponent,
        MineLevelComponent,
        MuseumCollectionComponent,
        PestComponent,
        RegrowableComponent,
        SeedComponent,
        ShippingBinComponent,
        SoilComponent,
        TilledComponent,
        WeedComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="farmhouse",
                title="Farmhouse",
                biome="farm",
                indoor=True,
                light=0.5,
                celsius=19.0,
            ),
            RoomSpec(key="field", title="South Field", biome="farm", light=1.0, celsius=22.0),
        ],
        exits=[
            ExitSpec(from_key="farmhouse", direction="south", to_key="field"),
            ExitSpec(from_key="field", direction="north", to_key="farmhouse"),
        ],
        characters=[
            CharacterSpec(
                key="farmer",
                name="Bracken",
                room_key="farmhouse",
                controller="suspended",
                traits=("patient",),
                goals=("bring in the harvest",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        field = world.rooms["field"]
        _add(
            actor,
            field,
            [
                IdentityComponent(name="a tilled bed", kind="soil"),
                SoilComponent(quality=1.2),
                TilledComponent(tilled_at_epoch=0),
            ],
        )
        # A carrot already sprouting partway to harvest.
        _add(
            actor,
            field,
            [
                IdentityComponent(name="sprouting carrots", kind="crop"),
                CropComponent(crop_type="carrot", planted_at_epoch=0, stage=1),
                CropGrowthComponent(progress_days=1.5, required_days=4.0, last_updated_epoch=0),
                HarvestableComponent(yield_item="carrot", quantity=3),
                CropQualityComponent(quality=1.2),
                RegrowableComponent(regrow_days=2.0),
                PestComponent(severity=0.25),
                WeedComponent(density=0.2),
            ],
        )
        _add(
            actor,
            field,
            [
                IdentityComponent(name="a packet of turnip seeds", kind="item"),
                PortableComponent(can_pick_up=True),
                SeedComponent(
                    crop_type="turnip", growth_days=5.0, yield_item="turnip", yield_quantity=2
                ),
            ],
        )
        _add(
            actor,
            field,
            [
                IdentityComponent(name="a small preserves machine", kind="machine"),
                MachineComponent(machine_type="preserves", quality=0.9),
            ],
        )
        _add(
            actor,
            field,
            [
                IdentityComponent(name="a farm shipping crate", kind="shipping-bin"),
                ShippingBinComponent(),
            ],
        )
        _add(
            actor,
            field,
            [
                IdentityComponent(name="a geode from the lower mine", kind="geode"),
                PortableComponent(can_pick_up=True),
                GeodeComponent(resource_type="amethyst", quantity=1),
            ],
        )
        _add(
            actor,
            field,
            [
                IdentityComponent(name="a ladder down to mine level two", kind="ladder"),
                LadderComponent(target_room_id=str(field)),
            ],
        )
        _augment(actor, field, MineLevelComponent(level=1))
        _add(
            actor,
            world.rooms["farmhouse"],
            [
                IdentityComponent(name="farm mail: welcome gift", kind="mail"),
                MailComponent(
                    subject="Welcome gift",
                    reward_resource="parsnip seed",
                    reward_quantity=3,
                ),
            ],
        )
        _add(
            actor,
            world.rooms["farmhouse"],
            [
                IdentityComponent(name="community board order", kind="quest"),
                FarmQuestComponent(
                    quest_id="first-harvest",
                    requested={"carrot": 2},
                    reward_resource="coin",
                    reward_quantity=25,
                ),
            ],
        )
        _add(
            actor,
            world.rooms["farmhouse"],
            [
                IdentityComponent(name="farm museum shelf", kind="museum"),
                MuseumCollectionComponent(),
            ],
        )
    return world


async def maple_farm_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import (
        DescriptionComponent,
        PortableComponent,
        WorldClockComponent,
    )
    from bunnyland.foundation.environment.mechanics import CalendarComponent, WeatherComponent
    from bunnyland.simpacks.colonysim.mechanics import (
        RecipeComponent,
        ResourceStackComponent,
        StockpileComponent,
        StorageFilterComponent,
        WorkstationComponent,
    )
    from bunnyland.simpacks.gardensim.mechanics import (
        HarvestableComponent,
        TreeComponent,
        TreeTapComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="grove", title="Quebec Maple Grove", biome="sugarbush", light=0.8, celsius=2.0
            ),
            RoomSpec(
                key="shack",
                title="Sugar Shack",
                biome="sugar-shack",
                indoor=True,
                light=0.65,
                celsius=18.0,
            ),
            RoomSpec(
                key="stand", title="Snowbank Farm Stand", biome="roadside", light=0.75, celsius=1.0
            ),
        ],
        exits=[
            ExitSpec(from_key="grove", direction="in", to_key="shack"),
            ExitSpec(from_key="shack", direction="out", to_key="grove"),
            ExitSpec(from_key="shack", direction="south", to_key="stand"),
            ExitSpec(from_key="stand", direction="north", to_key="shack"),
        ],
        objects=[
            ObjectSpec(
                key="pea_soup",
                room_key="shack",
                name="a crock of yellow pea soup",
                kind="food",
                nutrition=5.0,
                satiety=18.0,
                portable=False,
            ),
            ObjectSpec(
                key="snow_water",
                room_key="grove",
                name="a clean snowmelt barrel",
                kind="water",
                hydration=16.0,
                portable=False,
            ),
            ObjectSpec(
                key="tap_kit",
                room_key="grove",
                name="a maple tapping kit",
                kind="item",
                portable=True,
            ),
            ObjectSpec(
                key="ledger",
                room_key="shack",
                name="a syrup season ledger",
                kind="paper",
                portable=True,
            ),
            ObjectSpec(
                key="cash_box",
                room_key="stand",
                name="a locked wooden cash box",
                kind="container",
                portable=False,
                open=False,
            ),
        ],
        characters=[
            CharacterSpec(
                key="syrupmaker",
                name="Camille Lavoie",
                room_key="grove",
                controller="suspended",
                traits=("patient", "weather-wise"),
                goals=("tap the ready maples", "bring sap to the sugar shack"),
            ),
            CharacterSpec(
                key="neighbor",
                name="Noah Tremblay",
                room_key="stand",
                controller="llm",
                llm_profile="maple-neighbor",
                traits=("practical", "talkative"),
                goals=("trade for the first syrup of the season",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            clock[0].add_component(CalendarComponent(season="spring", day=38))
            clock[0].add_component(WeatherComponent(condition="freeze-thaw", intensity=0.2))

        grove = world.rooms["grove"]
        _augment(
            actor, grove, DescriptionComponent(short="A Canadian sugarbush waits in thawing snow.")
        )
        _add(
            actor,
            grove,
            [
                IdentityComponent(name="a young sugar maple", kind="tree"),
                TreeComponent(tree_type="sugar maple", planted_at_epoch=0, maturity_days=1.0),
            ],
        )
        _add(
            actor,
            grove,
            [
                IdentityComponent(name="a ready sugar maple", kind="tree"),
                TreeComponent(
                    tree_type="sugar maple", planted_at_epoch=0, maturity_days=0.0, mature=True
                ),
            ],
        )
        _add(
            actor,
            grove,
            [
                IdentityComponent(name="a tapped roadside maple", kind="tree"),
                TreeComponent(
                    tree_type="sugar maple", planted_at_epoch=0, maturity_days=0.0, mature=True
                ),
                TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0, collection_days=1.0),
                HarvestableComponent(yield_item="maple sap", quantity=4, ready=False),
            ],
        )
        _add(
            actor,
            world.rooms["shack"],
            [
                IdentityComponent(name="a wood-fired evaporator", kind="workstation"),
                WorkstationComponent(station_type="evaporator"),
            ],
        )
        _add(
            actor,
            world.rooms["shack"],
            [
                IdentityComponent(name="maple syrup recipe", kind="recipe"),
                RecipeComponent(
                    recipe_id="maple-syrup",
                    inputs={"maple sap": 4},
                    outputs={"maple syrup": 1},
                    required_station="evaporator",
                ),
            ],
        )
        _add(
            actor,
            world.rooms["shack"],
            [
                IdentityComponent(name="a sap stockpile", kind="stockpile"),
                StockpileComponent(capacity=32),
                StorageFilterComponent(allowed_types=("maple sap", "maple syrup")),
            ],
        )
        _add(
            actor,
            world.rooms["shack"],
            [
                IdentityComponent(name="a starter pail of maple sap", kind="resource"),
                PortableComponent(can_pick_up=True),
                ResourceStackComponent(resource_type="maple sap", quantity=4),
            ],
        )
        _add(
            actor,
            world.rooms["stand"],
            [
                IdentityComponent(name="a display of amber maple syrup", kind="resource"),
                PortableComponent(can_pick_up=True),
                ResourceStackComponent(resource_type="maple syrup", quantity=2),
            ],
        )
    return world


async def frozen_greenhouse_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A greenhouse dome on a frozen plain, fighting the cold around a too-eager specimen."""

    del options
    from bunnyland.core.components import (
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from bunnyland.foundation.environment.mechanics import (
        CalendarComponent,
        TimeOfDayComponent,
        WeatherComponent,
    )
    from bunnyland.simpacks.colonysim.mechanics import (
        JobComponent,
        ResourceStackComponent,
        StockpileComponent,
        WorkstationComponent,
    )
    from bunnyland.simpacks.dragonsim.mechanics import DiscoveryComponent, PointOfInterestComponent
    from bunnyland.simpacks.gardensim.mechanics import (
        CropComponent,
        CropGrowthComponent,
        CropQualityComponent,
        HarvestableComponent,
        SeedComponent,
        ShippingBinComponent,
        SoilComponent,
        TilledComponent,
    )

    # Day 88 at 10:00 is an overcast winter day, so the season and sky stay bleak as it ticks.
    winter_morning_seconds = 87 * 24 * 3600 + 10 * 3600

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="tundra", title="Wind-Scoured Tundra", biome="tundra", light=0.6, celsius=-24.0
            ),
            RoomSpec(
                key="dome",
                title="Geodesic Greenhouse Dome",
                biome="greenhouse",
                indoor=True,
                light=0.9,
                celsius=19.0,
            ),
            RoomSpec(
                key="boiler",
                title="Boiler and Seed Vault",
                biome="greenhouse",
                indoor=True,
                light=0.5,
                celsius=11.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="tundra", direction="in", to_key="dome"),
            ExitSpec(from_key="dome", direction="out", to_key="tundra"),
            ExitSpec(from_key="dome", direction="down", to_key="boiler"),
            ExitSpec(from_key="boiler", direction="up", to_key="dome"),
        ],
        objects=[
            ObjectSpec(
                key="greens",
                room_key="boiler",
                name="a tray of ration greens",
                kind="food",
                nutrition=4.0,
                satiety=12.0,
                portable=True,
            ),
            ObjectSpec(
                key="meltwater",
                room_key="boiler",
                name="a meltwater tank",
                kind="water",
                hydration=15.0,
                portable=False,
            ),
            ObjectSpec(
                key="peat",
                room_key="boiler",
                name="a sack of dried peat fuel",
                kind="item",
                portable=True,
            ),
            ObjectSpec(
                key="journal",
                room_key="boiler",
                name="a station research journal",
                kind="paper",
                writable=True,
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="botanist",
                name="Dr. Imala Sorn",
                room_key="dome",
                controller="suspended",
                traits=("meticulous", "cold-numbed", "uneasy"),
                goals=("keep the dome above freezing", "catalogue the new specimen"),
            ),
            CharacterSpec(
                key="tech",
                name="Bo Anders",
                room_key="boiler",
                controller="llm",
                llm_profile="station-tech",
                traits=("practical", "tired"),
                goals=("keep the boiler fed", "stop the specimen spreading"),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(
                clock[0], WorldClockComponent(game_time_seconds=winter_morning_seconds)
            )
            clock[0].add_component(TimeOfDayComponent(phase="day"))
            clock[0].add_component(CalendarComponent(day=88, season="winter", hour=10))
            clock[0].add_component(WeatherComponent(condition="overcast", intensity=0.5))

        dome, boiler = world.rooms["dome"], world.rooms["boiler"]
        _add(
            actor,
            dome,
            [
                IdentityComponent(name="a raised bed of warmed soil", kind="soil"),
                SoilComponent(quality=1.1),
                TilledComponent(tilled_at_epoch=0),
            ],
        )
        # An ordinary winter crop, growing at a sane pace.
        _add(
            actor,
            dome,
            [
                IdentityComponent(name="a row of winter kale", kind="crop"),
                CropComponent(crop_type="kale", planted_at_epoch=0, stage=1),
                CropGrowthComponent(progress_days=1.0, required_days=6.0, last_updated_epoch=0),
                HarvestableComponent(yield_item="kale", quantity=3),
                CropQualityComponent(quality=1.0),
            ],
        )
        # The specimen: it should not grow in this cold, in the dark, this fast.
        _augment(
            actor,
            dome,
            PointOfInterestComponent(location_type="quarantine bed", region="Station Drift-9"),
            DiscoveryComponent(),
        )
        _add(
            actor,
            dome,
            [
                IdentityComponent(name="a pale specimen that grew overnight", kind="crop"),
                CropComponent(crop_type="specimen", planted_at_epoch=0, stage=2),
                CropGrowthComponent(progress_days=0.4, required_days=0.5, last_updated_epoch=0),
                HarvestableComponent(yield_item="spore pod", quantity=4),
                CropQualityComponent(quality=1.6),
            ],
        )
        _add(
            actor,
            boiler,
            [
                IdentityComponent(name="a packet of saved seed", kind="item"),
                PortableComponent(can_pick_up=True),
                SeedComponent(
                    crop_type="kale", growth_days=6.0, yield_item="kale", yield_quantity=3
                ),
            ],
        )
        _add(
            actor,
            boiler,
            [
                IdentityComponent(name="the dome boiler", kind="workstation"),
                WorkstationComponent(station_type="boiler"),
            ],
        )
        _add(
            actor,
            boiler,
            [
                IdentityComponent(name="stoke the boiler job", kind="job"),
                JobComponent(job_type="haul", priority=4),
            ],
        )
        _add(
            actor,
            boiler,
            [
                IdentityComponent(name="a peat fuel bin", kind="stockpile"),
                StockpileComponent(capacity=20),
                ResourceStackComponent(resource_type="peat", quantity=9),
            ],
        )
        _add(
            actor,
            dome,
            [
                IdentityComponent(name="a frosted harvest crate", kind="shipping-bin"),
                ShippingBinComponent(),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["journal"]),
            ReadableComponent(
                title="Research Journal",
                text="Specimen doubled again with the heat off and the sun down. "
                "It does not need us. Recommend we stop feeding the bed.",
            ),
        )
    return world


async def county_fair_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """Closing night of a county fair: a pie contest, a prize pumpkin, and a blue ribbon."""

    del options
    from bunnyland.core.components import ReadableComponent, WorldClockComponent
    from bunnyland.foundation.environment.mechanics import CalendarComponent, TimeOfDayComponent
    from bunnyland.simpacks.gardensim.mechanics import (
        CropComponent,
        CropGrowthComponent,
        CropQualityComponent,
        HarvestableComponent,
        ShippingBinComponent,
    )

    # Day 57 at 19:00 is a clear autumn dusk, so the harvest-season closing night holds.
    fair_dusk_seconds = 56 * 24 * 3600 + 19 * 3600

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="midway", title="Fairground Midway", biome="fairground", light=0.4, celsius=16.0
            ),
            RoomSpec(
                key="hall",
                title="Exhibition Hall",
                biome="fairground",
                indoor=True,
                light=0.7,
                celsius=20.0,
            ),
            RoomSpec(
                key="barn",
                title="Livestock Barn",
                biome="fairground",
                indoor=True,
                light=0.5,
                celsius=18.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="midway", direction="in", to_key="hall"),
            ExitSpec(from_key="hall", direction="out", to_key="midway"),
            ExitSpec(from_key="hall", direction="barn", to_key="barn"),
            ExitSpec(from_key="barn", direction="hall", to_key="hall"),
        ],
        objects=[
            ObjectSpec(
                key="pie",
                room_key="hall",
                name="a blue-ribbon contender pie",
                kind="food",
                nutrition=5.0,
                satiety=16.0,
                portable=True,
            ),
            ObjectSpec(
                key="lemonade",
                room_key="midway",
                name="a cup of fresh lemonade",
                kind="water",
                hydration=13.0,
                portable=True,
            ),
            ObjectSpec(
                key="ferris",
                room_key="midway",
                name="the lit Ferris wheel",
                kind="item",
                portable=False,
            ),
            ObjectSpec(
                key="ribbon",
                room_key="hall",
                name="an unawarded blue ribbon",
                kind="item",
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="grower",
                name="Hattie Boone",
                room_key="hall",
                controller="suspended",
                traits=("proud", "nervous", "green-thumbed"),
                goals=("win the blue ribbon", "outgrow her rival's entry"),
            ),
            CharacterSpec(
                key="judge",
                name="Inez Coulter",
                room_key="hall",
                controller="llm",
                llm_profile="fair-judge",
                traits=("fair", "theatrical"),
                goals=("crown a winner before the lights go out",),
            ),
            CharacterSpec(
                key="rival",
                name="Cyrus Webb",
                room_key="barn",
                controller="llm",
                llm_profile="fair-rival",
                traits=("smug", "competitive"),
                goals=("take the ribbon from Hattie", "show off his prize hog"),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(clock[0], WorldClockComponent(game_time_seconds=fair_dusk_seconds))
            clock[0].add_component(TimeOfDayComponent(phase="dusk"))
            clock[0].add_component(CalendarComponent(day=57, season="autumn", hour=19))

        hall = world.rooms["hall"]
        # The star entry: a prize pumpkin grown to championship quality.
        _add(
            actor,
            hall,
            [
                IdentityComponent(name="a championship prize pumpkin", kind="crop"),
                CropComponent(crop_type="pumpkin", planted_at_epoch=0, stage=3),
                CropGrowthComponent(progress_days=120.0, required_days=120.0, last_updated_epoch=0),
                HarvestableComponent(yield_item="pumpkin", quantity=1),
                CropQualityComponent(quality=2.0),
            ],
        )
        # The judging table where entries are weighed and scored.
        _add(
            actor,
            hall,
            [
                IdentityComponent(name="the judging entry table", kind="shipping-bin"),
                ShippingBinComponent(),
            ],
        )
        # The blue-ribbon quest, still up for grabs on closing night.
        add_demo_quest(
            actor,
            hall,
            "blue-ribbon",
            "Win the Blue Ribbon",
            "Enter the best produce before judging closes",
            "the county fair blue ribbon and bragging rights",
        )
        replace_component(
            actor.world.get_entity(world.objects["ribbon"]),
            ReadableComponent(
                title="Blue Ribbon",
                text="FIRST PLACE — to be pinned to the winning entry at the close "
                "of judging. The card beneath it is still blank.",
            ),
        )
    return world


GARDENSIM_DEMO = WorldGenerator(
    name="gardensim-demo",
    generate=_with_regions(
        gardensim_example, (("Greenhollow", "region"), ("Bramblewick Farm", "area"))
    ),
    description="A farm with tilled soil, a growing crop, and seeds.",
    group="simpack sandbox",
    uses_seed=False,
)

MAPLE_FARM_DEMO = WorldGenerator(
    name="maple-farm-demo",
    generate=_with_regions(
        maple_farm_example, (("Laurentian Uplands", "region"), ("Snowbank Farm", "area"))
    ),
    description="A Canadian maple syrup farm with trees to wait for, tap, and harvest sap from.",
    group="simpack sandbox",
    uses_seed=False,
)

FROZEN_GREENHOUSE_DEMO = WorldGenerator(
    name="frozen-greenhouse-demo",
    generate=_with_regions(
        frozen_greenhouse_example, (("Borealis Flats", "region"), ("Dome Station 7", "building"))
    ),
    description="A greenhouse dome on a frozen winter plain with crops to keep warm, a boiler "
    "to stoke, and a specimen that grows too fast in the dark and cold.",
    group="scene demo",
    uses_seed=False,
)

COUNTY_FAIR_DEMO = WorldGenerator(
    name="county-fair-demo",
    generate=_with_regions(
        county_fair_example, (("Harvest County", "region"), ("County Fairgrounds", "zone"))
    ),
    description="A closing night at an autumn county fair, with a pie contest, a championship "
    "prize pumpkin, a smug rival, and a blue ribbon still up for grabs.",
    group="scene demo",
    uses_seed=False,
)
