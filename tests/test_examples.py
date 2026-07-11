"""Each sim package ships a deterministic example world that instantiates and shows off
its hallmark mechanics (plus the life-sim needs every character inherits)."""

from __future__ import annotations

import re

import pytest

from bunnyland.core import SuspendedComponent, WorldActor, container_of
from bunnyland.core.components import (
    DescriptionComponent,
    IdentityComponent,
    LightComponent,
    ReadableComponent,
    RegionComponent,
    RoomComponent,
    TemperatureComponent,
)
from bunnyland.core.edges import ContainmentMode, Contains
from bunnyland.foundation.consumables.components import DrinkableComponent, FoodComponent
from bunnyland.foundation.environment.mechanics import (
    CalendarComponent,
    FireComponent,
    FlammableComponent,
    TimeOfDayComponent,
    WeatherComponent,
    install_environment,
)
from bunnyland.foundation.needs.mechanics import HungerComponent
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.simpacks.barbariansim.mechanics import WeaponComponent
from bunnyland.simpacks.colonysim.mechanics import (
    ColonyIncidentComponent,
    JobBillComponent,
    PawnProfileComponent,
    PrisonerComponent,
    RecipeComponent,
    ResearchProjectComponent,
    ResourceNodeComponent,
    StockpileComponent,
    SurgeryBillComponent,
    TradeOfferComponent,
    WorkstationComponent,
)
from bunnyland.simpacks.daggersim.mechanics import (
    AutomapComponent,
    BankComponent,
    DungeonComponent,
    DungeonObjectiveComponent,
    DungeonRoomComponent,
    FeedingNeedComponent,
    RestRiskComponent,
    SecretDoorComponent,
    SupernaturalAfflictionComponent,
)
from bunnyland.simpacks.dinosim.mechanics import (
    CreatureProductComponent,
    DinosaurComponent,
    FeedStoreComponent,
    FertilityComponent,
    FossilFragmentComponent,
    ReptileProcreationComponent,
)
from bunnyland.simpacks.dragonsim.mechanics import PointOfInterestComponent, QuestComponent
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
    ShippingBinComponent,
    TreeComponent,
    TreeTapComponent,
    WeedComponent,
)
from bunnyland.simpacks.lifesim.mechanics import (
    CareerComponent,
    CharacterProfileComponent,
    HomeObjectComponent,
    WhimComponent,
)
from bunnyland.simpacks.neonsim.mechanics import CyberpunkSiteComponent
from bunnyland.simpacks.nukesim.mechanics import RadiationSourceComponent
from bunnyland.simpacks.voidsim.mechanics import (
    HabitatModuleComponent,
    LifeSupportComponent,
    PowerGridComponent,
    ShipComponent,
    ShipSystemComponent,
)
from bunnyland.worldgen.examples import (
    BARBARIANSIM_DEMO,
    COLONYSIM_DEMO,
    COUNTY_FAIR_DEMO,
    DAGGERSIM_DEMO,
    DINOSIM_DEMO,
    DRAGONSIM_DEMO,
    DUNGEON_DEMOS,
    FROZEN_GREENHOUSE_DEMO,
    GARDENSIM_DEMO,
    LIFESIM_DEMO,
    MAPLE_FARM_DEMO,
    MIDNIGHT_BURGER_DEMO,
    MIDNIGHT_LAUNDROMAT_DEMO,
    NEONSIM_DEMO,
    NUKESIM_DEMO,
    POP_CULTURE_DEMOS,
    SCENE_DEMOS,
    STORM_LIGHTHOUSE_DEMO,
    STUCK_SUBWAY_DEMO,
    VACANCY_MOTEL_DEMO,
    VOIDSIM_DEMO,
)
from bunnyland.worldgen.generators import GenOptions, collect_generators

