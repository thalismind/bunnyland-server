"""Hand-built example worlds (spec 21.4, 28.2).

Each generator lays down a small base world (rooms + life-sim characters with needs and
memory) via the same ``instantiate`` path the LLM uses, then layers on the components and
entities that show off its sim package. They are deterministic and dependency-free, so
``serve --generator voidsim-demo`` (etc.) spins up a scene a human can claim and play, and
the web inspector has something representative to show.

Demos may freely use features from the package's required/recommended dependencies — most
build on life-sim needs, which every character already gets from ``instantiate``.
"""

from __future__ import annotations

from ..core.ecs import replace_component, spawn_entity
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
# life-sim — needs, careers, money, relationships, aspirations
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
# garden-sim — soil, planting, crop growth, seeds
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
# colony-sim — resource nodes, stockpiles, workstations, recipes, jobs
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
# barbarian-sim — harsh cold, stamina, gear, corruption, shelter
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
# dragon-sim — discovery, factions, radiant quests, reputation
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
# dagger-sim — towns, guilds, banks, rumors, travel, expandable frontier
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
# void-sim — ships, habitat modules, life support, power, repair, hazards
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


# --------------------------------------------------------------------------------------
# nuke-sim — radiation, mutation pressure, scavenging, and jury-rigged crafting
# --------------------------------------------------------------------------------------


