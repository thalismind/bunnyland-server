"""Hand-built example worlds, one per sim package (spec 21.4, 28.2).

Each generator lays down a small base world (rooms + life-sim characters with needs and
memory) via the same ``instantiate`` path the LLM uses, then layers on the components and
entities that show off its sim package. They are deterministic and dependency-free, so
``serve --generator voidsim-demo`` (etc.) spins up a scene a human can claim and play, and
the web inspector has something representative to show.

Demos may freely use features from the package's required/recommended dependencies — most
build on life-sim needs, which every character already gets from ``instantiate``.
"""

from __future__ import annotations

from ..core.ecs import spawn_entity
from ..core.edges import ContainmentMode, Contains
from .generators import GenOptions, WorldGenerator
from .instantiate import InstantiatedWorld, instantiate
from .proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


def _add(actor, room_id, components):
    """Spawn an entity carrying ``components`` and place it in ``room_id``."""
    entity = spawn_entity(actor.world, components)
    actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


def _augment(actor, entity_id, *components):
    entity = actor.world.get_entity(entity_id)
    for component in components:
        entity.add_component(component)
    return entity


# --------------------------------------------------------------------------------------
# life-sim — The Sims: needs, careers, money, relationships, aspirations
# --------------------------------------------------------------------------------------