PACKAGE_DEMOS = [
    LIFESIM_DEMO,
    GARDENSIM_DEMO,
    COLONYSIM_DEMO,
    BARBARIANSIM_DEMO,
    DRAGONSIM_DEMO,
    DAGGERSIM_DEMO,
    VOIDSIM_DEMO,
    NUKESIM_DEMO,
    NEONSIM_DEMO,
    DINOSIM_DEMO,
]
ALL_DEMOS = [
    *PACKAGE_DEMOS,
    MAPLE_FARM_DEMO,
    *POP_CULTURE_DEMOS,
    *DUNGEON_DEMOS,
    *SCENE_DEMOS,
]

# Each demo's hallmark component — proof its package's mechanics are present.
HALLMARKS = {
    LIFESIM_DEMO.name: CareerComponent,
    GARDENSIM_DEMO.name: CropComponent,
    COLONYSIM_DEMO.name: ResourceNodeComponent,
    BARBARIANSIM_DEMO.name: WeaponComponent,
    DRAGONSIM_DEMO.name: QuestComponent,
    DAGGERSIM_DEMO.name: BankComponent,
    VOIDSIM_DEMO.name: ShipComponent,
    NUKESIM_DEMO.name: RadiationSourceComponent,
    NEONSIM_DEMO.name: CyberpunkSiteComponent,
    DINOSIM_DEMO.name: DinosaurComponent,
}


def _has(actor: WorldActor, component_type) -> bool:
    return bool(list(actor.world.query().with_all([component_type]).execute_entities()))


def _regions(actor: WorldActor):
    return list(actor.world.query().with_all([RegionComponent]).execute_entities())


def _rooms_under_regions(actor: WorldActor) -> set:
    """Room ids reached from any region via a REGION-mode ``Contains`` edge."""
    room_ids = set()
    for region in _regions(actor):
        for edge, child_id in region.get_relationships(Contains):
            if edge.mode != ContainmentMode.REGION:
                continue
            if actor.world.get_entity(child_id).has_component(RoomComponent):
                room_ids.add(child_id)
    return room_ids


def _visible_text(actor: WorldActor) -> str:
    texts: list[str] = []
    for entity in actor.world.query().execute_entities():
        if entity.has_component(IdentityComponent):
            identity = entity.get_component(IdentityComponent)
            texts.extend([identity.name, identity.kind, *identity.tags])
        if entity.has_component(RoomComponent):
            room = entity.get_component(RoomComponent)
            texts.extend([room.title, room.biome])
        if entity.has_component(DescriptionComponent):
            description = entity.get_component(DescriptionComponent)
            texts.extend([description.short, description.long, description.appearance])
        if entity.has_component(ReadableComponent):
            readable = entity.get_component(ReadableComponent)
            texts.extend([readable.title or "", readable.text])
    return "\n".join(text for text in texts if text)


@pytest.mark.parametrize("demo", ALL_DEMOS, ids=lambda d: d.name)
async def test_demo_world_has_rooms_characters_and_needs(demo):
    actor = WorldActor()

    world = await demo.generate(actor, demo.name, GenOptions())

    assert world.rooms, "demo world should have rooms"
    assert world.characters, "demo world should have characters"
    # Every demo builds on life-sim: characters get needs from instantiate.
    assert _has(actor, HungerComponent)


@pytest.mark.parametrize("demo", ALL_DEMOS, ids=lambda d: d.name)
async def test_demo_world_has_a_multi_level_region_above_its_rooms(demo):
    actor = WorldActor()

    world = await demo.generate(actor, demo.name, GenOptions())

    regions = _regions(actor)
    # Nested levels above the rooms populate the inspector's region view.
    assert len(regions) >= 2
    # Every room sits under a region via REGION-mode Contains edges.
    assert _rooms_under_regions(actor) == set(world.rooms.values())
    # The levels are distinct: at least one region nests another region.
    assert any(
        edge.mode == ContainmentMode.REGION
        and actor.world.get_entity(child_id).has_component(RegionComponent)
        for region in regions
        for edge, child_id in region.get_relationships(Contains)
    )


@pytest.mark.parametrize("demo", PACKAGE_DEMOS, ids=lambda d: d.name)
async def test_demo_world_includes_its_hallmark_mechanic(demo):
    actor = WorldActor()

    await demo.generate(actor, demo.name, GenOptions())

    assert _has(actor, HALLMARKS[demo.name])