async def nukesim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent, PortableComponent
    from ..mechanics.colonysim import RecipeComponent, WorkstationComponent
    from ..mechanics.nukesim import (
        DecontaminationComponent,
        JunkComponent,
        LootTableComponent,
        RadiationSourceComponent,
        RadMedicineComponent,
        RadProtectionComponent,
        ScavengeSiteComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="checkpoint", title="Rustwater Checkpoint", biome="wasteland",
                     light=0.8, celsius=29.0),
            RoomSpec(key="ruin", title="Glow-Marked Pharmacy", biome="ruin", indoor=True,
                     light=0.2, celsius=31.0),
        ],
        exits=[
            ExitSpec(from_key="checkpoint", direction="east", to_key="ruin"),
            ExitSpec(from_key="ruin", direction="west", to_key="checkpoint"),
        ],
        characters=[
            CharacterSpec(key="scavenger", name="Mara", room_key="checkpoint",
                          controller="suspended", traits=("cautious",),
                          goals=("bring back clean scrap",)),
            CharacterSpec(key="mechanic", name="Patch", room_key="checkpoint",
                          controller="llm", llm_profile="wasteland mechanic",
                          goals=("keep the checkpoint supplied",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        checkpoint, ruin = world.rooms["checkpoint"], world.rooms["ruin"]
        _add(actor, checkpoint, [
            IdentityComponent(name="a decon arch", kind="decontamination"),
            DecontaminationComponent(
                dose_reduction=5.0,
                sickness_reduction=2.0,
                mutation_pressure_reduction=3.0,
                uses=3,
            ),
        ])
        _add(actor, checkpoint, [
            IdentityComponent(name="a field workbench", kind="workstation"),
            WorkstationComponent(station_type="workbench"),
        ])
        _add(actor, checkpoint, [
            IdentityComponent(name="pipe filter recipe", kind="recipe"),
            RecipeComponent(
                recipe_id="pipe-filter",
                inputs={"scrap": 2, "cloth": 1},
                outputs={"pipe-filter": 1},
                required_station="workbench",
            ),
        ])
        _add(actor, checkpoint, [
            IdentityComponent(name="a patched rad poncho", kind="armor"),
            PortableComponent(can_pick_up=True),
            RadProtectionComponent(rating=0.35),
        ])
        _add(actor, checkpoint, [
            IdentityComponent(name="a packet of rad-away", kind="medicine"),
            PortableComponent(can_pick_up=True),
            RadMedicineComponent(
                dose_reduction=4.0,
                sickness_reduction=2.0,
                mutation_pressure_reduction=2.0,
            ),
        ])
        _add(actor, ruin, [
            IdentityComponent(name="a cracked isotope case", kind="radiation-source"),
            RadiationSourceComponent(
                source_type="cracked isotope case",
                rads_per_hour=4.0,
                mutation_pressure_per_rad=1.0,
                sickness_per_rad=0.5,
            ),
        ])
        _add(actor, ruin, [
            IdentityComponent(name="a pharmacy backroom cache", kind="scavenge-site"),
            ScavengeSiteComponent(site_type="pre-war pharmacy", charges=2, hazard_rads=2.0),
            LootTableComponent(outputs={"scrap": 2, "cloth": 1, "chemicals": 1}),
        ])
        _add(actor, ruin, [
            IdentityComponent(name="a bent pressure cooker", kind="junk"),
            PortableComponent(can_pick_up=True),
            JunkComponent(outputs={"scrap": 2}, contaminated_rads=1.0),
        ])
    return world


# --------------------------------------------------------------------------------------
# dino-sim — fossils, clone eggs, reptile procreation, incubation, and hatching
# --------------------------------------------------------------------------------------


async def dinosim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent, PortableComponent
    from ..mechanics.dinosim import (
        BoneComponent,
        CreatureMilkComponent,
        CreatureProductComponent,
        DinosaurComponent,
        EggComponent,
        EnclosureComponent,
        FeedingPenComponent,
        FeedStoreComponent,
        FenceComponent,
        FertilityComponent,
        FossilFragmentComponent,
        GateComponent,
        HideComponent,
        IncubationComponent,
        ReptileProcreationComponent,
        SpeciesComponent,
        ToxinComponent,
        TranquilizerComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="lab",
                title="Amber Hatchery Lab",
                biome="field-lab",
                indoor=True,
                light=0.65,
                celsius=24.0,
            ),
            RoomSpec(
                key="paddock",
                title="Fern Paddock",
                biome="paddock",
                light=0.9,
                celsius=27.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="lab", direction="out", to_key="paddock"),
            ExitSpec(from_key="paddock", direction="in", to_key="lab"),
        ],
        objects=[
            ObjectSpec(
                key="ration",
                room_key="lab",
                name="a basket of fern cakes",
                kind="food",
                nutrition=4.0,
                satiety=18.0,
                portable=True,
            ),
            ObjectSpec(
                key="water",
                room_key="paddock",
                name="a clear trough",
                kind="water",
                hydration=20.0,
                portable=False,
                renewable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="keeper",
                name="Mira",
                room_key="lab",
                controller="suspended",
                traits=("careful", "curious"),
                goals=("hatch the prepared egg", "catalogue the amber shard"),
            ),
            CharacterSpec(
                key="raptor",
                name="Clever Raptor",
                room_key="paddock",
                species="velociraptor",
                controller="llm",
                llm_profile="alert hatchery creature",
                traits=("watchful", "fast"),
                goals=("guard the paddock", "inspect new hatchlings"),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        lab = world.rooms["lab"]
        paddock = world.rooms["paddock"]
        raptor = world.characters["raptor"]
        _augment(
            actor,
            paddock,
            EnclosureComponent(name="Fern Paddock", capacity=3),
            FenceComponent(integrity=8.0, maximum=10.0),
            GateComponent(open=False, locked=True),
            FeedingPenComponent(feed=5.0),
            FeedStoreComponent(feed=5.0, capacity=12.0),
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="an amber bone shard", kind="fossil"),
                PortableComponent(can_pick_up=True),
                FossilFragmentComponent(sample_quality=0.85),
            ],
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="a warm velociraptor egg", kind="egg"),
                PortableComponent(can_pick_up=True),
                EggComponent(
                    species_name="velociraptor",
                    laid_at_epoch=0,
                    fertilized=True,
                    source="clone",
                ),
                IncubationComponent(
                    started_at_epoch=0,
                    required_seconds=60,
                    progress_seconds=60,
                    last_updated_epoch=0,
                    ready=True,
                ),
            ],
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="scented bait", kind="food"),
                PortableComponent(can_pick_up=True),
            ],
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="sleep dart", kind="tool"),
                PortableComponent(can_pick_up=True),
                TranquilizerComponent(potency=1.0, uses=1),
            ],
        )
        _augment(
            actor,
            raptor,
            DinosaurComponent(species_name="velociraptor"),
            SpeciesComponent(
                common_name="velociraptor",
                scientific_name="Velociraptor mongoliensis",
                diet="carnivore",
                size_class="small",
            ),
            FertilityComponent(fertile=True),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
            CreatureMilkComponent(volume=1.0, maximum=1.0),
            ToxinComponent(potency=1.0, quantity=1.0, maximum=1.0),
            HideComponent(quality=1.0),
            BoneComponent(quality=1.0),
            CreatureProductComponent(
                product_type="fertilizer",
                quantity=2.0,
                renewable=True,
            ),
        )
    return world


