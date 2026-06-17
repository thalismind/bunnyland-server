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

from ..core.components import RegionComponent
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
    # Use replace_component so a demo's curated component overrides any the built-in
    # enrichment hooks already added to this entity during instantiate() (e.g. a generic
    # PointOfInterest on a 'ruin' room), rather than raw-adding a duplicate and crashing.
    entity = actor.world.get_entity(entity_id)
    for component in components:
        replace_component(entity, component)
    return entity


def _region_stack(actor, room_ids, levels):
    """Build nested ``RegionComponent`` containers above ``room_ids``.

    ``levels`` is outermost-first ``(name, kind)`` pairs joined by ``Contains`` edges in
    ``REGION`` mode; the innermost region contains every room. This gives the inspector's
    region view a populated, multi-level hierarchy above the rooms, mirroring the web
    repo's ``regional-hierarchy.json`` (planet -> ... -> building -> story -> room).
    """
    children = list(room_ids)
    for name, kind in reversed(levels):
        region = spawn_entity(actor.world, [RegionComponent(name=name, kind=kind)])
        for child_id in children:
            region.add_relationship(Contains(mode=ContainmentMode.REGION), child_id)
        children = [region.id]


def _with_regions(generate, levels):
    """Wrap a demo generator so it lays nested regions above the rooms it builds."""

    async def generate_with_regions(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
        world = await generate(actor, seed, options)
        async with actor._lock:
            _region_stack(actor, world.rooms.values(), levels)
        return world

    return generate_with_regions


# --------------------------------------------------------------------------------------
# life-sim — needs, careers, money, relationships, aspirations
# --------------------------------------------------------------------------------------


async def lifesim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent
    from ..mechanics.lifesim import (
        AspirationComponent,
        CareerComponent,
        CharacterProfileComponent,
        HasWhim,
        HomeObjectComponent,
        HouseholdFundsComponent,
        PartnerOf,
        RelationshipStatus,
        SkillSetComponent,
        WhimComponent,
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
                 HouseholdFundsComponent(balance=140),
                 CharacterProfileComponent(
                     traits=("warm", "ambitious"),
                     interests=("gardening", "cooking"),
                     preferred_routine="morning garden care",
                 ))
        _augment(actor, hazel,
                 CareerComponent(title="baker", level=1, hourly_pay=11),
                 SkillSetComponent(levels={"baking": 2}),
                 AspirationComponent(name="Village Baker", milestones=("open a stall",)))
        whim = _add(actor, world.rooms["cottage"], [
            IdentityComponent(name="Juniper's garden whim", kind="whim"),
            WhimComponent(want="water the cottage herbs", reward_xp=4.0),
        ])
        actor.world.get_entity(juniper).add_relationship(HasWhim(), whim.id)
        _add(actor, world.rooms["cottage"], [
            IdentityComponent(name="a cozy reading chair", kind="home-object"),
            HomeObjectComponent(
                affordance="comfort",
                cleanliness=0.85,
                condition=0.9,
                decor_score=1.5,
            ),
        ])
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
            CropQualityComponent(quality=1.2),
            RegrowableComponent(regrow_days=2.0),
            PestComponent(severity=0.25),
            WeedComponent(density=0.2),
        ])
        _add(actor, field, [
            IdentityComponent(name="a packet of turnip seeds", kind="item"),
            PortableComponent(can_pick_up=True),
            SeedComponent(crop_type="turnip", growth_days=5.0, yield_item="turnip",
                          yield_quantity=2),
        ])
        _add(actor, field, [
            IdentityComponent(name="a small preserves machine", kind="machine"),
            MachineComponent(machine_type="preserves", quality=0.9),
        ])
        _add(actor, field, [
            IdentityComponent(name="a farm shipping crate", kind="shipping-bin"),
            ShippingBinComponent(),
        ])
        _add(actor, field, [
            IdentityComponent(name="a geode from the lower mine", kind="geode"),
            PortableComponent(can_pick_up=True),
            GeodeComponent(resource_type="amethyst", quantity=1),
        ])
        _add(actor, field, [
            IdentityComponent(name="a ladder down to mine level two", kind="ladder"),
            LadderComponent(target_room_id=str(field)),
        ])
        _augment(actor, field, MineLevelComponent(level=1))
        _add(actor, world.rooms["farmhouse"], [
            IdentityComponent(name="farm mail: welcome gift", kind="mail"),
            MailComponent(
                subject="Welcome gift",
                reward_resource="parsnip seed",
                reward_quantity=3,
            ),
        ])
        _add(actor, world.rooms["farmhouse"], [
            IdentityComponent(name="community board order", kind="quest"),
            FarmQuestComponent(
                quest_id="first-harvest",
                requested={"carrot": 2},
                reward_resource="coin",
                reward_quantity=25,
            ),
        ])
        _add(actor, world.rooms["farmhouse"], [
            IdentityComponent(name="farm museum shelf", kind="museum"),
            MuseumCollectionComponent(),
        ])
    return world