@pytest.mark.parametrize("demo", PACKAGE_DEMOS, ids=lambda d: d.name)
async def test_demo_world_generates_with_enrichment_plugins(demo):
    # On a running server the built-in enrichment hooks are subscribed and add components
    # (e.g. a PointOfInterest to any 'ruin' room) during instantiate(). A demo's curated
    # _augment components must override those rather than raw-adding a duplicate and
    # crashing generation with DuplicateComponentError.
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)

    await demo.generate(actor, demo.name, GenOptions())


async def test_dragonsim_demo_curated_poi_wins_over_enrichment_hook():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)

    world = await DRAGONSIM_DEMO.generate(actor, DRAGONSIM_DEMO.name, GenOptions())

    # The enrichment hook tags the 'ruin' room as a generic POI during instantiate; the
    # demo's curated barrow POI must take precedence instead of colliding.
    ruin = actor.world.get_entity(world.rooms["ruin"])
    poi = ruin.get_component(PointOfInterestComponent)
    assert poi.location_type == "barrow"
    assert poi.region == "Mistmoor"


async def test_voidsim_demo_rooms_are_habitat_modules():
    actor = WorldActor()

    await VOIDSIM_DEMO.generate(actor, "voidsim-demo", GenOptions())

    assert _has(actor, HabitatModuleComponent)


async def test_dinosim_demo_includes_fossil_and_fertile_parent():
    actor = WorldActor()

    await DINOSIM_DEMO.generate(actor, "dinosim-demo", GenOptions())

    assert _has(actor, FossilFragmentComponent)
    assert _has(actor, FeedStoreComponent)
    assert _has(actor, CreatureProductComponent)
    assert bool(
        list(
            actor.world.query()
            .with_all([DinosaurComponent, FertilityComponent, ReptileProcreationComponent])
            .execute_entities()
        )
    )


async def test_colonysim_demo_includes_stockpile_storage():
    actor = WorldActor()

    await COLONYSIM_DEMO.generate(actor, "colonysim-demo", GenOptions())

    assert _has(actor, StockpileComponent)
    assert _has(actor, PawnProfileComponent)
    assert _has(actor, PrisonerComponent)
    assert _has(actor, JobBillComponent)
    assert _has(actor, ResearchProjectComponent)
    assert _has(actor, TradeOfferComponent)
    assert _has(actor, ColonyIncidentComponent)
    assert _has(actor, SurgeryBillComponent)


async def test_lifesim_demo_includes_profile_whim_and_home_objects():
    actor = WorldActor()

    await LIFESIM_DEMO.generate(actor, "lifesim-demo", GenOptions())

    assert _has(actor, CharacterProfileComponent)
    assert _has(actor, WhimComponent)
    assert _has(actor, HomeObjectComponent)


async def test_gardensim_demo_includes_catalogue_farm_surfaces():
    actor = WorldActor()

    await GARDENSIM_DEMO.generate(actor, "gardensim-demo", GenOptions())

    assert _has(actor, CropQualityComponent)
    assert _has(actor, RegrowableComponent)
    assert _has(actor, PestComponent)
    assert _has(actor, WeedComponent)
    assert _has(actor, MachineComponent)
    assert _has(actor, ShippingBinComponent)
    assert _has(actor, MineLevelComponent)
    assert _has(actor, LadderComponent)
    assert _has(actor, GeodeComponent)
    assert _has(actor, MailComponent)
    assert _has(actor, FarmQuestComponent)
    assert _has(actor, MuseumCollectionComponent)


async def test_maple_farm_demo_is_a_functional_canadian_sugarbush():
    actor = WorldActor()

    await MAPLE_FARM_DEMO.generate(actor, "maple-farm-demo", GenOptions())

    assert _has(actor, TreeComponent)
    assert _has(actor, TreeTapComponent)
    assert _has(actor, HarvestableComponent)
    assert _has(actor, WorkstationComponent)
    assert _has(actor, RecipeComponent)
    assert _has(actor, StockpileComponent)
    assert _has(actor, CalendarComponent)

    corpus = _visible_text(actor)
    assert "Quebec Maple Grove" in corpus
    assert "Sugar Shack" in corpus
    assert "maple sap" in corpus

    trees = list(actor.world.query().with_all([TreeComponent]).execute_entities())
    assert any(not tree.get_component(TreeComponent).mature for tree in trees)
    assert any(
        tree.has_component(TreeTapComponent) and not tree.get_component(HarvestableComponent).ready
        for tree in trees
    )