async def lifesim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..mechanics.lifesim import (
        AspirationComponent,
        CareerComponent,
        HouseholdFundsComponent,
        PartnerOf,
        RelationshipStatus,
        SkillSetComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="cottage", title="Clover Cottage", biome="meadow", indoor=True,
                     light=0.6, celsius=20.0),
            RoomSpec(key="yard", title="Front Yard", biome="meadow", light=0.9, celsius=18.0),
        ],
        exits=[
            ExitSpec(from_key="cottage", direction="out", to_key="yard"),
            ExitSpec(from_key="yard", direction="in", to_key="cottage"),
        ],
        objects=[
            ObjectSpec(key="stew", room_key="cottage", name="a pot of clover stew",
                       kind="food", nutrition=6.0, satiety=30.0, portable=False),
            ObjectSpec(key="well", room_key="yard", name="a stone well", kind="water",
                       portable=False, hydration=30.0),
        ],
        characters=[
            CharacterSpec(key="juniper", name="Juniper", room_key="cottage",
                          controller="suspended", traits=("warm", "ambitious")),
            CharacterSpec(key="hazel", name="Hazel", room_key="cottage", controller="llm",
                          llm_profile="partner", traits=("playful",),
                          goals=("grow the household",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        juniper, hazel = world.characters["juniper"], world.characters["hazel"]
        _augment(actor, juniper,
                 CareerComponent(title="gardener", level=2, hourly_pay=14),
                 SkillSetComponent(levels={"gardening": 3, "cooking": 1}),
                 AspirationComponent(name="Master Gardener",
                                     milestones=("ten harvests", "a prize bloom")),
                 HouseholdFundsComponent(balance=140))
        _augment(actor, hazel,
                 CareerComponent(title="baker", level=1, hourly_pay=11),
                 SkillSetComponent(levels={"baking": 2}),
                 AspirationComponent(name="Village Baker", milestones=("open a stall",)))
        # A married couple: partner edges both ways plus a shared relationship status.
        actor.world.get_entity(juniper).add_relationship(PartnerOf(since_epoch=0), hazel)
        actor.world.get_entity(hazel).add_relationship(PartnerOf(since_epoch=0), juniper)
        actor.world.get_entity(juniper).add_relationship(
            RelationshipStatus(status="married", since_epoch=0), hazel
        )
    return world


# --------------------------------------------------------------------------------------
# garden-sim — Stardew Valley: soil, planting, crop growth, seeds
# --------------------------------------------------------------------------------------


async def gardensim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent, PortableComponent
    from ..mechanics.gardensim import (
        CropComponent,
        CropGrowthComponent,
        HarvestableComponent,
        SeedComponent,
        SoilComponent,
        TilledComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="farmhouse", title="Farmhouse", biome="farm", indoor=True,
                     light=0.5, celsius=19.0),
            RoomSpec(key="field", title="South Field", biome="farm", light=1.0, celsius=22.0),
        ],
        exits=[
            ExitSpec(from_key="farmhouse", direction="south", to_key="field"),
            ExitSpec(from_key="field", direction="north", to_key="farmhouse"),
        ],
        characters=[
            CharacterSpec(key="farmer", name="Bracken", room_key="farmhouse",
                          controller="suspended", traits=("patient",),
                          goals=("bring in the harvest",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        field = world.rooms["field"]
        _add(actor, field, [
            IdentityComponent(name="a tilled bed", kind="soil"),
            SoilComponent(quality=1.2),
            TilledComponent(tilled_at_epoch=0),
        ])
        # A carrot already sprouting partway to harvest.
        _add(actor, field, [
            IdentityComponent(name="sprouting carrots", kind="crop"),
            CropComponent(crop_type="carrot", planted_at_epoch=0, stage=1),
            CropGrowthComponent(progress_days=1.5, required_days=4.0, last_updated_epoch=0),
            HarvestableComponent(yield_item="carrot", quantity=3),
        ])
        _add(actor, field, [
            IdentityComponent(name="a packet of turnip seeds", kind="item"),
            PortableComponent(can_pick_up=True),
            SeedComponent(crop_type="turnip", growth_days=5.0, yield_item="turnip",
                          yield_quantity=2),
        ])
    return world


# --------------------------------------------------------------------------------------
# colony-sim — RimWorld: resource nodes, stockpiles, workstations, recipes, jobs
# --------------------------------------------------------------------------------------


async def colonysim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent, PortableComponent
    from ..mechanics.colonysim import (
        JobComponent,
        RecipeComponent,
        ResourceNodeComponent,
        ResourceStackComponent,
        WorkstationComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="camp", title="Forest Camp", biome="forest", light=0.8, celsius=16.0),
            RoomSpec(key="store", title="Storeroom", biome="forest", indoor=True,
                     light=0.4, celsius=15.0),
        ],
        exits=[
            ExitSpec(from_key="camp", direction="in", to_key="store"),
            ExitSpec(from_key="store", direction="out", to_key="camp"),
        ],
        characters=[
            CharacterSpec(key="rowan", name="Rowan", room_key="camp", controller="suspended",
                          traits=("industrious",)),
            CharacterSpec(key="fern", name="Fern", room_key="camp", controller="llm",
                          llm_profile="worker", goals=("stock the storeroom",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        camp, store = world.rooms["camp"], world.rooms["store"]
        _add(actor, camp, [
            IdentityComponent(name="a berry bush", kind="resource-node"),
            ResourceNodeComponent(resource_type="berries", current=20, maximum=20,
                                  regen_per_day=6.0),
        ])
        _add(actor, camp, [
            IdentityComponent(name="a carpentry bench", kind="workstation"),
            WorkstationComponent(station_type="workbench"),
        ])
        _add(actor, camp, [
            IdentityComponent(name="plank recipe", kind="recipe"),
            RecipeComponent(recipe_id="plank", inputs={"wood": 2}, outputs={"plank": 1},
                            required_station="workbench"),
        ])
        _add(actor, store, [
            IdentityComponent(name="a stack of logs", kind="resource"),
            PortableComponent(can_pick_up=True),
            ResourceStackComponent(resource_type="wood", quantity=8),
        ])
        _add(actor, store, [
            IdentityComponent(name="hauling job", kind="job"),
            JobComponent(job_type="haul", priority=3),
        ])
    return world


# --------------------------------------------------------------------------------------
# barbarian-sim — Conan Exiles: harsh cold, stamina, gear, corruption, shelter
# --------------------------------------------------------------------------------------


async def barbariansim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent, PortableComponent
    from ..mechanics.barbariansim import (
        ArmorComponent,
        CorruptionComponent,
        DurabilityComponent,
        ShelterComponent,
        StaminaComponent,
        TemperatureResistanceComponent,
        WeaponComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="ridge", title="Frozen Ridge", biome="tundra", light=0.7,
                     celsius=-12.0),
            RoomSpec(key="cave", title="Sheltered Cave", biome="tundra", indoor=True,
                     light=0.2, celsius=4.0),
        ],
        exits=[
            ExitSpec(from_key="ridge", direction="in", to_key="cave"),
            ExitSpec(from_key="cave", direction="out", to_key="ridge"),
        ],
        characters=[
            CharacterSpec(key="kell", name="Kell", room_key="cave", controller="suspended",
                          traits=("hardy", "grim"), goals=("survive the cold",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        ridge, cave = world.rooms["ridge"], world.rooms["cave"]
        _augment(actor, cave, ShelterComponent(temperature_buffer=12.0))
        _augment(actor, world.characters["kell"],
                 StaminaComponent(current=8.0, maximum=10.0),
                 CorruptionComponent(amount=3.0),
                 TemperatureResistanceComponent(cold=0.25))
        _add(actor, cave, [
            IdentityComponent(name="a bone axe", kind="weapon"),
            PortableComponent(can_pick_up=True),
            WeaponComponent(damage=7.0, damage_type="slashing", lethal_capable=True),
            DurabilityComponent(current=38.0, maximum=50.0),
        ])
        _add(actor, ridge, [
            IdentityComponent(name="a hide jerkin", kind="armor"),
            PortableComponent(can_pick_up=True),
            ArmorComponent(rating=3.0),
            DurabilityComponent(current=44.0, maximum=50.0),
        ])
    return world


# --------------------------------------------------------------------------------------
# dragon-sim — Skyrim: discovery, factions, radiant quests, reputation
# --------------------------------------------------------------------------------------


async def dragonsim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent
    from ..mechanics.dragonsim import (
        DiscoveryComponent,
        FactionComponent,
        FactionReputationComponent,
        PointOfInterestComponent,
        QuestComponent,
        QuestObjectiveComponent,
        QuestRewardComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="village", title="Mistmoor Village", biome="highland", light=0.7,
                     celsius=12.0),
            RoomSpec(key="ruin", title="Sunken Barrow", biome="ruin", indoor=True, light=0.1,
                     celsius=6.0),
        ],
        exits=[
            ExitSpec(from_key="village", direction="east", to_key="ruin"),
            ExitSpec(from_key="ruin", direction="west", to_key="village"),
        ],
        characters=[
            CharacterSpec(key="aldric", name="Aldric", room_key="village",
                          controller="suspended", traits=("bold",),
                          goals=("explore the barrow",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        village, ruin = world.rooms["village"], world.rooms["ruin"]
        _augment(actor, ruin,
                 PointOfInterestComponent(location_type="barrow", region="Mistmoor"),
                 DiscoveryComponent())
        _add(actor, village, [
            IdentityComponent(name="the Moss Wardens", kind="faction"),
            FactionComponent(name="Moss Wardens", ideology="guard the old marsh"),
        ])
        _add(actor, village, [
            IdentityComponent(name="Clear the Barrow", kind="quest"),
            QuestComponent(quest_id="barrow", title="Clear the Barrow", status="offered"),
            QuestObjectiveComponent(quest_id="barrow", description="Reach the inner sanctum"),
            QuestRewardComponent(quest_id="barrow", description="an ancient relic"),
        ])
        _augment(actor, world.characters["aldric"],
                 FactionReputationComponent(scores={"Moss Wardens": 5}))
    return world


# --------------------------------------------------------------------------------------
# dagger-sim — Daggerfall: towns, guilds, banks, rumors, travel, expandable frontier
# --------------------------------------------------------------------------------------


async def daggersim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent
    from ..mechanics.daggersim import (
        BankComponent,
        EtiquetteSkillComponent,
        ExpansionHookComponent,
        InstitutionComponent,
        LawRegionComponent,
        ProceduralSiteComponent,
        RumorComponent,
        TravelHubComponent,
        TravelRoute,
        UnrealizedLocationComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="square", title="Town Square", biome="town", light=0.9, celsius=15.0),
            RoomSpec(key="road", title="Moss Road", biome="road", light=0.8, celsius=14.0),
        ],
        exits=[
            ExitSpec(from_key="square", direction="north", to_key="road"),
            ExitSpec(from_key="road", direction="south", to_key="square"),
        ],
        characters=[
            CharacterSpec(key="wren", name="Wren", room_key="square", controller="suspended",
                          traits=("curious",), goals=("make a name in town",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        square, road = world.rooms["square"], world.rooms["road"]
        _augment(actor, square, LawRegionComponent(region_id="moss-road",
                                                    fines={"theft": 20, "default": 10}))
        _add(actor, square, [
            IdentityComponent(name="Carrot Factors Bank", kind="bank"),
            BankComponent(name="Carrot Factors Bank", region_id="moss-road"),
        ])
        _add(actor, square, [
            IdentityComponent(name="Burrow Cartographers", kind="institution"),
            InstitutionComponent(name="Burrow Cartographers", institution_type="guild"),
        ])
        _add(actor, square, [
            IdentityComponent(name="a tavern rumor", kind="rumor"),
            RumorComponent(text="A vault lies beneath the old hamlet down the road."),
        ])
        # An unrealized hamlet down the road, ready for worldgen to expand on demand.
        _add(actor, road, [
            IdentityComponent(name="Rain Garden Hamlet", kind="settlement"),
            ProceduralSiteComponent(site_type="hamlet", seed="rain-garden"),
            UnrealizedLocationComponent(summary="a damp trading stop at the road's edge",
                                        region_id="moss-road"),
            ExpansionHookComponent(trigger="rumor", generator_plugin_id="worldgen.recursive"),
        ])
        # Travel hubs so the square and road form a route.
        actor.world.get_entity(square).add_component(
            TravelHubComponent(name="Town Square", region_id="moss-road"))
        actor.world.get_entity(road).add_component(
            TravelHubComponent(name="Moss Road", region_id="moss-road"))
        actor.world.get_entity(square).add_relationship(
            TravelRoute(travel_seconds=2 * 60 * 60, label="moss road"), road)
        _augment(actor, world.characters["wren"], EtiquetteSkillComponent(level=2))
    return world


# --------------------------------------------------------------------------------------
# void-sim — FTL: ships, habitat modules, life support, power, repair, hazards
# --------------------------------------------------------------------------------------


async def voidsim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent
    from ..mechanics.voidsim import (
        AirlockComponent,
        DistressSignalComponent,
        FuelComponent,
        HabitatModuleComponent,
        JumpDriveComponent,
        LifeSupportComponent,
        OxygenComponent,
        PowerGridComponent,
        PressurizedComponent,
        SensorComponent,
        ShipComponent,
        ShipSystemComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="bridge", title="Bridge", biome="ship", indoor=True, light=0.7,
                     celsius=21.0),
            RoomSpec(key="engineering", title="Engineering", biome="ship", indoor=True,
                     light=0.5, celsius=24.0),
        ],
        exits=[
            ExitSpec(from_key="bridge", direction="aft", to_key="engineering"),
            ExitSpec(from_key="engineering", direction="fore", to_key="bridge"),
        ],
        characters=[
            CharacterSpec(key="captain", name="Captain Vesta", room_key="bridge",
                          controller="suspended", traits=("steady",),
                          goals=("keep the ship flying",)),
            CharacterSpec(key="engineer", name="Sprocket", room_key="engineering",
                          controller="llm", llm_profile="engineer",
                          goals=("keep systems online",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        bridge, engineering = world.rooms["bridge"], world.rooms["engineering"]
        # The two rooms are pressurized habitat modules with their own life support.
        _augment(actor, bridge,
                 HabitatModuleComponent(module_type="bridge"),
                 PressurizedComponent(pressure=1.0),
                 OxygenComponent(level=96.0, maximum=100.0),
                 LifeSupportComponent(online=True))
        _augment(actor, engineering,
                 HabitatModuleComponent(module_type="engineering"),
                 PressurizedComponent(pressure=1.0),
                 OxygenComponent(level=88.0, maximum=100.0),
                 LifeSupportComponent(online=True))
        # The ship itself, with power, fuel, jump drive, and sensors.
        _add(actor, bridge, [
            IdentityComponent(name="the Marsh Lark", kind="ship"),
            ShipComponent(name="Marsh Lark", hull_integrity=82.0),
            PowerGridComponent(capacity=100.0, available=60.0),
            FuelComponent(level=70.0, maximum=100.0),
            JumpDriveComponent(charged=True),
            SensorComponent(scan_range=2.0),
        ])
        _add(actor, bridge, [
            IdentityComponent(name="the forward airlock", kind="airlock"),
            AirlockComponent(module_id=str(bridge), exposes_vacuum=True),
        ])
        # A damaged reactor to repair, and a distress signal to scan and answer.
        _add(actor, engineering, [
            IdentityComponent(name="the reactor", kind="ship-system"),
            ShipSystemComponent(system_type="reactor", integrity=55.0, online=True),
        ])
        _add(actor, bridge, [
            IdentityComponent(name="a distress beacon", kind="signal"),
            DistressSignalComponent(text="Derelict hauler adrift, life signs faint."),
        ])
    return world


LIFESIM_DEMO = WorldGenerator(
    name="lifesim-demo", generate=lifesim_example,
    description="The Sims: a married couple with careers, skills, money, and aspirations.")
GARDENSIM_DEMO = WorldGenerator(
    name="gardensim-demo", generate=gardensim_example,
    description="Stardew Valley: a farm with tilled soil, a growing crop, and seeds.")
COLONYSIM_DEMO = WorldGenerator(
    name="colonysim-demo", generate=colonysim_example,
    description="RimWorld: a camp with resources, a workstation, a recipe, and a job.")
BARBARIANSIM_DEMO = WorldGenerator(
    name="barbariansim-demo", generate=barbariansim_example,
    description="Conan Exiles: a frozen ridge, a sheltered cave, gear, and corruption.")
DRAGONSIM_DEMO = WorldGenerator(
    name="dragonsim-demo", generate=dragonsim_example,
    description="Skyrim: a village, an undiscovered barrow, a faction, and a quest.")
DAGGERSIM_DEMO = WorldGenerator(
    name="daggersim-demo", generate=daggersim_example,
    description="Daggerfall: a town with a bank, guild, rumor, travel, and a frontier site.")
VOIDSIM_DEMO = WorldGenerator(
    name="voidsim-demo", generate=voidsim_example,
    description="FTL: a ship of habitat modules with life support, power, and a damaged reactor.")


__all__ = [
    "BARBARIANSIM_DEMO",
    "COLONYSIM_DEMO",
    "DAGGERSIM_DEMO",
    "DRAGONSIM_DEMO",
    "GARDENSIM_DEMO",
    "LIFESIM_DEMO",
    "VOIDSIM_DEMO",
    "barbariansim_example",
    "colonysim_example",
    "daggersim_example",
    "dragonsim_example",
    "gardensim_example",
    "lifesim_example",
    "voidsim_example",
]