async def maple_farm_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import (
        DescriptionComponent,
        IdentityComponent,
        PortableComponent,
        WorldClockComponent,
    )
    from ..mechanics.colonysim import (
        RecipeComponent,
        ResourceStackComponent,
        StockpileComponent,
        StorageFilterComponent,
        WorkstationComponent,
    )
    from ..mechanics.environment import CalendarComponent, WeatherComponent
    from ..mechanics.gardensim import (
        HarvestableComponent,
        TreeComponent,
        TreeTapComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="grove", title="Quebec Maple Grove", biome="sugarbush",
                     light=0.8, celsius=2.0),
            RoomSpec(key="shack", title="Sugar Shack", biome="sugar-shack",
                     indoor=True, light=0.65, celsius=18.0),
            RoomSpec(key="stand", title="Snowbank Farm Stand", biome="roadside",
                     light=0.75, celsius=1.0),
        ],
        exits=[
            ExitSpec(from_key="grove", direction="in", to_key="shack"),
            ExitSpec(from_key="shack", direction="out", to_key="grove"),
            ExitSpec(from_key="shack", direction="south", to_key="stand"),
            ExitSpec(from_key="stand", direction="north", to_key="shack"),
        ],
        objects=[
            ObjectSpec(key="pea_soup", room_key="shack", name="a crock of yellow pea soup",
                       kind="food", nutrition=5.0, satiety=18.0, portable=False),
            ObjectSpec(key="snow_water", room_key="grove", name="a clean snowmelt barrel",
                       kind="water", hydration=16.0, portable=False),
            ObjectSpec(key="tap_kit", room_key="grove", name="a maple tapping kit",
                       kind="item", portable=True),
            ObjectSpec(key="ledger", room_key="shack", name="a syrup season ledger",
                       kind="paper", portable=True),
            ObjectSpec(key="cash_box", room_key="stand", name="a locked wooden cash box",
                       kind="container", portable=False, open=False),
        ],
        characters=[
            CharacterSpec(key="syrupmaker", name="Camille Lavoie", room_key="grove",
                          controller="suspended", traits=("patient", "weather-wise"),
                          goals=("tap the ready maples", "bring sap to the sugar shack")),
            CharacterSpec(key="neighbor", name="Noah Tremblay", room_key="stand",
                          controller="llm", llm_profile="maple-neighbor",
                          traits=("practical", "talkative"),
                          goals=("trade for the first syrup of the season",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            clock[0].add_component(CalendarComponent(season="spring", day=38))
            clock[0].add_component(WeatherComponent(condition="freeze-thaw", intensity=0.2))

        grove = world.rooms["grove"]
        _augment(actor, grove,
                 DescriptionComponent(short="A Canadian sugarbush waits in thawing snow."))
        _add(actor, grove, [
            IdentityComponent(name="a young sugar maple", kind="tree"),
            TreeComponent(tree_type="sugar maple", planted_at_epoch=0,
                          maturity_days=1.0),
        ])
        _add(actor, grove, [
            IdentityComponent(name="a ready sugar maple", kind="tree"),
            TreeComponent(tree_type="sugar maple", planted_at_epoch=0,
                          maturity_days=0.0, mature=True),
        ])
        _add(actor, grove, [
            IdentityComponent(name="a tapped roadside maple", kind="tree"),
            TreeComponent(tree_type="sugar maple", planted_at_epoch=0,
                          maturity_days=0.0, mature=True),
            TreeTapComponent(tapped_at_epoch=0, last_collected_epoch=0,
                             collection_days=1.0),
            HarvestableComponent(yield_item="maple sap", quantity=4, ready=False),
        ])
        _add(actor, world.rooms["shack"], [
            IdentityComponent(name="a wood-fired evaporator", kind="workstation"),
            WorkstationComponent(station_type="evaporator"),
        ])
        _add(actor, world.rooms["shack"], [
            IdentityComponent(name="maple syrup recipe", kind="recipe"),
            RecipeComponent(recipe_id="maple-syrup", inputs={"maple sap": 4},
                            outputs={"maple syrup": 1}, required_station="evaporator"),
        ])
        _add(actor, world.rooms["shack"], [
            IdentityComponent(name="a sap stockpile", kind="stockpile"),
            StockpileComponent(capacity=32),
            StorageFilterComponent(allowed_types=("maple sap", "maple syrup")),
        ])
        _add(actor, world.rooms["shack"], [
            IdentityComponent(name="a starter pail of maple sap", kind="resource"),
            PortableComponent(can_pick_up=True),
            ResourceStackComponent(resource_type="maple sap", quantity=4),
        ])
        _add(actor, world.rooms["stand"], [
            IdentityComponent(name="a display of amber maple syrup", kind="resource"),
            PortableComponent(can_pick_up=True),
            ResourceStackComponent(resource_type="maple syrup", quantity=2),
        ])
    return world


# --------------------------------------------------------------------------------------
# colony-sim — resource nodes, stockpiles, workstations, recipes, jobs
# --------------------------------------------------------------------------------------


async def colonysim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent, PortableComponent
    from ..mechanics.colonysim import (
        BodyPartHealthComponent,
        ColonyIncidentComponent,
        HasBodyPart,
        JobBillComponent,
        JobComponent,
        PawnProfileComponent,
        PrisonerComponent,
        RecipeComponent,
        ResearchProjectComponent,
        ResourceNodeComponent,
        ResourceStackComponent,
        StockpileComponent,
        StorageFilterComponent,
        SurgeryBillComponent,
        TradeOfferComponent,
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
        rowan, fern = world.characters["rowan"], world.characters["fern"]
        _augment(actor, rowan,
                 PawnProfileComponent(
                     backstory="field builder",
                     passions={"construction": 2, "plants": 1},
                     expectations="modest",
                 ))
        _augment(actor, fern, PrisonerComponent(recruitment_difficulty=8.0, policy="recruit"))
        left_arm = spawn_entity(actor.world, [
            IdentityComponent(name="Rowan's left arm", kind="body-part"),
            BodyPartHealthComponent(part="left arm", health=0.65),
        ])
        actor.world.get_entity(rowan).add_relationship(HasBodyPart(), left_arm.id)
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
            IdentityComponent(name="a wood stockpile", kind="stockpile"),
            StockpileComponent(capacity=24),
            StorageFilterComponent(allowed_types=("wood", "plank")),
        ])
        _add(actor, store, [
            IdentityComponent(name="a stack of logs", kind="resource"),
            PortableComponent(can_pick_up=True),
            ResourceStackComponent(resource_type="wood", quantity=8),
        ])
        _add(actor, store, [
            IdentityComponent(name="hauling job", kind="job"),
            JobComponent(job_type="haul", priority=3),
            JobBillComponent(recipe_id="plank", work_required=6.0, work_done=2.0),
        ])
        _add(actor, camp, [
            IdentityComponent(name="treehouse research notes", kind="research"),
            ResearchProjectComponent(project_id="treehouse", work_required=20.0, work_done=5.0),
        ])
        _add(actor, camp, [
            IdentityComponent(name="wandering trader offer", kind="trade-offer"),
            TradeOfferComponent(
                faction_id="pine-traders",
                gives={"medicine": 1},
                wants={"wood": 4},
                goodwill_delta=1.0,
            ),
        ])
        _add(actor, camp, [
            IdentityComponent(name="minor crop blight incident", kind="incident"),
            ColonyIncidentComponent(incident_type="crop blight", severity=1),
        ])
        _add(actor, camp, [
            IdentityComponent(name="install splint surgery", kind="surgery"),
            SurgeryBillComponent(part="left arm", operation="splint", work_required=4.0),
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
# neon-sim — districts, surveillance, hacking, street economy, cyberware, and fixers
# --------------------------------------------------------------------------------------


async def neonsim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..core.components import IdentityComponent, PortableComponent
    from ..core.edges import ContainmentMode, Contains
    from ..mechanics.colonysim import ResourceStackComponent
    from ..mechanics.neonsim import (
        AccessLevelComponent,
        BlackMarketComponent,
        CameraComponent,
        CheckpointComponent,
        ClinicComponent,
        CyberpunkSiteComponent,
        DataPayloadComponent,
        DeviceComponent,
        ExploitComponent,
        FixerComponent,
        HackableComponent,
        ImplantComponent,
        RestrictedAreaComponent,
        RunnerContractComponent,
        SafehouseComponent,
        SecurityZoneComponent,
        SurveillanceCoverageComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="strip", title="Glass Spire Strip", biome="city", light=0.4,
                     celsius=14.0),
            RoomSpec(key="office", title="Arasaka Records Office", biome="corp", indoor=True,
                     light=0.7, celsius=21.0),
        ],
        exits=[
            ExitSpec(from_key="strip", direction="north", to_key="office"),
            ExitSpec(from_key="office", direction="south", to_key="strip"),
        ],
        characters=[
            CharacterSpec(key="runner", name="Vesper", room_key="strip",
                          controller="suspended", traits=("paranoid",),
                          goals=("exfiltrate the personnel files",)),
            CharacterSpec(key="fixer", name="Padre", room_key="strip", controller="llm",
                          llm_profile="neon-city fixer",
                          goals=("keep the runners working",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        strip, office = world.rooms["strip"], world.rooms["office"]
        _augment(actor, strip, RegionComponent(name="Glass Spire", kind="district"))

        runner = actor.world.get_entity(world.characters["runner"])
        runner.add_component(AccessLevelComponent(clearance=1))
        fixer = actor.world.get_entity(world.characters["fixer"])
        fixer.add_component(FixerComponent(name="Padre"))

        kit = _add(actor, strip, [
            IdentityComponent(name="a breach kit", kind="tool"),
            PortableComponent(can_pick_up=True),
            ExploitComponent(power=3),
        ])
        runner.add_relationship(Contains(mode=ContainmentMode.INVENTORY), kit.id)
        scrip = _add(actor, strip, [
            IdentityComponent(name="scrip x80", kind="resource"),
            PortableComponent(can_pick_up=True),
            ResourceStackComponent(resource_type="scrip", quantity=80),
        ])
        runner.add_relationship(Contains(mode=ContainmentMode.INVENTORY), scrip.id)

        _add(actor, strip, [
            IdentityComponent(name="a corp turnstile", kind="checkpoint"),
            CheckpointComponent(clearance_required=2, bribe_cost=20),
        ])
        _add(actor, strip, [
            IdentityComponent(name="a back-alley flop", kind="safehouse"),
            SafehouseComponent(),
        ])
        _add(actor, strip, [
            IdentityComponent(name="a chrome dealer's stall", kind="vendor"),
            BlackMarketComponent(price=20, contraband_name="synthcoke", contraband_heat=3.0),
        ])
        _add(actor, strip, [
            IdentityComponent(name="a ripperdoc booth", kind="clinic"),
            ClinicComponent(licensed=False, install_cost=40),
        ])
        _add(actor, strip, [
            IdentityComponent(name="a reflex booster", kind="implant"),
            PortableComponent(can_pick_up=True),
            ImplantComponent(implant_type="reflex", slot="neural", maintenance_interval=7200.0,
                             side_effect="hand tremors"),
        ])
        _add(actor, strip, [
            IdentityComponent(name="a data-run contract", kind="contract"),
            RunnerContractComponent(objective="courier the records", payout=250),
        ])

        _add(actor, office, [
            IdentityComponent(name="a records vault", kind="cyberpunk-site"),
            CyberpunkSiteComponent(site_type="data center"),
            SecurityZoneComponent(clearance_required=3),
            RestrictedAreaComponent(),
        ])
        _add(actor, office, [
            IdentityComponent(name="a ceiling camera", kind="camera"),
            DeviceComponent(device_type="camera"),
            CameraComponent(),
            SurveillanceCoverageComponent(),
        ])
        _add(actor, office, [
            IdentityComponent(name="a records server", kind="server"),
            DeviceComponent(device_type="server"),
            HackableComponent(security=2, owner="arasaka"),
            DataPayloadComponent(name="personnel files", sensitive=True),
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


async def midnight_burger_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """An inner-city burger shack whose back cellar is only dangerous after dark."""

    del options
    from ..core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from ..mechanics.daggersim import (
        FeedingNeedComponent,
        SecretDoorComponent,
        SupernaturalAfflictionComponent,
    )
    from ..mechanics.dragonsim import DiscoveryComponent, PointOfInterestComponent
    from ..mechanics.environment import CalendarComponent, TimeOfDayComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="lot", title="Neon Corner Lot", biome="city-street",
                     light=0.1, celsius=14.0),
            RoomSpec(key="counter", title="Patty Stack Counter", biome="diner",
                     indoor=True, light=0.55, celsius=24.0),
            RoomSpec(key="kitchen", title="Greasy Back Kitchen", biome="diner",
                     indoor=True, light=0.4, celsius=29.0),
            RoomSpec(key="cellar", title="Cold-Iron Cellar", biome="cellar",
                     indoor=True, light=0.05, celsius=4.0),
        ],
        exits=[
            ExitSpec(from_key="lot", direction="in", to_key="counter"),
            ExitSpec(from_key="counter", direction="out", to_key="lot"),
            ExitSpec(from_key="counter", direction="back", to_key="kitchen"),
            ExitSpec(from_key="kitchen", direction="front", to_key="counter"),
            ExitSpec(from_key="kitchen", direction="down", to_key="cellar"),
            ExitSpec(from_key="cellar", direction="up", to_key="kitchen"),
        ],
        objects=[
            ObjectSpec(key="smash_burgers", room_key="counter",
                       name="a tray of double smash burgers", kind="food",
                       nutrition=6.0, satiety=24.0, portable=True),
            ObjectSpec(key="fries", room_key="counter", name="a paper boat of salted fries",
                       kind="food", nutrition=3.0, satiety=10.0, portable=True),
            ObjectSpec(key="soda", room_key="counter", name="a sweating fountain soda",
                       kind="water", hydration=14.0, portable=True),
            ObjectSpec(key="menu", room_key="counter", name="a grease-spotted menu board",
                       kind="paper", writable=False, portable=False),
            ObjectSpec(key="freezer", room_key="kitchen", name="a padlocked chest freezer",
                       kind="container", portable=False, open=False),
        ],
        characters=[
            CharacterSpec(key="regular", name="Tessa Lane", room_key="counter",
                          controller="suspended", traits=("hungry", "cheerful", "oblivious"),
                          goals=("get a late-night burger", "head home before close")),
            CharacterSpec(key="cook", name="Mort Greaves", room_key="kitchen",
                          species="nightfolk", controller="llm", llm_profile="night-cook",
                          traits=("genial", "ravenous", "secretive"),
                          goals=("keep the grill hot", "keep guests out of the cellar after dark")),
            CharacterSpec(key="manager", name="Owen Park", room_key="counter",
                          controller="llm", llm_profile="closing-manager",
                          traits=("tired", "decent"),
                          goals=("hurry the last order", "warn Tessa without naming the danger")),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        # Open in the late-afternoon dinner rush so the day/night cycle visibly rolls into
        # night within a few hourly ticks — the cellar's danger is only real once it is dark.
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(clock[0], WorldClockComponent(game_time_seconds=17 * 3600))
            clock[0].add_component(TimeOfDayComponent(phase="day"))
            clock[0].add_component(CalendarComponent(day=1, season="autumn", hour=17))

        kitchen, cellar = world.rooms["kitchen"], world.rooms["cellar"]
        _augment(actor, cellar,
                 PointOfInterestComponent(location_type="meat cellar", region="Sixth Ward"),
                 DiscoveryComponent())
        _augment(actor, world.characters["cook"],
                 SupernaturalAfflictionComponent(affliction_type="nocturnal hunger",
                                                 contracted_at_epoch=0,
                                                 stage="mastered"),
                 FeedingNeedComponent(current=8.0, maximum=10.0))
        _add(actor, kitchen, [
            IdentityComponent(name="a steel walk-in door held shut by a meat hook",
                              kind="secret-door"),
            SecretDoorComponent(target_room_id=str(cellar), direction="behind the walk-in",
                                hint="The walk-in only latches from the cellar side."),
        ])
        _add(actor, cellar, [
            IdentityComponent(name="a stained butcher's ledger", kind="paper"),
            PortableComponent(can_pick_up=True),
            ReadableComponent(title="Butcher's Ledger",
                              text="Day shift buys beef. Night shift never does, and the "
                                   "regulars who stay past close never sign out."),
        ])
        replace_component(
            actor.world.get_entity(world.objects["menu"]),
            ReadableComponent(title="Menu Board",
                              text="ALL DAY: double smash, fries, soda. AFTER MIDNIGHT: ask "
                                   "Mort for the off-menu special. Staff only past the counter "
                                   "once the sign goes dark."),
        )
    return world


# --------------------------------------------------------------------------------------
# dungeon showcases — hand-built text-adventure crawls with maps, secrets, and objectives
# --------------------------------------------------------------------------------------


async def dungeon_vault_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A compact torchlit vault with a hidden final room and a relic objective."""

    del options
    from ..core.components import (
        DescriptionComponent,
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
    )
    from ..mechanics.daggersim import (
        AutomapComponent,
        DungeonComponent,
        DungeonObjectiveComponent,
        DungeonRoomComponent,
        RecallAnchorComponent,
        RestRiskComponent,
        SecretDoorComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="threshold", title="Dungeon Threshold", biome="dungeon",
                     indoor=True, light=0.25, celsius=11.0),
            RoomSpec(key="guardroom", title="Old Guardroom", biome="dungeon",
                     indoor=True, light=0.18, celsius=10.0),
            RoomSpec(key="cistern", title="Black Cistern", biome="dungeon",
                     indoor=True, light=0.08, celsius=8.0),
            RoomSpec(key="shrine", title="Ashen Shrine", biome="dungeon",
                     indoor=True, light=0.12, celsius=9.0),
            RoomSpec(key="vault", title="Sealed Ember Vault", biome="dungeon",
                     indoor=True, light=0.04, celsius=7.0),
        ],
        exits=[
            ExitSpec(from_key="threshold", direction="north", to_key="guardroom"),
            ExitSpec(from_key="guardroom", direction="south", to_key="threshold"),
            ExitSpec(from_key="guardroom", direction="east", to_key="cistern"),
            ExitSpec(from_key="cistern", direction="west", to_key="guardroom"),
            ExitSpec(from_key="guardroom", direction="west", to_key="shrine"),
            ExitSpec(from_key="shrine", direction="east", to_key="guardroom"),
        ],
        objects=[
            ObjectSpec(key="ration", room_key="threshold", name="a waxed trail ration",
                       kind="food", nutrition=4.0, satiety=16.0, portable=True),
            ObjectSpec(key="canteen", room_key="cistern", name="a dented water canteen",
                       kind="water", hydration=14.0, portable=True),
            ObjectSpec(key="torch", room_key="threshold", name="a pitch-soaked torch",
                       kind="item", portable=True),
            ObjectSpec(key="chalk_map", room_key="guardroom", name="a chalked wall map",
                       kind="paper", portable=False, writable=False),
            ObjectSpec(key="iron_box", room_key="vault", name="an iron-banded coffer",
                       kind="container", portable=False, open=False),
        ],
        characters=[
            CharacterSpec(key="delver", name="Mira Flint", room_key="threshold",
                          controller="suspended", traits=("methodical", "scarred"),
                          goals=("map the vault", "bring back the ember idol")),
            CharacterSpec(key="warden", name="The Ember Warden", room_key="shrine",
                          species="echo", controller="llm", llm_profile="dungeon-warden",
                          traits=("ancient", "literal"),
                          goals=("test anyone who reaches the shrine",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _add(actor, world.rooms["threshold"], [
            IdentityComponent(name="the Ember Vault", kind="dungeon"),
            DungeonComponent(dungeon_id="ember-vault", theme="torchlit ruin", seed=seed,
                             level_count=1,
                             objective_summary="recover the ember idol",
                             entry_room_id=str(world.rooms["threshold"]),
                             generated=True, entered=True),
        ])
        room_meta = {
            "threshold": (0, "low", "The stair behind you climbs to black air."),
            "guardroom": (1, "medium", "Rusty spear racks point toward four exits."),
            "cistern": (2, "uneasy", "Water drips in a rhythm that almost spells words."),
            "shrine": (2, "high", "Ash lies thick around a blank stone altar."),
            "vault": (3, "ambush", "The final chamber waits behind the shrine wall."),
        }
        for key, (depth, risk, text) in room_meta.items():
            _augment(actor, world.rooms[key],
                     DungeonRoomComponent(dungeon_id="ember-vault", depth=depth,
                                          discovered=(key == "threshold"),
                                          is_objective=(key == "vault"), danger=risk),
                     RestRiskComponent(band=risk),
                     DescriptionComponent(short=text))
        _augment(actor, world.characters["delver"],
                 AutomapComponent(discovered_rooms=(str(world.rooms["threshold"]),)),
                 RecallAnchorComponent(room_id=str(world.rooms["threshold"])))
        _add(actor, world.rooms["shrine"], [
            IdentityComponent(name="hairline cracks behind the altar", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(world.rooms["vault"]),
                                direction="behind altar", difficulty=2,
                                hint="Ash has been swept away from the rear flagstones."),
        ])
        replace_component(
            actor.world.get_entity(world.objects["chalk_map"]),
            ReadableComponent(title="Chalked Wall Map",
                              text="NORTH to iron, EAST to water, WEST to ash, then search.")
        )
        _add(actor, world.rooms["vault"], [
            IdentityComponent(name="the ember idol", kind="objective"),
            PortableComponent(can_pick_up=True),
            DungeonObjectiveComponent(objective_kind="relic",
                                      description="a palm-sized idol warm under the dust"),
        ])
    return world


async def dungeon_maze_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A looping slate maze built for mapping, backtracking, and suspicious directions."""

    del options
    from ..core.components import DescriptionComponent, IdentityComponent, ReadableComponent
    from ..mechanics.daggersim import (
        AutomapComponent,
        DungeonComponent,
        DungeonObjectiveComponent,
        DungeonRoomComponent,
        RestRiskComponent,
        SecretDoorComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="stair", title="Slate Stair", biome="dungeon",
                     indoor=True, light=0.22, celsius=12.0),
            RoomSpec(key="crossroads", title="Four-Way Crossroads", biome="dungeon",
                     indoor=True, light=0.16, celsius=11.0),
            RoomSpec(key="alcove", title="North Alcove", biome="dungeon",
                     indoor=True, light=0.1, celsius=10.0),
            RoomSpec(key="gallery", title="Echo Gallery", biome="dungeon",
                     indoor=True, light=0.1, celsius=10.0),
            RoomSpec(key="maproom", title="Map Room", biome="dungeon",
                     indoor=True, light=0.2, celsius=12.0),
            RoomSpec(key="cache", title="Hidden Provision Cache", biome="dungeon",
                     indoor=True, light=0.05, celsius=9.0),
        ],
        exits=[
            ExitSpec(from_key="stair", direction="down", to_key="crossroads"),
            ExitSpec(from_key="crossroads", direction="up", to_key="stair"),
            ExitSpec(from_key="crossroads", direction="north", to_key="alcove"),
            ExitSpec(from_key="alcove", direction="south", to_key="crossroads"),
            ExitSpec(from_key="crossroads", direction="east", to_key="gallery"),
            ExitSpec(from_key="gallery", direction="west", to_key="crossroads"),
            ExitSpec(from_key="gallery", direction="south", to_key="maproom"),
            ExitSpec(from_key="maproom", direction="north", to_key="gallery"),
            ExitSpec(from_key="maproom", direction="west", to_key="crossroads"),
            ExitSpec(from_key="crossroads", direction="south", to_key="maproom"),
        ],
        objects=[
            ObjectSpec(key="apple", room_key="stair", name="a bruised red apple",
                       kind="food", nutrition=2.0, satiety=8.0, portable=True),
            ObjectSpec(key="flask", room_key="alcove", name="a stoppered flask",
                       kind="water", hydration=10.0, portable=True),
            ObjectSpec(key="compass", room_key="gallery", name="a brass finger compass",
                       kind="item", portable=True),
            ObjectSpec(key="map_scrap", room_key="maproom", name="a slate map fragment",
                       kind="paper", portable=True),
        ],
        characters=[
            CharacterSpec(key="mapper", name="Tamsin Grey", room_key="stair",
                          controller="suspended", traits=("careful", "skeptical"),
                          goals=("prove the map room lies", "mark a path out")),
            CharacterSpec(key="voice", name="The Slate Voice", room_key="crossroads",
                          species="echo", controller="llm", llm_profile="maze-voice",
                          traits=("misleading", "patient"),
                          goals=("offer directions that sound useful",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _add(actor, world.rooms["stair"], [
            IdentityComponent(name="the Slate Maze", kind="dungeon"),
            DungeonComponent(dungeon_id="slate-maze", theme="mapped labyrinth", seed=seed,
                             level_count=1,
                             objective_summary="find the true map fragment",
                             entry_room_id=str(world.rooms["stair"]),
                             generated=True, entered=True),
        ])
        for key, depth in {
            "stair": 0,
            "crossroads": 1,
            "alcove": 2,
            "gallery": 2,
            "maproom": 3,
            "cache": 4,
        }.items():
            _augment(actor, world.rooms[key],
                     DungeonRoomComponent(dungeon_id="slate-maze", depth=depth,
                                          discovered=(key == "stair"),
                                          is_objective=(key == "maproom"),
                                          danger="medium" if key != "cache" else "low"),
                     RestRiskComponent(band="uneasy" if key != "cache" else "low"),
                     DescriptionComponent(short=f"Scratched slate marks the {key}."))
        _augment(actor, world.characters["mapper"],
                 AutomapComponent(discovered_rooms=(str(world.rooms["stair"]),)))
        replace_component(
            actor.world.get_entity(world.objects["map_scrap"]),
            ReadableComponent(title="Slate Map Fragment",
                              text="A blocky map says: N, E, S, W are true only once.")
        )
        _add(actor, world.rooms["maproom"], [
            IdentityComponent(name="a square shadow under the false map", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(world.rooms["cache"]),
                                direction="under map", difficulty=1,
                                hint="The map stone rings hollow when tapped."),
        ])
        _add(actor, world.rooms["cache"], [
            IdentityComponent(name="the true map tablet", kind="objective"),
            DungeonObjectiveComponent(objective_kind="map",
                                      description="a complete route scratched into slate"),
        ])
    return world


async def dungeon_crypt_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A chapel crypt with locked passages, readable clues, and a lower reliquary."""

    del options
    from ..core.components import (
        DescriptionComponent,
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
    )
    from ..mechanics.daggersim import (
        AutomapComponent,
        DungeonComponent,
        DungeonObjectiveComponent,
        DungeonRoomComponent,
        RestRiskComponent,
        SecretDoorComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="chapel", title="Ruined Chapel", biome="crypt",
                     indoor=True, light=0.35, celsius=10.0),
            RoomSpec(key="ossuary", title="Lettered Ossuary", biome="crypt",
                     indoor=True, light=0.12, celsius=7.0),
            RoomSpec(key="well", title="Dry Well Shaft", biome="crypt",
                     indoor=True, light=0.06, celsius=6.0),
            RoomSpec(key="gate", title="Iron Saint Gate", biome="crypt",
                     indoor=True, light=0.08, celsius=6.0),
            RoomSpec(key="reliquary", title="Lower Reliquary", biome="crypt",
                     indoor=True, light=0.03, celsius=5.0),
        ],
        exits=[
            ExitSpec(from_key="chapel", direction="down", to_key="ossuary"),
            ExitSpec(from_key="ossuary", direction="up", to_key="chapel"),
            ExitSpec(from_key="ossuary", direction="west", to_key="well"),
            ExitSpec(from_key="well", direction="east", to_key="ossuary"),
            ExitSpec(from_key="ossuary", direction="east", to_key="gate", locked=True),
            ExitSpec(from_key="gate", direction="west", to_key="ossuary", locked=True),
        ],
        objects=[
            ObjectSpec(key="bread", room_key="chapel", name="a wrapped heel of bread",
                       kind="food", nutrition=3.0, satiety=10.0, portable=True),
            ObjectSpec(key="holy_water", room_key="chapel", name="a blue glass water vial",
                       kind="water", hydration=8.0, portable=True),
            ObjectSpec(key="epitaph", room_key="ossuary", name="an alphabetical epitaph",
                       kind="paper", portable=False),
            ObjectSpec(key="rust_key", room_key="well", name="a rusted crypt key",
                       kind="key", portable=True, key_name="saint-gate"),
        ],
        characters=[
            CharacterSpec(key="seeker", name="Iris Vale", room_key="chapel",
                          controller="suspended", traits=("brave", "tired"),
                          goals=("read the epitaph", "find the reliquary candle")),
            CharacterSpec(key="scribe", name="The Bone Scribe", room_key="ossuary",
                          species="spirit", controller="llm", llm_profile="crypt-scribe",
                          traits=("formal", "forgetful"),
                          goals=("answer only in clues",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _add(actor, world.rooms["chapel"], [
            IdentityComponent(name="the Lettered Crypt", kind="dungeon"),
            DungeonComponent(dungeon_id="lettered-crypt", theme="sepulchral puzzle",
                             seed=seed, level_count=1,
                             objective_summary="recover the reliquary candle",
                             entry_room_id=str(world.rooms["chapel"]),
                             generated=True, entered=True),
        ])
        for key, (depth, danger, text) in {
            "chapel": (0, "low", "Rain ticks through the roof in single-letter beats."),
            "ossuary": (1, "medium", "Names are carved alphabetically into every wall."),
            "well": (2, "medium", "The dry stones smell of old iron."),
            "gate": (2, "high", "A saint of iron bars blocks the eastern way."),
            "reliquary": (3, "ambush", "Wax seals the shelves like pale armor."),
        }.items():
            _augment(actor, world.rooms[key],
                     DungeonRoomComponent(dungeon_id="lettered-crypt", depth=depth,
                                          discovered=(key == "chapel"),
                                          is_objective=(key == "reliquary"), danger=danger),
                     RestRiskComponent(band=danger),
                     DescriptionComponent(short=text))
        _augment(actor, world.characters["seeker"],
                 AutomapComponent(discovered_rooms=(str(world.rooms["chapel"]),)))
        _add(actor, world.rooms["gate"], [
            IdentityComponent(name="a saint's loose iron halo", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(world.rooms["reliquary"]),
                                direction="through halo", difficulty=2,
                                hint="The halo turns a finger-width when the key is near."),
        ])
        replace_component(
            actor.world.get_entity(world.objects["epitaph"]),
            ReadableComponent(title="Alphabetical Epitaph",
                              text="A begins below. I opens east. R turns the saint's halo.")
        )
        _add(actor, world.rooms["reliquary"], [
            IdentityComponent(name="the reliquary candle", kind="objective"),
            PortableComponent(can_pick_up=True),
            DungeonObjectiveComponent(objective_kind="light",
                                      description="a black candle marked with silver letters"),
        ])
    return world


# --------------------------------------------------------------------------------------
# scene vignettes — original atmospheric one-room dramas that lean on the shared
# environment, weather, and cross-package mechanics rather than a single sim pack
# --------------------------------------------------------------------------------------


async def storm_lighthouse_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A coastal lighthouse riding out a squall, with a beacon to feed and a buried sin."""

    del options
    from ..core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from ..mechanics.daggersim import SecretDoorComponent
    from ..mechanics.dragonsim import DiscoveryComponent, PointOfInterestComponent
    from ..mechanics.environment import (
        CalendarComponent,
        FireComponent,
        FlammableComponent,
        TimeOfDayComponent,
        WeatherComponent,
    )

    # Day 61 at 18:00 is an autumn rain day, so the deterministic weather cycle keeps the
    # squall blowing and the outdoor jetty dim as the demo ticks forward.
    storm_dusk_seconds = 60 * 24 * 3600 + 18 * 3600

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="jetty", title="Spray-Lashed Jetty", biome="coast",
                     light=0.2, celsius=7.0),
            RoomSpec(key="watch", title="Keeper's Watch Room", biome="lighthouse",
                     indoor=True, light=0.45, celsius=14.0),
            RoomSpec(key="lamp", title="Lantern Room", biome="lighthouse",
                     indoor=True, light=0.6, celsius=9.0),
            RoomSpec(key="niche", title="Below the Lens", biome="lighthouse",
                     indoor=True, light=0.05, celsius=8.0),
        ],
        exits=[
            ExitSpec(from_key="jetty", direction="in", to_key="watch"),
            ExitSpec(from_key="watch", direction="out", to_key="jetty"),
            ExitSpec(from_key="watch", direction="up", to_key="lamp"),
            ExitSpec(from_key="lamp", direction="down", to_key="watch"),
            ExitSpec(from_key="niche", direction="up", to_key="lamp"),
        ],
        objects=[
            ObjectSpec(key="stew", room_key="watch", name="a dented pot of fish stew",
                       kind="food", nutrition=5.0, satiety=18.0, portable=False),
            ObjectSpec(key="kettle", room_key="watch", name="a kettle of rainwater tea",
                       kind="water", hydration=14.0, portable=False),
            ObjectSpec(key="oil_can", room_key="lamp", name="a heavy can of lamp oil",
                       kind="item", portable=True),
            ObjectSpec(key="logbook", room_key="watch", name="the keeper's logbook",
                       kind="paper", writable=True, portable=True),
        ],
        characters=[
            CharacterSpec(key="keeper", name="Edda Voss", room_key="watch",
                          controller="suspended", traits=("dutiful", "weathered", "haunted"),
                          goals=("keep the beacon burning", "ride out the squall")),
            CharacterSpec(key="sailor", name="Cole Renner", room_key="watch",
                          controller="llm", llm_profile="stranded-sailor",
                          traits=("soaked", "grateful", "curious"),
                          goals=("get warm", "learn why ships keep wrecking on this point")),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(clock[0], WorldClockComponent(game_time_seconds=storm_dusk_seconds))
            clock[0].add_component(TimeOfDayComponent(phase="dusk"))
            clock[0].add_component(CalendarComponent(day=61, season="autumn", hour=18))
            clock[0].add_component(WeatherComponent(condition="rain", intensity=0.7))

        lamp, niche = world.rooms["lamp"], world.rooms["niche"]
        # The beacon is lit but burns its own fuel down — feed it or it dies before dawn.
        _add(actor, lamp, [
            IdentityComponent(name="the great lamp", kind="beacon"),
            FlammableComponent(fuel=6.0),
            FireComponent(intensity=0.6, fuel=6.0, last_updated_epoch=0),
        ])
        # The buried sin: a wrecker's niche hidden beneath the lens.
        _augment(actor, niche,
                 PointOfInterestComponent(location_type="wrecker's niche", region="Gallows Point"),
                 DiscoveryComponent())
        _add(actor, lamp, [
            IdentityComponent(name="a hatch under the lens pedestal", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(niche), direction="under the pedestal",
                                hint="The brass pedestal sits a finger's width off the floor."),
        ])
        _add(actor, niche, [
            IdentityComponent(name="a salt-stiff wrecking ledger", kind="paper"),
            PortableComponent(can_pick_up=True),
            ReadableComponent(title="Wrecking Ledger",
                              text="When the lamp goes dark on a bad night, the rocks do the "
                                   "rest, and whatever washes up on Gallows Point is ours."),
        ])
    return world


async def vacancy_motel_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A roadside motel where Room 6 only opens after dark, and the clerk gets hungry."""

    del options
    from ..core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from ..mechanics.daggersim import (
        FeedingNeedComponent,
        SecretDoorComponent,
        SupernaturalAfflictionComponent,
    )
    from ..mechanics.dragonsim import DiscoveryComponent, PointOfInterestComponent
    from ..mechanics.environment import CalendarComponent, TimeOfDayComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="lot", title="Gravel Lot Under the Vacancy Sign", biome="roadside",
                     light=0.2, celsius=15.0),
            RoomSpec(key="office", title="Wood-Paneled Front Office", biome="motel",
                     indoor=True, light=0.5, celsius=22.0),
            RoomSpec(key="corridor", title="Carpeted Motel Corridor", biome="motel",
                     indoor=True, light=0.35, celsius=20.0),
            RoomSpec(key="room6", title="Room 6", biome="motel",
                     indoor=True, light=0.05, celsius=12.0),
        ],
        exits=[
            ExitSpec(from_key="lot", direction="in", to_key="office"),
            ExitSpec(from_key="office", direction="out", to_key="lot"),
            ExitSpec(from_key="office", direction="inside", to_key="corridor"),
            ExitSpec(from_key="corridor", direction="lobby", to_key="office"),
            ExitSpec(from_key="room6", direction="out", to_key="corridor"),
        ],
        objects=[
            ObjectSpec(key="vending", room_key="corridor", name="a humming vending machine",
                       kind="food", nutrition=3.0, satiety=9.0, portable=False),
            ObjectSpec(key="ice", room_key="corridor", name="a cloudy ice machine",
                       kind="water", hydration=12.0, portable=False),
            ObjectSpec(key="register", room_key="office", name="the guest register",
                       kind="paper", writable=True, portable=False),
            ObjectSpec(key="key6", room_key="office", name="a brass key on a Room 6 fob",
                       kind="item", portable=True),
        ],
        characters=[
            CharacterSpec(key="guest", name="Nadia Frost", room_key="office",
                          controller="suspended", traits=("road-weary", "skeptical", "tired"),
                          goals=("sleep off the drive", "check out by morning")),
            CharacterSpec(key="clerk", name="Vernon Pike", room_key="office",
                          species="nightfolk", controller="llm", llm_profile="night-clerk",
                          traits=("courteous", "unblinking", "hungry-after-dark"),
                          goals=("keep guests in their rooms after midnight",
                                 "never rent out Room 6")),
            CharacterSpec(key="maid", name="Lupe Ramos", room_key="corridor",
                          controller="llm", llm_profile="frightened-housekeeper",
                          traits=("kind", "frightened"),
                          goals=("warn Nadia off Room 6 without naming what is in it",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        # The motel checks in by daylight; the cycle rolls it into the dangerous small hours.
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(clock[0], WorldClockComponent(game_time_seconds=16 * 3600))
            clock[0].add_component(TimeOfDayComponent(phase="day"))
            clock[0].add_component(CalendarComponent(day=1, season="summer", hour=16))

        corridor, room6 = world.rooms["corridor"], world.rooms["room6"]
        _augment(actor, room6,
                 PointOfInterestComponent(location_type="sealed room", region="Route 9"),
                 DiscoveryComponent())
        _augment(actor, world.characters["clerk"],
                 SupernaturalAfflictionComponent(affliction_type="after-dark hunger",
                                                 contracted_at_epoch=0,
                                                 stage="mastered"),
                 FeedingNeedComponent(current=7.0, maximum=10.0))
        _add(actor, corridor, [
            IdentityComponent(name="a door numbered 6 that is not on the daytime map",
                              kind="secret-door"),
            SecretDoorComponent(target_room_id=str(room6), direction="end of the corridor",
                                hint="The corridor has five doors by day and six after dark."),
        ])
        _add(actor, room6, [
            IdentityComponent(name="a warped drawer hymnal", kind="paper"),
            PortableComponent(can_pick_up=True),
            ReadableComponent(title="Drawer Hymnal",
                              text="Margins full of names and dates in different hands, each one "
                                   "checked in after midnight and never checked out."),
        ])
        replace_component(
            actor.world.get_entity(world.objects["register"]),
            ReadableComponent(title="Guest Register",
                              text="House rule, underlined twice: do not assign Room 6, and do "
                                   "not let a guest wander the corridor after midnight."),
        )
    return world


async def frozen_greenhouse_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A greenhouse dome on a frozen plain, fighting the cold around a too-eager specimen."""

    del options
    from ..core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from ..mechanics.colonysim import (
        JobComponent,
        ResourceStackComponent,
        StockpileComponent,
        WorkstationComponent,
    )
    from ..mechanics.dragonsim import DiscoveryComponent, PointOfInterestComponent
    from ..mechanics.environment import CalendarComponent, TimeOfDayComponent, WeatherComponent
    from ..mechanics.gardensim import (
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
            RoomSpec(key="tundra", title="Wind-Scoured Tundra", biome="tundra",
                     light=0.6, celsius=-24.0),
            RoomSpec(key="dome", title="Geodesic Greenhouse Dome", biome="greenhouse",
                     indoor=True, light=0.9, celsius=19.0),
            RoomSpec(key="boiler", title="Boiler and Seed Vault", biome="greenhouse",
                     indoor=True, light=0.5, celsius=11.0),
        ],
        exits=[
            ExitSpec(from_key="tundra", direction="in", to_key="dome"),
            ExitSpec(from_key="dome", direction="out", to_key="tundra"),
            ExitSpec(from_key="dome", direction="down", to_key="boiler"),
            ExitSpec(from_key="boiler", direction="up", to_key="dome"),
        ],
        objects=[
            ObjectSpec(key="greens", room_key="boiler", name="a tray of ration greens",
                       kind="food", nutrition=4.0, satiety=12.0, portable=True),
            ObjectSpec(key="meltwater", room_key="boiler", name="a meltwater tank",
                       kind="water", hydration=15.0, portable=False),
            ObjectSpec(key="peat", room_key="boiler", name="a sack of dried peat fuel",
                       kind="item", portable=True),
            ObjectSpec(key="journal", room_key="boiler", name="a station research journal",
                       kind="paper", writable=True, portable=True),
        ],
        characters=[
            CharacterSpec(key="botanist", name="Dr. Imala Sorn", room_key="dome",
                          controller="suspended", traits=("meticulous", "cold-numbed", "uneasy"),
                          goals=("keep the dome above freezing", "catalogue the new specimen")),
            CharacterSpec(key="tech", name="Bo Anders", room_key="boiler",
                          controller="llm", llm_profile="station-tech",
                          traits=("practical", "tired"),
                          goals=("keep the boiler fed", "stop the specimen spreading")),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(
                clock[0], WorldClockComponent(game_time_seconds=winter_morning_seconds))
            clock[0].add_component(TimeOfDayComponent(phase="day"))
            clock[0].add_component(CalendarComponent(day=88, season="winter", hour=10))
            clock[0].add_component(WeatherComponent(condition="overcast", intensity=0.5))

        dome, boiler = world.rooms["dome"], world.rooms["boiler"]
        _add(actor, dome, [
            IdentityComponent(name="a raised bed of warmed soil", kind="soil"),
            SoilComponent(quality=1.1),
            TilledComponent(tilled_at_epoch=0),
        ])
        # An ordinary winter crop, growing at a sane pace.
        _add(actor, dome, [
            IdentityComponent(name="a row of winter kale", kind="crop"),
            CropComponent(crop_type="kale", planted_at_epoch=0, stage=1),
            CropGrowthComponent(progress_days=1.0, required_days=6.0, last_updated_epoch=0),
            HarvestableComponent(yield_item="kale", quantity=3),
            CropQualityComponent(quality=1.0),
        ])
        # The specimen: it should not grow in this cold, in the dark, this fast.
        _augment(actor, dome,
                 PointOfInterestComponent(location_type="quarantine bed", region="Station Drift-9"),
                 DiscoveryComponent())
        _add(actor, dome, [
            IdentityComponent(name="a pale specimen that grew overnight", kind="crop"),
            CropComponent(crop_type="specimen", planted_at_epoch=0, stage=2),
            CropGrowthComponent(progress_days=0.4, required_days=0.5, last_updated_epoch=0),
            HarvestableComponent(yield_item="spore pod", quantity=4),
            CropQualityComponent(quality=1.6),
        ])
        _add(actor, boiler, [
            IdentityComponent(name="a packet of saved seed", kind="item"),
            PortableComponent(can_pick_up=True),
            SeedComponent(crop_type="kale", growth_days=6.0, yield_item="kale", yield_quantity=3),
        ])
        _add(actor, boiler, [
            IdentityComponent(name="the dome boiler", kind="workstation"),
            WorkstationComponent(station_type="boiler"),
        ])
        _add(actor, boiler, [
            IdentityComponent(name="stoke the boiler job", kind="job"),
            JobComponent(job_type="haul", priority=4),
        ])
        _add(actor, boiler, [
            IdentityComponent(name="a peat fuel bin", kind="stockpile"),
            StockpileComponent(capacity=20),
            ResourceStackComponent(resource_type="peat", quantity=9),
        ])
        _add(actor, dome, [
            IdentityComponent(name="a frosted harvest crate", kind="shipping-bin"),
            ShippingBinComponent(),
        ])
        replace_component(
            actor.world.get_entity(world.objects["journal"]),
            ReadableComponent(title="Research Journal",
                              text="Specimen doubled again with the heat off and the sun down. "
                                   "It does not need us. Recommend we stop feeding the bed."),
        )
    return world


async def stuck_subway_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A subway car stalled between stations, strangers and failing systems in the dark."""

    del options
    from ..core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from ..mechanics.dragonsim import DiscoveryComponent, PointOfInterestComponent
    from ..mechanics.environment import CalendarComponent, TimeOfDayComponent
    from ..mechanics.lifesim import WhimComponent
    from ..mechanics.voidsim import (
        DistressSignalComponent,
        LifeSupportComponent,
        OxygenComponent,
        PowerGridComponent,
        ShipSystemComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="car", title="Stalled Subway Car", biome="subway",
                     indoor=True, light=0.3, celsius=27.0),
            RoomSpec(key="cab", title="Operator's Cab", biome="subway",
                     indoor=True, light=0.45, celsius=26.0),
            RoomSpec(key="tunnel", title="Dark Tunnel Catwalk", biome="tunnel",
                     indoor=True, light=0.05, celsius=18.0),
        ],
        exits=[
            ExitSpec(from_key="car", direction="fore", to_key="cab"),
            ExitSpec(from_key="cab", direction="aft", to_key="car"),
            ExitSpec(from_key="car", direction="emergency-door", to_key="tunnel"),
            ExitSpec(from_key="tunnel", direction="back-aboard", to_key="car"),
        ],
        objects=[
            ObjectSpec(key="pretzel", room_key="car", name="a half-eaten soft pretzel",
                       kind="food", nutrition=3.0, satiety=8.0, portable=True),
            ObjectSpec(key="bottle", room_key="car", name="a sweating water bottle",
                       kind="water", hydration=10.0, portable=True),
            ObjectSpec(key="notice", room_key="car", name="a laminated service notice",
                       kind="paper", writable=False, portable=False),
            ObjectSpec(key="map", room_key="car", name="a strip map of the line",
                       kind="paper", writable=False, portable=True),
        ],
        characters=[
            CharacterSpec(key="commuter", name="Priya Nadeau", room_key="car",
                          controller="suspended", traits=("anxious", "polite", "practical"),
                          goals=("get home tonight", "keep everyone calm")),
            CharacterSpec(key="operator", name="Gus Holloway", room_key="cab",
                          controller="llm", llm_profile="transit-operator",
                          traits=("gruff", "reassuring"),
                          goals=("restart the car", "keep passengers seated")),
            CharacterSpec(key="busker", name="Remy Osei", room_key="car",
                          controller="llm", llm_profile="stuck-busker",
                          traits=("easygoing", "talkative"),
                          goals=("lighten the mood", "busk for transfer fare")),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(clock[0], WorldClockComponent(game_time_seconds=18 * 3600))
            clock[0].add_component(TimeOfDayComponent(phase="dusk"))
            clock[0].add_component(CalendarComponent(day=1, season="summer", hour=18))

        car, cab, tunnel = world.rooms["car"], world.rooms["cab"], world.rooms["tunnel"]
        # The car's systems are failing: dim power, ventilation off, air going stale.
        _augment(actor, car,
                 PowerGridComponent(capacity=100.0, available=18.0),
                 LifeSupportComponent(online=False),
                 OxygenComponent(level=82.0, maximum=100.0))
        # The dead traction motor up front, and the intercom crackling at control.
        _add(actor, cab, [
            IdentityComponent(name="the traction motor", kind="ship-system"),
            ShipSystemComponent(system_type="traction motor", integrity=40.0, online=False),
        ])
        _add(actor, cab, [
            IdentityComponent(name="the cab intercom", kind="signal"),
            DistressSignalComponent(text="Control, car 1142 dead in the tube past Junction St."),
        ])
        # The clamped social want that makes the wait bite: a transfer she may now miss.
        _augment(actor, world.characters["commuter"],
                 WhimComponent(want="make the last cross-town transfer"))
        # The tunnel is pitch-dark and not somewhere passengers should wander.
        _augment(actor, tunnel,
                 PointOfInterestComponent(location_type="service tunnel", region="Junction St"),
                 DiscoveryComponent())
        _add(actor, car, [
            IdentityComponent(name="a strip map marked at the dead spot", kind="paper"),
            PortableComponent(can_pick_up=True),
            ReadableComponent(title="Strip Map",
                              text="Someone has circled the same stretch of tunnel three times "
                                   "and written: it always stops here."),
        ])
        replace_component(
            actor.world.get_entity(world.objects["notice"]),
            ReadableComponent(title="Service Notice",
                              text="In the event of an extended hold, remain in the car. Do not "
                                   "open the emergency door onto the trackway."),
        )
    return world


async def midnight_laundromat_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A 24-hour laundromat in the small hours: strangers, a broken dryer, a lost-and-found."""

    del options
    from ..core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from ..mechanics.dragonsim import DiscoveryComponent, PointOfInterestComponent
    from ..mechanics.environment import CalendarComponent, TimeOfDayComponent
    from ..mechanics.lifesim import WhimComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="sidewalk", title="Buzzing Sidewalk", biome="city-street",
                     light=0.1, celsius=13.0),
            RoomSpec(key="floor", title="All-Night Laundromat", biome="laundromat",
                     indoor=True, light=0.6, celsius=26.0),
            RoomSpec(key="back", title="Back Folding Room", biome="laundromat",
                     indoor=True, light=0.4, celsius=24.0),
        ],
        exits=[
            ExitSpec(from_key="sidewalk", direction="in", to_key="floor"),
            ExitSpec(from_key="floor", direction="out", to_key="sidewalk"),
            ExitSpec(from_key="floor", direction="back", to_key="back"),
            ExitSpec(from_key="back", direction="front", to_key="floor"),
        ],
        objects=[
            ObjectSpec(key="coffee", room_key="floor", name="a paper cup of machine coffee",
                       kind="water", hydration=10.0, portable=True),
            ObjectSpec(key="crackers", room_key="floor", name="a sleeve of vending crackers",
                       kind="food", nutrition=3.0, satiety=9.0, portable=True),
            ObjectSpec(key="dryer", room_key="floor", name="an out-of-order dryer",
                       kind="item", portable=False),
            ObjectSpec(key="lostbin", room_key="back", name="the lost-and-found bin",
                       kind="container", portable=False, open=False),
            ObjectSpec(key="mitten", room_key="back", name="a child's red mitten, unclaimed",
                       kind="item", portable=True),
        ],
        characters=[
            CharacterSpec(key="patron", name="Marisol Vega", room_key="floor",
                          controller="suspended", traits=("sleepless", "friendly", "curious"),
                          goals=("finish the wash in peace", "figure out the back room")),
            CharacterSpec(key="attendant", name="Sam Okafor", room_key="back",
                          controller="llm", llm_profile="night-attendant",
                          traits=("quiet", "watchful", "kind"),
                          goals=("keep the machines running", "mind the lost-and-found")),
            CharacterSpec(key="regular", name="Dot Pell", room_key="floor",
                          controller="llm", llm_profile="lonely-regular",
                          traits=("chatty", "lonely"),
                          goals=("talk to someone", "put off going home")),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        # It is already the small hours; the cycle carries the scene on toward dawn.
        clock = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        if clock:
            replace_component(clock[0], WorldClockComponent(game_time_seconds=1 * 3600))
            clock[0].add_component(TimeOfDayComponent(phase="night"))
            clock[0].add_component(CalendarComponent(day=1, season="autumn", hour=1))

        back = world.rooms["back"]
        # The night's small wants are what give the liminal hour its pull.
        _augment(actor, world.characters["patron"],
                 WhimComponent(want="get one full load done before dawn"))
        _augment(actor, world.characters["regular"],
                 WhimComponent(want="not be alone at two in the morning"))
        # The lost-and-found is the quiet mystery: things no one remembers leaving.
        _augment(actor, back,
                 PointOfInterestComponent(location_type="lost and found", region="Eighth Street"),
                 DiscoveryComponent())
        _add(actor, back, [
            IdentityComponent(name="a lost-and-found ledger", kind="paper"),
            PortableComponent(can_pick_up=True),
            ReadableComponent(title="Lost and Found Ledger",
                              text="Half the entries are in the attendant's hand, half in none "
                                   "he recognizes, logging coats and keys nobody came back for."),
        ])
        replace_component(
            actor.world.get_entity(world.objects["dryer"]),
            ReadableComponent(title="Taped-On Sign",
                              text="OUT OF ORDER. It still rumbles and turns some nights. Do not "
                                   "use it; do not open it while it does."),
        )
    return world


async def county_fair_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """Closing night of a county fair: a pie contest, a prize pumpkin, and a blue ribbon."""

    del options
    from ..core.components import IdentityComponent, ReadableComponent, WorldClockComponent
    from ..mechanics.dragonsim import (
        QuestComponent,
        QuestObjectiveComponent,
        QuestRewardComponent,
    )
    from ..mechanics.environment import CalendarComponent, TimeOfDayComponent
    from ..mechanics.gardensim import (
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
            RoomSpec(key="midway", title="Fairground Midway", biome="fairground",
                     light=0.4, celsius=16.0),
            RoomSpec(key="hall", title="Exhibition Hall", biome="fairground",
                     indoor=True, light=0.7, celsius=20.0),
            RoomSpec(key="barn", title="Livestock Barn", biome="fairground",
                     indoor=True, light=0.5, celsius=18.0),
        ],
        exits=[
            ExitSpec(from_key="midway", direction="in", to_key="hall"),
            ExitSpec(from_key="hall", direction="out", to_key="midway"),
            ExitSpec(from_key="hall", direction="barn", to_key="barn"),
            ExitSpec(from_key="barn", direction="hall", to_key="hall"),
        ],
        objects=[
            ObjectSpec(key="pie", room_key="hall", name="a blue-ribbon contender pie",
                       kind="food", nutrition=5.0, satiety=16.0, portable=True),
            ObjectSpec(key="lemonade", room_key="midway", name="a cup of fresh lemonade",
                       kind="water", hydration=13.0, portable=True),
            ObjectSpec(key="ferris", room_key="midway", name="the lit Ferris wheel",
                       kind="item", portable=False),
            ObjectSpec(key="ribbon", room_key="hall", name="an unawarded blue ribbon",
                       kind="item", portable=True),
        ],
        characters=[
            CharacterSpec(key="grower", name="Hattie Boone", room_key="hall",
                          controller="suspended", traits=("proud", "nervous", "green-thumbed"),
                          goals=("win the blue ribbon", "outgrow her rival's entry")),
            CharacterSpec(key="judge", name="Inez Coulter", room_key="hall",
                          controller="llm", llm_profile="fair-judge",
                          traits=("fair", "theatrical"),
                          goals=("crown a winner before the lights go out",)),
            CharacterSpec(key="rival", name="Cyrus Webb", room_key="barn",
                          controller="llm", llm_profile="fair-rival",
                          traits=("smug", "competitive"),
                          goals=("take the ribbon from Hattie", "show off his prize hog")),
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
        _add(actor, hall, [
            IdentityComponent(name="a championship prize pumpkin", kind="crop"),
            CropComponent(crop_type="pumpkin", planted_at_epoch=0, stage=3),
            CropGrowthComponent(progress_days=120.0, required_days=120.0, last_updated_epoch=0),
            HarvestableComponent(yield_item="pumpkin", quantity=1),
            CropQualityComponent(quality=2.0),
        ])
        # The judging table where entries are weighed and scored.
        _add(actor, hall, [
            IdentityComponent(name="the judging entry table", kind="shipping-bin"),
            ShippingBinComponent(),
        ])
        # The blue-ribbon quest, still up for grabs on closing night.
        _add(actor, hall, [
            IdentityComponent(name="Win the Blue Ribbon", kind="quest"),
            QuestComponent(quest_id="blue-ribbon", title="Win the Blue Ribbon",
                           status="offered"),
            QuestObjectiveComponent(quest_id="blue-ribbon",
                                    description="Enter the best produce before judging closes"),
            QuestRewardComponent(quest_id="blue-ribbon",
                                 description="the county fair blue ribbon and bragging rights"),
        ])
        replace_component(
            actor.world.get_entity(world.objects["ribbon"]),
            ReadableComponent(title="Blue Ribbon",
                              text="FIRST PLACE — to be pinned to the winning entry at the close "
                                   "of judging. The card beneath it is still blank."),
        )
    return world


LIFESIM_DEMO = WorldGenerator(
    name="lifesim-demo",
    generate=_with_regions(
        lifesim_example, (("Cloverbrook Vale", "region"), ("Clover Hollow", "area"))),
    description="A household with careers, skills, money, relationships, and aspirations.",
    group="simpack sandbox",
    uses_seed=False)
GARDENSIM_DEMO = WorldGenerator(
    name="gardensim-demo",
    generate=_with_regions(
        gardensim_example, (("Greenhollow", "region"), ("Bramblewick Farm", "area"))),
    description="A farm with tilled soil, a growing crop, and seeds.",
    group="simpack sandbox",
    uses_seed=False)
MAPLE_FARM_DEMO = WorldGenerator(
    name="maple-farm-demo",
    generate=_with_regions(
        maple_farm_example, (("Laurentian Uplands", "region"), ("Snowbank Farm", "area"))),
    description="A Canadian maple syrup farm with trees to wait for, tap, and harvest sap from.",
    group="simpack sandbox",
    uses_seed=False)
COLONYSIM_DEMO = WorldGenerator(
    name="colonysim-demo",
    generate=_with_regions(
        colonysim_example, (("Verdant Frontier", "region"), ("Camp Theta", "zone"))),
    description="A work camp with resources, a workstation, a recipe, and a job.",
    group="simpack sandbox",
    uses_seed=False)
BARBARIANSIM_DEMO = WorldGenerator(
    name="barbariansim-demo",
    generate=_with_regions(
        barbariansim_example, (("Frostfang Reaches", "region"), ("Wolfwind Pass", "zone"))),
    description="A frozen ridge with a sheltered cave, gear, and corruption pressure.",
    group="simpack sandbox",
    uses_seed=False)
DRAGONSIM_DEMO = WorldGenerator(
    name="dragonsim-demo",
    generate=_with_regions(
        dragonsim_example, (("Mistmoor Vale", "region"), ("Mistmoor Village", "neighborhood"))),
    description="A village with an undiscovered barrow, a faction, and a quest.",
    group="simpack sandbox",
    uses_seed=False)
DAGGERSIM_DEMO = WorldGenerator(
    name="daggersim-demo",
    generate=_with_regions(
        daggersim_example, (("Daggerfell Reach", "region"), ("Greywall", "city"))),
    description="A town with a bank, guild, rumor, travel, and a frontier site.",
    group="simpack sandbox",
    uses_seed=False)
VOIDSIM_DEMO = WorldGenerator(
    name="voidsim-demo",
    generate=_with_regions(
        voidsim_example, (("Helios Sector", "sector"), ("ISV Wanderer", "ship"))),
    description="A modular ship with life support, power, and a damaged reactor.",
    group="simpack sandbox",
    uses_seed=False)
NUKESIM_DEMO = WorldGenerator(
    name="nukesim-demo",
    generate=_with_regions(
        nukesim_example, (("The Glowlands", "region"), ("Rustwater Flats", "area"))),
    description="A wasteland checkpoint with radiation, scavenging, decon, and scrap crafting.",
    group="simpack sandbox",
    uses_seed=False)
NEONSIM_DEMO = WorldGenerator(
    name="neonsim-demo",
    generate=_with_regions(
        neonsim_example, (("Night City", "city"), ("Watson", "neighborhood"))),
    description="A neon strip and corp office with surveillance, a hackable server, a fixer "
                "contract, a ripperdoc, and a runner ready to break in.",
    group="simpack sandbox",
    uses_seed=False)
DINOSIM_DEMO = WorldGenerator(
    name="dinosim-demo",
    generate=_with_regions(
        dinosim_example, (("Isla Vega", "region"), ("Cretaceous Compound", "zone"))),
    description="A hatchery with fossils, a ready egg, and a fertile dinosaur parent.",
    group="simpack sandbox",
    uses_seed=False)
CLUE_SNACK_DEMO = WorldGenerator(
    name="clue-snack-demo",
    generate=_with_regions(
        clue_snack_example, (("Pinecrest", "area"), ("Mascot Lodge", "building"))),
    description=(
        "A legally distinct comic mystery with snacks, a talking hound, and a fake haunting."
    ),
    group="pop culture",
    uses_seed=False)
DIVE_SCHEME_DEMO = WorldGenerator(
    name="dive-scheme-demo",
    generate=_with_regions(
        dive_scheme_example,
        (("Saltport Harbor", "neighborhood"), ("The Gull & Grift", "building"))),
    description="A legally distinct dysfunctional tavern sitcom full of bad schemes.",
    group="pop culture",
    uses_seed=False)
STAR_OPERA_DEMO = WorldGenerator(
    name="star-opera-demo",
    generate=_with_regions(
        star_opera_example, (("Saffron Sector", "sector"), ("Duneport", "city"))),
    description="A legally distinct star-opera rebellion at a desert port and rusty freighter.",
    group="pop culture",
    uses_seed=False)
GOTHIC_COUNT_DEMO = WorldGenerator(
    name="gothic-count-demo",
    generate=_with_regions(
        gothic_count_example, (("Carpathian Marches", "country"), ("Castle Mordrath", "building"))),
    description="A legally distinct gothic night-host castle with papers, secrets, and hunger.",
    group="pop culture",
    uses_seed=False)
MIDNIGHT_BURGER_DEMO = WorldGenerator(
    name="midnight-burger-demo",
    generate=_with_regions(
        midnight_burger_example, (("East Side", "neighborhood"), ("Patty Stack", "building"))),
    description="An inner-city burger shack that opens at dusk and rolls into night, with a "
                "hungry night cook and a hidden cellar that is only dangerous after dark.",
    group="pop culture",
    uses_seed=False)
DUNGEON_VAULT_DEMO = WorldGenerator(
    name="dungeon-vault-demo",
    generate=_with_regions(
        dungeon_vault_example, (("Emberdeep", "region"), ("Ember Vault", "dungeon"))),
    description="A torchlit hand-built vault with a hidden relic room and dungeon map.",
    group="dungeon",
    uses_seed=False)
DUNGEON_MAZE_DEMO = WorldGenerator(
    name="dungeon-maze-demo",
    generate=_with_regions(
        dungeon_maze_example, (("Slatewarren", "region"), ("Slate Maze", "dungeon"))),
    description="A looping slate maze for classic mapping, backtracking, and secret hunting.",
    group="dungeon",
    uses_seed=False)
DUNGEON_CRYPT_DEMO = WorldGenerator(
    name="dungeon-crypt-demo",
    generate=_with_regions(
        dungeon_crypt_example, (("Saintswood", "region"), ("Hollow Crypt", "dungeon"))),
    description="A chapel crypt with locked passages, readable clues, and a reliquary.",
    group="dungeon",
    uses_seed=False)
STORM_LIGHTHOUSE_DEMO = WorldGenerator(
    name="storm-lighthouse-demo",
    generate=_with_regions(
        storm_lighthouse_example, (("Saltreef Coast", "area"), ("Gull Point Light", "building"))),
    description="A coastal lighthouse in an autumn squall, with a beacon to keep fueled, a "
                "stranded sailor, and a wrecker's secret hidden under the lens.",
    group="scene demo",
    uses_seed=False)
VACANCY_MOTEL_DEMO = WorldGenerator(
    name="vacancy-motel-demo",
    generate=_with_regions(
        vacancy_motel_example, (("Route 9", "region"), ("The Vacancy Motel", "building"))),
    description="A roadside motel that checks in by day and rolls into night, where Room 6 "
                "only opens after dark and the night clerk gets hungry.",
    group="scene demo",
    uses_seed=False)
FROZEN_GREENHOUSE_DEMO = WorldGenerator(
    name="frozen-greenhouse-demo",
    generate=_with_regions(
        frozen_greenhouse_example, (("Borealis Flats", "region"), ("Dome Station 7", "building"))),
    description="A greenhouse dome on a frozen winter plain with crops to keep warm, a boiler "
                "to stoke, and a specimen that grows too fast in the dark and cold.",
    group="scene demo",
    uses_seed=False)
STUCK_SUBWAY_DEMO = WorldGenerator(
    name="stuck-subway-demo",
    generate=_with_regions(
        stuck_subway_example, (("Metro Line 4", "zone"), ("Tunnel Section 12", "area"))),
    description="A subway car stalled between stations with dim power, dead ventilation, a "
                "dead traction motor, and strangers waiting out the hold in the dark.",
    group="scene demo",
    uses_seed=False)
MIDNIGHT_LAUNDROMAT_DEMO = WorldGenerator(
    name="midnight-laundromat-demo",
    generate=_with_regions(
        midnight_laundromat_example, (("Riverside", "neighborhood"), ("Suds & Such", "building"))),
    description="A 24-hour laundromat in the small hours rolling toward dawn, with late-night "
                "strangers, a broken dryer, and a lost-and-found nobody remembers filling.",
    group="scene demo",
    uses_seed=False)
COUNTY_FAIR_DEMO = WorldGenerator(
    name="county-fair-demo",
    generate=_with_regions(
        county_fair_example, (("Harvest County", "region"), ("County Fairgrounds", "zone"))),
    description="A closing night at an autumn county fair, with a pie contest, a championship "
                "prize pumpkin, a smug rival, and a blue ribbon still up for grabs.",
    group="scene demo",
    uses_seed=False)

POP_CULTURE_DEMOS = (
    CLUE_SNACK_DEMO,
    DIVE_SCHEME_DEMO,
    STAR_OPERA_DEMO,
    GOTHIC_COUNT_DEMO,
    MIDNIGHT_BURGER_DEMO,
)

DUNGEON_DEMOS = (
    DUNGEON_VAULT_DEMO,
    DUNGEON_MAZE_DEMO,
    DUNGEON_CRYPT_DEMO,
)

SCENE_DEMOS = (
    STORM_LIGHTHOUSE_DEMO,
    VACANCY_MOTEL_DEMO,
    FROZEN_GREENHOUSE_DEMO,
    STUCK_SUBWAY_DEMO,
    MIDNIGHT_LAUNDROMAT_DEMO,
    COUNTY_FAIR_DEMO,
)


__all__ = [
    "BARBARIANSIM_DEMO",
    "CLUE_SNACK_DEMO",
    "COLONYSIM_DEMO",
    "COUNTY_FAIR_DEMO",
    "DAGGERSIM_DEMO",
    "DINOSIM_DEMO",
    "DRAGONSIM_DEMO",
    "DUNGEON_CRYPT_DEMO",
    "DUNGEON_DEMOS",
    "DUNGEON_MAZE_DEMO",
    "DUNGEON_VAULT_DEMO",
    "DIVE_SCHEME_DEMO",
    "FROZEN_GREENHOUSE_DEMO",
    "GARDENSIM_DEMO",
    "GOTHIC_COUNT_DEMO",
    "LIFESIM_DEMO",
    "MAPLE_FARM_DEMO",
    "MIDNIGHT_BURGER_DEMO",
    "MIDNIGHT_LAUNDROMAT_DEMO",
    "NEONSIM_DEMO",
    "NUKESIM_DEMO",
    "POP_CULTURE_DEMOS",
    "SCENE_DEMOS",
    "STAR_OPERA_DEMO",
    "STORM_LIGHTHOUSE_DEMO",
    "STUCK_SUBWAY_DEMO",
    "VACANCY_MOTEL_DEMO",
    "VOIDSIM_DEMO",
    "barbariansim_example",
    "clue_snack_example",
    "colonysim_example",
    "county_fair_example",
    "daggersim_example",
    "dinosim_example",
    "dragonsim_example",
    "dungeon_crypt_example",
    "dungeon_maze_example",
    "dungeon_vault_example",
    "dive_scheme_example",
    "frozen_greenhouse_example",
    "gardensim_example",
    "gothic_count_example",
    "lifesim_example",
    "maple_farm_example",
    "midnight_burger_example",
    "midnight_laundromat_example",
    "neonsim_example",
    "nukesim_example",
    "star_opera_example",
    "storm_lighthouse_example",
    "stuck_subway_example",
    "vacancy_motel_example",
    "voidsim_example",
]