async def test_midnight_burger_demo_secret_is_gated_by_a_running_night_cycle():
    actor = WorldActor()

    world = await MIDNIGHT_BURGER_DEMO.generate(actor, "midnight-burger-demo", GenOptions())

    # The shack opens during the day — the world is not frozen at night.
    clock = list(actor.world.query().with_all([TimeOfDayComponent]).execute_entities())[0]
    assert clock.get_component(TimeOfDayComponent).phase == "day"
    assert clock.get_component(CalendarComponent).hour == 17

    # The dark secret: a hungry night cook and a hidden, pitch-dark cellar behind the kitchen.
    cook = list(actor.world.query().with_all([SupernaturalAfflictionComponent]).execute_entities())[
        0
    ]
    assert cook.get_component(SupernaturalAfflictionComponent).affliction_type == "nocturnal hunger"
    assert cook.has_component(FeedingNeedComponent)
    assert _has(actor, SecretDoorComponent)
    cellar = actor.world.get_entity(world.rooms["cellar"])
    assert cellar.has_component(PointOfInterestComponent)
    assert cellar.get_component(LightComponent).level <= 0.1

    # Let the clock run: within a few hourly ticks the shack tips into the dangerous night.
    install_environment(actor)
    await actor.tick(3 * 3600)  # 17:00 -> 20:00
    assert clock.get_component(TimeOfDayComponent).phase == "night"


async def test_storm_lighthouse_demo_keeps_a_beacon_burning_through_a_squall():
    actor = WorldActor()

    world = await STORM_LIGHTHOUSE_DEMO.generate(actor, "storm-lighthouse-demo", GenOptions())

    # A lit beacon that burns its own fuel down — something to keep feeding.
    assert _has(actor, FireComponent)
    assert _has(actor, FlammableComponent)
    # The buried sin: a wrecker's niche behind a secret hatch under the lens.
    assert _has(actor, SecretDoorComponent)
    assert actor.world.get_entity(world.rooms["niche"]).has_component(PointOfInterestComponent)

    # The deterministic weather cycle keeps the squall blowing and the jetty dim as it ticks.
    install_environment(actor)
    await actor.tick(3600)  # day 61, 18:00 -> 19:00, still a rain day
    clock = list(actor.world.query().with_all([WeatherComponent]).execute_entities())[0]
    assert clock.get_component(WeatherComponent).condition == "rain"
    assert actor.world.get_entity(world.rooms["jetty"]).get_component(LightComponent).level <= 0.25


async def test_vacancy_motel_demo_room_six_is_a_night_gated_secret():
    actor = WorldActor()

    world = await VACANCY_MOTEL_DEMO.generate(actor, "vacancy-motel-demo", GenOptions())

    # Guests check in by daylight — Room 6 is not dangerous yet.
    clock = list(actor.world.query().with_all([TimeOfDayComponent]).execute_entities())[0]
    assert clock.get_component(TimeOfDayComponent).phase == "day"

    # The secret: a hungry night clerk and a sealed, pitch-dark Room 6 off the corridor.
    motel_clerk = list(
        actor.world.query().with_all([SupernaturalAfflictionComponent]).execute_entities()
    )[0]
    assert motel_clerk.get_component(SupernaturalAfflictionComponent).affliction_type == (
        "after-dark hunger"
    )
    assert motel_clerk.has_component(FeedingNeedComponent)
    assert _has(actor, SecretDoorComponent)
    room6 = actor.world.get_entity(world.rooms["room6"])
    assert room6.has_component(PointOfInterestComponent)
    assert room6.get_component(LightComponent).level <= 0.1

    # As the night cycle runs the motel tips into the dangerous small hours.
    install_environment(actor)
    await actor.tick(5 * 3600)  # 16:00 -> 21:00
    assert clock.get_component(TimeOfDayComponent).phase == "night"