# --------------------------------------------------------------------------------------
# pop-culture demos — legally distinct affectionate genre spoofs
# --------------------------------------------------------------------------------------


async def clue_snack_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A comic mystery demo with a nervous snack-lover and a talking sleuth-hound."""

    del options
    from ..core.components import IdentityComponent, PortableComponent, ReadableComponent
    from ..mechanics.dragonsim import (
        DiscoveryComponent,
        PointOfInterestComponent,
        QuestComponent,
        QuestObjectiveComponent,
        QuestRewardComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="snack_van", title="Snack Van Pull-Off", biome="roadside",
                     light=0.5, celsius=16.0),
            RoomSpec(key="lodge", title="Creaky Mascot Lodge", biome="lodge",
                     indoor=True, light=0.25, celsius=13.0),
            RoomSpec(key="cellar", title="Stage-Trick Cellar", biome="cellar",
                     indoor=True, light=0.1, celsius=11.0),
        ],
        exits=[
            ExitSpec(from_key="snack_van", direction="in", to_key="lodge"),
            ExitSpec(from_key="lodge", direction="out", to_key="snack_van"),
            ExitSpec(from_key="lodge", direction="down", to_key="cellar"),
            ExitSpec(from_key="cellar", direction="up", to_key="lodge"),
        ],
        objects=[
            ObjectSpec(key="sandwiches", room_key="snack_van", name="a hamper of tower sandwiches",
                       kind="food", nutrition=5.0, satiety=22.0, portable=True),
            ObjectSpec(key="water_jug", room_key="snack_van", name="a sloshing water jug",
                       kind="water", hydration=18.0, portable=True, renewable=False),
            ObjectSpec(key="mask", room_key="cellar", name="a rubber fog-beast mask",
                       kind="item", portable=True),
            ObjectSpec(key="projector", room_key="cellar", name="a rattling shadow projector",
                       kind="item", portable=False),
        ],
        characters=[
            CharacterSpec(key="munch", name="Jory Munch", room_key="snack_van",
                          controller="suspended", traits=("nervous", "hungry", "loyal"),
                          goals=("find the hidden snack stash", "avoid being volunteered")),
            CharacterSpec(key="hound", name="Biscuit", room_key="snack_van", species="dog",
                          controller="llm", llm_profile="comic-hound",
                          traits=("talkative", "brave-when-fed"),
                          goals=("sniff out the prankster", "protect Jory's lunch")),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        cellar = world.rooms["cellar"]
        _augment(actor, cellar,
                 PointOfInterestComponent(location_type="stage trick", region="Fogbank Pier"),
                 DiscoveryComponent())
        _add(actor, world.rooms["lodge"], [
            IdentityComponent(name="Unmask the Fog Prank", kind="quest"),
            QuestComponent(quest_id="fog-prank", title="Unmask the Fog Prank",
                           status="offered"),
            QuestObjectiveComponent(quest_id="fog-prank",
                                    description="Find the stage equipment under the lodge"),
            QuestRewardComponent(quest_id="fog-prank",
                                 description="a heroic share of the sandwich hamper"),
        ])
        actor.world.get_entity(world.objects["projector"]).add_component(
            ReadableComponent(
                title="Projector Label",
                text="Property of Pier Promotions. Do not use to frighten guests after hours.",
            )
        )
        _add(actor, world.rooms["lodge"], [
            IdentityComponent(name="a squeaky clue notebook", kind="paper"),
            PortableComponent(can_pick_up=True),
            ReadableComponent(title="Clue Notebook",
                              text="Someone ordered extra fog, extra chains, and no witnesses."),
        ])
    return world


async def dive_scheme_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A dysfunctional city tavern where every room contains a terrible business plan."""

    del options
    from ..core.components import IdentityComponent, PortableComponent, ReadableComponent
    from ..mechanics.colonysim import JobComponent, ResourceStackComponent, WorkstationComponent
    from ..mechanics.daggersim import LawRegionComponent, RumorComponent
    from ..mechanics.lifesim import CareerComponent, HouseholdFundsComponent, SkillSetComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="bar", title="Gull And Grift Taproom", biome="city-tavern",
                     indoor=True, light=0.45, celsius=20.0),
            RoomSpec(key="office", title="Back Office Of Bad Ideas", biome="office",
                     indoor=True, light=0.35, celsius=21.0),
            RoomSpec(key="alley", title="Dumpster Negotiation Alley", biome="alley",
                     light=0.25, celsius=12.0),
        ],
        exits=[
            ExitSpec(from_key="bar", direction="back", to_key="office"),
            ExitSpec(from_key="office", direction="front", to_key="bar"),
            ExitSpec(from_key="bar", direction="out", to_key="alley"),
            ExitSpec(from_key="alley", direction="in", to_key="bar"),
        ],
        objects=[
            ObjectSpec(key="beer", room_key="bar", name="a questionable house lager",
                       kind="water", hydration=6.0, portable=False),
            ObjectSpec(key="pretzels", room_key="bar", name="a bowl of over-salted pretzels",
                       kind="food", nutrition=2.0, satiety=8.0, portable=False),
            ObjectSpec(key="scheme_board", room_key="office", name="a corkboard of doomed schemes",
                       kind="paper", writable=True, portable=False),
            ObjectSpec(key="crate", room_key="alley", name="a crate of unsold novelty whistles",
                       kind="container", portable=True, open=True),
        ],
        characters=[
            CharacterSpec(key="boss", name="Rex Malloy", room_key="bar", controller="suspended",
                          traits=("commanding", "self-serving"),
                          goals=("declare himself general manager",)),
            CharacterSpec(key="performer", name="Lina Sharp", room_key="bar", controller="llm",
                          llm_profile="dive-performer", traits=("vain", "quick-witted"),
                          goals=("turn tonight into a showcase",)),
            CharacterSpec(key="fixer", name="Ozzie Crank", room_key="office", controller="llm",
                          llm_profile="bad-scheme-fixer", traits=("intense", "impatient"),
                          goals=("prove the whistle franchise is viable",)),
            CharacterSpec(key="investor", name="Marta Quill", room_key="alley", controller="llm",
                          llm_profile="reckless-investor", traits=("rich", "bored"),
                          goals=("buy influence with pocket change",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _augment(actor, world.rooms["bar"],
                 LawRegionComponent(region_id="river-ward", fines={"brawl": 15, "default": 5}))
        _add(actor, world.rooms["office"], [
            IdentityComponent(name="a broken laminating station", kind="workstation"),
            WorkstationComponent(station_type="office"),
        ])
        _add(actor, world.rooms["alley"], [
            IdentityComponent(name="six novelty whistles", kind="resource"),
            PortableComponent(can_pick_up=True),
            ResourceStackComponent(resource_type="novelty-whistle", quantity=6),
        ])
        _add(actor, world.rooms["office"], [
            IdentityComponent(name="tonight's terrible job", kind="job"),
            JobComponent(job_type="sell-whistles", priority=5),
        ])
        _add(actor, world.rooms["bar"], [
            IdentityComponent(name="a barfly rumor", kind="rumor"),
            RumorComponent(text="The alley crate is worth less than the argument about it."),
        ])
        replace_component(
            actor.world.get_entity(world.objects["scheme_board"]),
            ReadableComponent(title="Scheme Board",
                              text="Step 1: rebrand whistles. Step 2: citywide respect. "
                                   "Step 3: absolutely no refunds.")
        )
        _augment(actor, world.characters["boss"],
                 CareerComponent(title="bar co-owner", level=1, hourly_pay=0),
                 SkillSetComponent(levels={"intimidation": 2}),
                 HouseholdFundsComponent(balance=37))
    return world


async def star_opera_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A bright star-opera demo with rebels, a rusty courier ship, and a masked officer."""

    del options
    from ..core.components import IdentityComponent, PortableComponent, ReadableComponent
    from ..mechanics.barbariansim import DurabilityComponent, WeaponComponent
    from ..mechanics.dragonsim import FactionComponent, QuestComponent, QuestObjectiveComponent
    from ..mechanics.voidsim import (
        FuelComponent,
        HabitatModuleComponent,
        JumpDriveComponent,
        LifeSupportComponent,
        NavigationRouteComponent,
        OxygenComponent,
        PowerGridComponent,
        PressurizedComponent,
        SensorComponent,
        ShipComponent,
        StarSystemComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="duneport", title="Saffron Duneport Market", biome="desert-port",
                     light=0.95, celsius=34.0),
            RoomSpec(key="freighter", title="Rustwing Freighter Hold", biome="ship",
                     indoor=True, light=0.55, celsius=22.0),
            RoomSpec(key="checkpoint", title="Black-Helmet Checkpoint", biome="checkpoint",
                     indoor=True, light=0.7, celsius=20.0),
        ],
        exits=[
            ExitSpec(from_key="duneport", direction="aboard", to_key="freighter"),
            ExitSpec(from_key="freighter", direction="down-ramp", to_key="duneport"),
            ExitSpec(from_key="duneport", direction="east", to_key="checkpoint"),
            ExitSpec(from_key="checkpoint", direction="west", to_key="duneport"),
        ],
        objects=[
            ObjectSpec(key="ration", room_key="duneport", name="a packet of sun-baked rations",
                       kind="food", nutrition=4.0, satiety=15.0, portable=True),
            ObjectSpec(key="canteen", room_key="duneport", name="a dented vapor canteen",
                       kind="water", hydration=20.0, portable=True, renewable=False),
            ObjectSpec(key="data_spool", room_key="checkpoint", name="a coded courier spool",
                       kind="paper", writable=False, portable=True),
        ],
        characters=[
            CharacterSpec(key="farmhand", name="Tavi Orun", room_key="duneport",
                          controller="suspended", traits=("idealistic", "restless"),
                          goals=("escape the dunes", "deliver the coded spool")),
            CharacterSpec(key="courier", name="Captain Brindle Voss", room_key="freighter",
                          controller="llm", llm_profile="wry-courier",
                          traits=("charming", "indebted"),
                          goals=("get paid before helping anyone",)),
            CharacterSpec(key="mentor", name="Old Sera", room_key="duneport",
                          controller="llm", llm_profile="star-monk",
                          traits=("patient", "cryptic"),
                          goals=("teach Tavi restraint",)),
            CharacterSpec(key="marshal", name="Marshal Vark", room_key="checkpoint",
                          controller="llm", llm_profile="masked-officer",
                          traits=("severe", "ceremonial"),
                          goals=("recover the courier spool",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        duneport = world.rooms["duneport"]
        freighter = world.rooms["freighter"]
        _augment(actor, duneport, StarSystemComponent(name="Amber Verge"))
        _augment(actor, freighter,
                 HabitatModuleComponent(module_type="freighter-hold"),
                 PressurizedComponent(pressure=1.0),
                 OxygenComponent(level=91.0),
                 LifeSupportComponent(online=True),
                 NavigationRouteComponent(destination_id="Free Lantern", fuel_cost=20.0))
        _add(actor, freighter, [
            IdentityComponent(name="the Rustwing", kind="ship"),
            ShipComponent(name="Rustwing", hull_integrity=64.0),
            PowerGridComponent(capacity=80.0, available=38.0),
            FuelComponent(level=44.0, maximum=100.0),
            JumpDriveComponent(charged=False),
            SensorComponent(scan_range=1.5),
        ])
        _add(actor, duneport, [
            IdentityComponent(name="Free Lantern Cell", kind="faction"),
            FactionComponent(name="Free Lantern Cell", ideology="smuggle hope past checkpoints"),
        ])
        _add(actor, duneport, [
            IdentityComponent(name="Run The Checkpoint", kind="quest"),
            QuestComponent(quest_id="run-checkpoint", title="Run The Checkpoint",
                           status="offered"),
            QuestObjectiveComponent(quest_id="run-checkpoint",
                                    description="Carry the coded spool aboard the Rustwing"),
        ])
        _add(actor, world.rooms["checkpoint"], [
            IdentityComponent(name="a humming training baton", kind="weapon"),
            PortableComponent(can_pick_up=True),
            WeaponComponent(damage=5.0, damage_type="energy", lethal_capable=False),
            DurabilityComponent(current=30.0, maximum=40.0),
        ])
        replace_component(
            actor.world.get_entity(world.objects["data_spool"]),
            ReadableComponent(title="Courier Spool",
                              text="A compressed route ledger points toward the Free Lantern.")
        )
    return world


async def gothic_count_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A gothic castle demo with an over-formal night host and suspicious paperwork."""

    del options
    from ..core.components import IdentityComponent, PortableComponent, ReadableComponent
    from ..mechanics.daggersim import (
        FeedingNeedComponent,
        SecretDoorComponent,
        SupernaturalAfflictionComponent,
    )
    from ..mechanics.dragonsim import DiscoveryComponent, PointOfInterestComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="inn", title="Moor Road Inn", biome="moor", indoor=True,
                     light=0.4, celsius=9.0),
            RoomSpec(key="hall", title="Moonlit Castle Hall", biome="castle",
                     indoor=True, light=0.2, celsius=8.0),
            RoomSpec(key="crypt", title="Velvet-Draped Crypt", biome="crypt",
                     indoor=True, light=0.05, celsius=6.0),
        ],
        exits=[
            ExitSpec(from_key="inn", direction="up-road", to_key="hall"),
            ExitSpec(from_key="hall", direction="down-road", to_key="inn"),
            ExitSpec(from_key="hall", direction="down", to_key="crypt"),
            ExitSpec(from_key="crypt", direction="up", to_key="hall"),
        ],
        objects=[
            ObjectSpec(key="broth", room_key="inn", name="a bowl of garlicy root broth",
                       kind="food", nutrition=4.0, satiety=14.0, portable=False),
            ObjectSpec(key="tea", room_key="inn", name="a chipped cup of black tea",
                       kind="water", hydration=12.0, portable=False),
            ObjectSpec(key="deed", room_key="hall", name="a crimson-sealed property deed",
                       kind="paper", writable=False, portable=True),
            ObjectSpec(key="travel_trunk", room_key="hall", name="a brass-bound travel trunk",
                       kind="container", portable=True, open=False),
        ],
        characters=[
            CharacterSpec(key="clerk", name="Merrit Vale", room_key="inn",
                          controller="suspended", traits=("polite", "uneasy"),
                          goals=("complete the property papers", "leave before midnight")),
            CharacterSpec(key="count", name="Lord Varro", room_key="hall", species="nightfolk",
                          controller="llm", llm_profile="gothic-host",
                          traits=("courtly", "hungry", "ancient"),
                          goals=("keep guests comfortable", "avoid direct sunlight")),
            CharacterSpec(key="innkeeper", name="Nessa Pike", room_key="inn",
                          controller="llm", llm_profile="worried-innkeeper",
                          traits=("superstitious", "practical"),
                          goals=("warn Merrit without naming the danger",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        hall, crypt = world.rooms["hall"], world.rooms["crypt"]
        _augment(actor, crypt,
                 PointOfInterestComponent(location_type="crypt", region="Moor Road"),
                 DiscoveryComponent())
        _augment(actor, world.characters["count"],
                 SupernaturalAfflictionComponent(affliction_type="nocturnal hunger",
                                                 contracted_at_epoch=0,
                                                 stage="mastered"),
                 FeedingNeedComponent(current=6.0, maximum=10.0))
        _add(actor, hall, [
            IdentityComponent(name="a hidden stair behind the portrait", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(crypt), direction="behind portrait",
                                hint="The portrait frame is cleaner on one side."),
        ])
        _add(actor, crypt, [
            IdentityComponent(name="a silvered travel mirror", kind="item"),
            PortableComponent(can_pick_up=True),
        ])
        replace_component(
            actor.world.get_entity(world.objects["deed"]),
            ReadableComponent(title="Property Deed",
                              text="The buyer agrees to occupy the estate only after sunset "
                                   "and never inspect the lower rooms uninvited.")
        )
    return world


LIFESIM_DEMO = WorldGenerator(
    name="lifesim-demo", generate=lifesim_example,
    description="A household with careers, skills, money, relationships, and aspirations.",
    uses_seed=False)
GARDENSIM_DEMO = WorldGenerator(
    name="gardensim-demo", generate=gardensim_example,
    description="A farm with tilled soil, a growing crop, and seeds.",
    uses_seed=False)
COLONYSIM_DEMO = WorldGenerator(
    name="colonysim-demo", generate=colonysim_example,
    description="A work camp with resources, a workstation, a recipe, and a job.",
    uses_seed=False)
BARBARIANSIM_DEMO = WorldGenerator(
    name="barbariansim-demo", generate=barbariansim_example,
    description="A frozen ridge with a sheltered cave, gear, and corruption pressure.",
    uses_seed=False)
DRAGONSIM_DEMO = WorldGenerator(
    name="dragonsim-demo", generate=dragonsim_example,
    description="A village with an undiscovered barrow, a faction, and a quest.",
    uses_seed=False)
DAGGERSIM_DEMO = WorldGenerator(
    name="daggersim-demo", generate=daggersim_example,
    description="A town with a bank, guild, rumor, travel, and a frontier site.",
    uses_seed=False)
VOIDSIM_DEMO = WorldGenerator(
    name="voidsim-demo", generate=voidsim_example,
    description="A modular ship with life support, power, and a damaged reactor.",
    uses_seed=False)
NUKESIM_DEMO = WorldGenerator(
    name="nukesim-demo", generate=nukesim_example,
    description="A wasteland checkpoint with radiation, scavenging, decon, and scrap crafting.",
    uses_seed=False)
DINOSIM_DEMO = WorldGenerator(
    name="dinosim-demo", generate=dinosim_example,
    description="A hatchery with fossils, a ready egg, and a fertile dinosaur parent.",
    uses_seed=False)
CLUE_SNACK_DEMO = WorldGenerator(
    name="clue-snack-demo", generate=clue_snack_example,
    description=(
        "A legally distinct comic mystery with snacks, a talking hound, and a fake haunting."
    ),
    uses_seed=False)
DIVE_SCHEME_DEMO = WorldGenerator(
    name="dive-scheme-demo", generate=dive_scheme_example,
    description="A legally distinct dysfunctional tavern sitcom full of bad schemes.",
    uses_seed=False)
STAR_OPERA_DEMO = WorldGenerator(
    name="star-opera-demo", generate=star_opera_example,
    description="A legally distinct star-opera rebellion at a desert port and rusty freighter.",
    uses_seed=False)
GOTHIC_COUNT_DEMO = WorldGenerator(
    name="gothic-count-demo", generate=gothic_count_example,
    description="A legally distinct gothic night-host castle with papers, secrets, and hunger.",
    uses_seed=False)

POP_CULTURE_DEMOS = (
    CLUE_SNACK_DEMO,
    DIVE_SCHEME_DEMO,
    STAR_OPERA_DEMO,
    GOTHIC_COUNT_DEMO,
)


__all__ = [
    "BARBARIANSIM_DEMO",
    "CLUE_SNACK_DEMO",
    "COLONYSIM_DEMO",
    "DAGGERSIM_DEMO",
    "DINOSIM_DEMO",
    "DRAGONSIM_DEMO",
    "DIVE_SCHEME_DEMO",
    "GARDENSIM_DEMO",
    "GOTHIC_COUNT_DEMO",
    "LIFESIM_DEMO",
    "NUKESIM_DEMO",
    "POP_CULTURE_DEMOS",
    "STAR_OPERA_DEMO",
    "VOIDSIM_DEMO",
    "barbariansim_example",
    "clue_snack_example",
    "colonysim_example",
    "daggersim_example",
    "dinosim_example",
    "dragonsim_example",
    "dive_scheme_example",
    "gardensim_example",
    "gothic_count_example",
    "lifesim_example",
    "nukesim_example",
    "star_opera_example",
    "voidsim_example",
]