async def test_frozen_greenhouse_demo_grows_crops_against_the_cold():
    actor = WorldActor()

    world = await FROZEN_GREENHOUSE_DEMO.generate(actor, "frozen-greenhouse-demo", GenOptions())

    # Crops to tend and a boiler to stoke against the freeze.
    assert _has(actor, CropComponent)
    assert _has(actor, WorkstationComponent)
    assert (
        actor.world.get_entity(world.rooms["tundra"]).get_component(TemperatureComponent).celsius
        <= -10.0
    )

    # The unnatural specimen grows far faster than the ordinary winter crop.
    growths = [
        entity.get_component(CropGrowthComponent).required_days
        for entity in actor.world.query().with_all([CropGrowthComponent]).execute_entities()
    ]
    assert any(required <= 1.0 for required in growths)
    assert actor.world.get_entity(world.rooms["dome"]).has_component(PointOfInterestComponent)


async def test_stuck_subway_demo_is_a_failing_car_full_of_strangers():
    actor = WorldActor()

    world = await STUCK_SUBWAY_DEMO.generate(actor, "stuck-subway-demo", GenOptions())

    # The car's systems are failing: dim power and dead ventilation.
    car = actor.world.get_entity(world.rooms["car"])
    assert car.has_component(PowerGridComponent)
    assert car.get_component(LifeSupportComponent).online is False

    # A dead traction motor up front.
    motor = list(actor.world.query().with_all([ShipSystemComponent]).execute_entities())[0]
    assert motor.get_component(ShipSystemComponent).online is False

    # The clamped social want that makes the wait bite.
    assert _has(actor, WhimComponent)


async def test_midnight_laundromat_demo_drifts_from_night_toward_dawn():
    actor = WorldActor()

    world = await MIDNIGHT_LAUNDROMAT_DEMO.generate(actor, "midnight-laundromat-demo", GenOptions())

    # It is already the small hours, and late-night wants give the scene its pull.
    clock = list(actor.world.query().with_all([TimeOfDayComponent]).execute_entities())[0]
    assert clock.get_component(TimeOfDayComponent).phase == "night"
    whims = list(actor.world.query().with_all([WhimComponent]).execute_entities())
    assert len(whims) >= 2

    # The quiet mystery: a lost-and-found nobody remembers filling.
    assert actor.world.get_entity(world.rooms["back"]).has_component(PointOfInterestComponent)

    # The cycle carries the small hours on toward morning.
    install_environment(actor)
    await actor.tick(4 * 3600)  # 01:00 -> 05:00
    assert clock.get_component(TimeOfDayComponent).phase == "dawn"


async def test_county_fair_demo_has_a_blue_ribbon_contest_and_a_prize_entry():
    actor = WorldActor()

    world = await COUNTY_FAIR_DEMO.generate(actor, "county-fair-demo", GenOptions())

    # The blue-ribbon quest is still up for grabs on closing night.
    quest = list(actor.world.query().with_all([QuestComponent]).execute_entities())[0]
    assert quest.get_component(QuestComponent).quest_id == "blue-ribbon"
    from bunnyland.simpacks.dragonsim.mechanics import QuestStateComponent

    assert quest.get_component(QuestStateComponent).status == "offered"

    # A championship-quality produce entry to win it with.
    qualities = [
        entity.get_component(CropQualityComponent).quality
        for entity in actor.world.query().with_all([CropQualityComponent]).execute_entities()
    ]
    assert any(quality >= 1.5 for quality in qualities)

    # A rival to beat: the fair is a social contest, not a solo scene.
    assert len(world.characters) >= 3


@pytest.mark.parametrize("demo", DUNGEON_DEMOS, ids=lambda d: d.name)
async def test_dungeon_demo_worlds_feel_like_hand_built_crawls(demo):
    actor = WorldActor()

    world = await demo.generate(actor, demo.name, GenOptions())

    assert len(world.rooms) >= 5
    assert len(world.characters) >= 2
    assert _has(actor, DungeonComponent)
    assert _has(actor, DungeonRoomComponent)
    assert _has(actor, SecretDoorComponent)
    assert _has(actor, DungeonObjectiveComponent)
    assert _has(actor, RestRiskComponent)
    assert _has(actor, FoodComponent)
    assert _has(actor, DrinkableComponent)

    claimable = actor.world.get_entity(next(iter(world.characters.values())))
    assert claimable.has_component(SuspendedComponent)
    assert claimable.has_component(AutomapComponent)
    assert container_of(claimable) in set(world.rooms.values())

    dungeon_rooms = list(actor.world.query().with_all([DungeonRoomComponent]).execute_entities())
    assert any(room.get_component(DungeonRoomComponent).is_objective for room in dungeon_rooms)


@pytest.mark.parametrize("demo", POP_CULTURE_DEMOS, ids=lambda d: d.name)
async def test_pop_culture_demo_worlds_stay_legally_distinct(demo):
    actor = WorldActor()

    await demo.generate(actor, demo.name, GenOptions())

    protected_terms = (
        "always sunny",
        "chewbacca",
        "charlie",
        "dee",
        "dennis",
        "dracula",
        "frank",
        "han",
        "harker",
        "jedi",
        "leia",
        "luke",
        "mac",
        "mystery machine",
        "paddy",
        "philadelphia",
        "rogers",
        "scooby",
        "shaggy",
        "sith",
        "star wars",
        "vader",
        "van helsing",
    )
    corpus = _visible_text(actor).lower()
    for term in protected_terms:
        assert not re.search(rf"\b{re.escape(term)}\b", corpus), term


def test_every_demo_is_registered_under_its_plugin():
    registry = collect_generators(bunnyland_plugins())
    for demo in ALL_DEMOS:
        assert registry.get(demo.name) is demo


# Demos whose builders set the scene's time/weather behind an ``if clock:`` guard. The guard
# is normally true (``instantiate`` lays down a world clock), so its false arm -- the world
# somehow having no clock -- is otherwise unreachable from these tests.
CLOCK_GUARDED_DEMOS = [
    MAPLE_FARM_DEMO,
    MIDNIGHT_BURGER_DEMO,
    STORM_LIGHTHOUSE_DEMO,
    VACANCY_MOTEL_DEMO,
    FROZEN_GREENHOUSE_DEMO,
    STUCK_SUBWAY_DEMO,
    MIDNIGHT_LAUNDROMAT_DEMO,
    COUNTY_FAIR_DEMO,
]


@pytest.mark.parametrize("demo", CLOCK_GUARDED_DEMOS, ids=lambda d: d.name)
async def test_demo_builds_without_a_world_clock(demo, monkeypatch):
    """The scene builders guard their time/weather setup with ``if clock:``; prove the false
    arm is safe.

    Each builder does ``world = await instantiate(...)`` and *then* re-takes ``actor._lock`` to
    query the clock. We splice a wrapper around ``instantiate`` that, once the real call has
    returned (and released the lock), takes the lock itself and deletes the world clock. By the
    time the builder re-acquires the lock and queries, the clock is gone, so the guard takes its
    false branch -- and the world must still build with rooms and characters.
    """
    from bunnyland.core.components import WorldClockComponent
    from bunnyland.worldgen import examples

    real_instantiate = examples.instantiate

    async def instantiate_then_drop_clock(actor, *args, **kwargs):
        world = await real_instantiate(actor, *args, **kwargs)
        async with actor._lock:
            for clock in list(
                actor.world.query().with_all([WorldClockComponent]).execute_entities()
            ):
                actor.world.remove(clock.id)
        return world

    monkeypatch.setattr(examples, "instantiate", instantiate_then_drop_clock)

    actor = WorldActor()
    world = await demo.generate(actor, demo.name, GenOptions())

    # The guard's false arm ran: the world built fine and still has no clock to set the time on.
    assert world.rooms
    assert world.characters
    assert not _has(actor, WorldClockComponent)
