"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.core.ecs import replace_component
from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


async def lifesim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import IdentityComponent
    from bunnyland.simpacks.lifesim.mechanics import (
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
            RoomSpec(
                key="cottage",
                title="Clover Cottage",
                biome="meadow",
                indoor=True,
                light=0.6,
                celsius=20.0,
            ),
            RoomSpec(key="yard", title="Front Yard", biome="meadow", light=0.9, celsius=18.0),
        ],
        exits=[
            ExitSpec(from_key="cottage", direction="out", to_key="yard"),
            ExitSpec(from_key="yard", direction="in", to_key="cottage"),
        ],
        objects=[
            ObjectSpec(
                key="stew",
                room_key="cottage",
                name="a pot of clover stew",
                kind="food",
                nutrition=6.0,
                satiety=30.0,
                portable=False,
            ),
            ObjectSpec(
                key="well",
                room_key="yard",
                name="a stone well",
                kind="water",
                portable=False,
                hydration=30.0,
            ),
        ],
        characters=[
            CharacterSpec(
                key="juniper",
                name="Juniper",
                room_key="cottage",
                controller="suspended",
                traits=("warm", "ambitious"),
            ),
            CharacterSpec(
                key="hazel",
                name="Hazel",
                room_key="cottage",
                controller="llm",
                llm_profile="partner",
                traits=("playful",),
                goals=("grow the household",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        juniper, hazel = world.characters["juniper"], world.characters["hazel"]
        _augment(
            actor,
            juniper,
            CareerComponent(title="gardener", level=2, hourly_pay=14),
            SkillSetComponent(levels={"gardening": 3, "cooking": 1}),
            AspirationComponent(
                name="Master Gardener", milestones=("ten harvests", "a prize bloom")
            ),
            HouseholdFundsComponent(balance=140),
            CharacterProfileComponent(
                traits=("warm", "ambitious"),
                interests=("gardening", "cooking"),
                preferred_routine="morning garden care",
            ),
        )
        _augment(
            actor,
            hazel,
            CareerComponent(title="baker", level=1, hourly_pay=11),
            SkillSetComponent(levels={"baking": 2}),
            AspirationComponent(name="Village Baker", milestones=("open a stall",)),
        )
        whim = _add(
            actor,
            world.rooms["cottage"],
            [
                IdentityComponent(name="Juniper's garden whim", kind="whim"),
                WhimComponent(want="water the cottage herbs", reward_xp=4.0),
            ],
        )
        actor.world.get_entity(juniper).add_relationship(HasWhim(), whim.id)
        _add(
            actor,
            world.rooms["cottage"],
            [
                IdentityComponent(name="a cozy reading chair", kind="home-object"),
                HomeObjectComponent(
                    affordance="comfort",
                    cleanliness=0.85,
                    condition=0.9,
                    decor_score=1.5,
                ),
            ],
        )
        # A married couple: partner edges both ways plus a shared relationship status.
        actor.world.get_entity(juniper).add_relationship(PartnerOf(since_epoch=0), hazel)
        actor.world.get_entity(hazel).add_relationship(PartnerOf(since_epoch=0), juniper)
        actor.world.get_entity(juniper).add_relationship(
            RelationshipStatus(status="married", since_epoch=0), hazel
        )
    return world


async def midnight_burger_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """An inner-city burger shack whose back cellar is only dangerous after dark."""

    del options
    from bunnyland.core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from bunnyland.foundation.environment.mechanics import CalendarComponent, TimeOfDayComponent
    from bunnyland.simpacks.daggersim.mechanics import (
        FeedingNeedComponent,
        SecretDoorComponent,
        SupernaturalAfflictionComponent,
    )
    from bunnyland.simpacks.dragonsim.mechanics import DiscoveryComponent, PointOfInterestComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="lot", title="Neon Corner Lot", biome="city-street", light=0.1, celsius=14.0
            ),
            RoomSpec(
                key="counter",
                title="Patty Stack Counter",
                biome="diner",
                indoor=True,
                light=0.55,
                celsius=24.0,
            ),
            RoomSpec(
                key="kitchen",
                title="Greasy Back Kitchen",
                biome="diner",
                indoor=True,
                light=0.4,
                celsius=29.0,
            ),
            RoomSpec(
                key="cellar",
                title="Cold-Iron Cellar",
                biome="cellar",
                indoor=True,
                light=0.05,
                celsius=4.0,
            ),
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
            ObjectSpec(
                key="smash_burgers",
                room_key="counter",
                name="a tray of double smash burgers",
                kind="food",
                nutrition=6.0,
                satiety=24.0,
                portable=True,
            ),
            ObjectSpec(
                key="fries",
                room_key="counter",
                name="a paper boat of salted fries",
                kind="food",
                nutrition=3.0,
                satiety=10.0,
                portable=True,
            ),
            ObjectSpec(
                key="soda",
                room_key="counter",
                name="a sweating fountain soda",
                kind="water",
                hydration=14.0,
                portable=True,
            ),
            ObjectSpec(
                key="menu",
                room_key="counter",
                name="a grease-spotted menu board",
                kind="paper",
                writable=False,
                portable=False,
            ),
            ObjectSpec(
                key="freezer",
                room_key="kitchen",
                name="a padlocked chest freezer",
                kind="container",
                portable=False,
                open=False,
            ),
        ],
        characters=[
            CharacterSpec(
                key="regular",
                name="Tessa Lane",
                room_key="counter",
                controller="suspended",
                traits=("hungry", "cheerful", "oblivious"),
                goals=("get a late-night burger", "head home before close"),
            ),
            CharacterSpec(
                key="cook",
                name="Mort Greaves",
                room_key="kitchen",
                species="nightfolk",
                controller="llm",
                llm_profile="night-cook",
                traits=("genial", "ravenous", "secretive"),
                goals=("keep the grill hot", "keep guests out of the cellar after dark"),
            ),
            CharacterSpec(
                key="manager",
                name="Owen Park",
                room_key="counter",
                controller="llm",
                llm_profile="closing-manager",
                traits=("tired", "decent"),
                goals=("hurry the last order", "warn Tessa without naming the danger"),
            ),
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
        _augment(
            actor,
            cellar,
            PointOfInterestComponent(location_type="meat cellar", region="Sixth Ward"),
            DiscoveryComponent(),
        )
        _augment(
            actor,
            world.characters["cook"],
            SupernaturalAfflictionComponent(
                affliction_type="nocturnal hunger", contracted_at_epoch=0, stage="mastered"
            ),
            FeedingNeedComponent(current=8.0, maximum=10.0),
        )
        _add(
            actor,
            kitchen,
            [
                IdentityComponent(
                    name="a steel walk-in door held shut by a meat hook", kind="secret-door"
                ),
                SecretDoorComponent(
                    target_room_id=str(cellar),
                    direction="behind the walk-in",
                    hint="The walk-in only latches from the cellar side.",
                ),
            ],
        )
        _add(
            actor,
            cellar,
            [
                IdentityComponent(name="a stained butcher's ledger", kind="paper"),
                PortableComponent(can_pick_up=True),
                ReadableComponent(
                    title="Butcher's Ledger",
                    text="Day shift buys beef. Night shift never does, and the "
                    "regulars who stay past close never sign out.",
                ),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["menu"]),
            ReadableComponent(
                title="Menu Board",
                text="ALL DAY: double smash, fries, soda. AFTER MIDNIGHT: ask "
                "Mort for the off-menu special. Staff only past the counter "
                "once the sign goes dark.",
            ),
        )
    return world


async def vacancy_motel_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A roadside motel where Room 6 only opens after dark, and the clerk gets hungry."""

    del options
    from bunnyland.core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from bunnyland.foundation.environment.mechanics import CalendarComponent, TimeOfDayComponent
    from bunnyland.simpacks.daggersim.mechanics import (
        FeedingNeedComponent,
        SecretDoorComponent,
        SupernaturalAfflictionComponent,
    )
    from bunnyland.simpacks.dragonsim.mechanics import DiscoveryComponent, PointOfInterestComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="lot",
                title="Gravel Lot Under the Vacancy Sign",
                biome="roadside",
                light=0.2,
                celsius=15.0,
            ),
            RoomSpec(
                key="office",
                title="Wood-Paneled Front Office",
                biome="motel",
                indoor=True,
                light=0.5,
                celsius=22.0,
            ),
            RoomSpec(
                key="corridor",
                title="Carpeted Motel Corridor",
                biome="motel",
                indoor=True,
                light=0.35,
                celsius=20.0,
            ),
            RoomSpec(
                key="room6", title="Room 6", biome="motel", indoor=True, light=0.05, celsius=12.0
            ),
        ],
        exits=[
            ExitSpec(from_key="lot", direction="in", to_key="office"),
            ExitSpec(from_key="office", direction="out", to_key="lot"),
            ExitSpec(from_key="office", direction="inside", to_key="corridor"),
            ExitSpec(from_key="corridor", direction="lobby", to_key="office"),
            ExitSpec(from_key="room6", direction="out", to_key="corridor"),
        ],
        objects=[
            ObjectSpec(
                key="vending",
                room_key="corridor",
                name="a humming vending machine",
                kind="food",
                nutrition=3.0,
                satiety=9.0,
                portable=False,
            ),
            ObjectSpec(
                key="ice",
                room_key="corridor",
                name="a cloudy ice machine",
                kind="water",
                hydration=12.0,
                portable=False,
            ),
            ObjectSpec(
                key="register",
                room_key="office",
                name="the guest register",
                kind="paper",
                writable=True,
                portable=False,
            ),
            ObjectSpec(
                key="key6",
                room_key="office",
                name="a brass key on a Room 6 fob",
                kind="item",
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="guest",
                name="Nadia Frost",
                room_key="office",
                controller="suspended",
                traits=("road-weary", "skeptical", "tired"),
                goals=("sleep off the drive", "check out by morning"),
            ),
            CharacterSpec(
                key="clerk",
                name="Vernon Pike",
                room_key="office",
                species="nightfolk",
                controller="llm",
                llm_profile="night-clerk",
                traits=("courteous", "unblinking", "hungry-after-dark"),
                goals=("keep guests in their rooms after midnight", "never rent out Room 6"),
            ),
            CharacterSpec(
                key="maid",
                name="Lupe Ramos",
                room_key="corridor",
                controller="llm",
                llm_profile="frightened-housekeeper",
                traits=("kind", "frightened"),
                goals=("warn Nadia off Room 6 without naming what is in it",),
            ),
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
        _augment(
            actor,
            room6,
            PointOfInterestComponent(location_type="sealed room", region="Route 9"),
            DiscoveryComponent(),
        )
        _augment(
            actor,
            world.characters["clerk"],
            SupernaturalAfflictionComponent(
                affliction_type="after-dark hunger", contracted_at_epoch=0, stage="mastered"
            ),
            FeedingNeedComponent(current=7.0, maximum=10.0),
        )
        _add(
            actor,
            corridor,
            [
                IdentityComponent(
                    name="a door numbered 6 that is not on the daytime map", kind="secret-door"
                ),
                SecretDoorComponent(
                    target_room_id=str(room6),
                    direction="end of the corridor",
                    hint="The corridor has five doors by day and six after dark.",
                ),
            ],
        )
        _add(
            actor,
            room6,
            [
                IdentityComponent(name="a warped drawer hymnal", kind="paper"),
                PortableComponent(can_pick_up=True),
                ReadableComponent(
                    title="Drawer Hymnal",
                    text="Margins full of names and dates in different hands, each one "
                    "checked in after midnight and never checked out.",
                ),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["register"]),
            ReadableComponent(
                title="Guest Register",
                text="House rule, underlined twice: do not assign Room 6, and do "
                "not let a guest wander the corridor after midnight.",
            ),
        )
    return world


async def midnight_laundromat_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A 24-hour laundromat in the small hours: strangers, a broken dryer, a lost-and-found."""

    del options
    from bunnyland.core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from bunnyland.foundation.environment.mechanics import CalendarComponent, TimeOfDayComponent
    from bunnyland.simpacks.dragonsim.mechanics import DiscoveryComponent, PointOfInterestComponent
    from bunnyland.simpacks.lifesim.mechanics import WhimComponent

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="sidewalk",
                title="Buzzing Sidewalk",
                biome="city-street",
                light=0.1,
                celsius=13.0,
            ),
            RoomSpec(
                key="floor",
                title="All-Night Laundromat",
                biome="laundromat",
                indoor=True,
                light=0.6,
                celsius=26.0,
            ),
            RoomSpec(
                key="back",
                title="Back Folding Room",
                biome="laundromat",
                indoor=True,
                light=0.4,
                celsius=24.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="sidewalk", direction="in", to_key="floor"),
            ExitSpec(from_key="floor", direction="out", to_key="sidewalk"),
            ExitSpec(from_key="floor", direction="back", to_key="back"),
            ExitSpec(from_key="back", direction="front", to_key="floor"),
        ],
        objects=[
            ObjectSpec(
                key="coffee",
                room_key="floor",
                name="a paper cup of machine coffee",
                kind="water",
                hydration=10.0,
                portable=True,
            ),
            ObjectSpec(
                key="crackers",
                room_key="floor",
                name="a sleeve of vending crackers",
                kind="food",
                nutrition=3.0,
                satiety=9.0,
                portable=True,
            ),
            ObjectSpec(
                key="dryer",
                room_key="floor",
                name="an out-of-order dryer",
                kind="item",
                portable=False,
            ),
            ObjectSpec(
                key="lostbin",
                room_key="back",
                name="the lost-and-found bin",
                kind="container",
                portable=False,
                open=False,
            ),
            ObjectSpec(
                key="mitten",
                room_key="back",
                name="a child's red mitten, unclaimed",
                kind="item",
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="patron",
                name="Marisol Vega",
                room_key="floor",
                controller="suspended",
                traits=("sleepless", "friendly", "curious"),
                goals=("finish the wash in peace", "figure out the back room"),
            ),
            CharacterSpec(
                key="attendant",
                name="Sam Okafor",
                room_key="back",
                controller="llm",
                llm_profile="night-attendant",
                traits=("quiet", "watchful", "kind"),
                goals=("keep the machines running", "mind the lost-and-found"),
            ),
            CharacterSpec(
                key="regular",
                name="Dot Pell",
                room_key="floor",
                controller="llm",
                llm_profile="lonely-regular",
                traits=("chatty", "lonely"),
                goals=("talk to someone", "put off going home"),
            ),
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
        _augment(
            actor,
            world.characters["patron"],
            WhimComponent(want="get one full load done before dawn"),
        )
        _augment(
            actor,
            world.characters["regular"],
            WhimComponent(want="not be alone at two in the morning"),
        )
        # The lost-and-found is the quiet mystery: things no one remembers leaving.
        _augment(
            actor,
            back,
            PointOfInterestComponent(location_type="lost and found", region="Eighth Street"),
            DiscoveryComponent(),
        )
        _add(
            actor,
            back,
            [
                IdentityComponent(name="a lost-and-found ledger", kind="paper"),
                PortableComponent(can_pick_up=True),
                ReadableComponent(
                    title="Lost and Found Ledger",
                    text="Half the entries are in the attendant's hand, half in none "
                    "he recognizes, logging coats and keys nobody came back for.",
                ),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["dryer"]),
            ReadableComponent(
                title="Taped-On Sign",
                text="OUT OF ORDER. It still rumbles and turns some nights. Do not "
                "use it; do not open it while it does.",
            ),
        )
    return world


LIFESIM_DEMO = WorldGenerator(
    name="lifesim-demo",
    generate=_with_regions(
        lifesim_example, (("Cloverbrook Vale", "region"), ("Clover Hollow", "area"))
    ),
    description="A household with careers, skills, money, relationships, and aspirations.",
    group="simpack sandbox",
    uses_seed=False,
)

MIDNIGHT_BURGER_DEMO = WorldGenerator(
    name="midnight-burger-demo",
    generate=_with_regions(
        midnight_burger_example, (("East Side", "neighborhood"), ("Patty Stack", "building"))
    ),
    description="An inner-city burger shack that opens at dusk and rolls into night, with a "
    "hungry night cook and a hidden cellar that is only dangerous after dark.",
    group="pop culture",
    uses_seed=False,
)

VACANCY_MOTEL_DEMO = WorldGenerator(
    name="vacancy-motel-demo",
    generate=_with_regions(
        vacancy_motel_example, (("Route 9", "region"), ("The Vacancy Motel", "building"))
    ),
    description="A roadside motel that checks in by day and rolls into night, where Room 6 "
    "only opens after dark and the night clerk gets hungry.",
    group="scene demo",
    uses_seed=False,
)

MIDNIGHT_LAUNDROMAT_DEMO = WorldGenerator(
    name="midnight-laundromat-demo",
    generate=_with_regions(
        midnight_laundromat_example, (("Riverside", "neighborhood"), ("Suds & Such", "building"))
    ),
    description="A 24-hour laundromat in the small hours rolling toward dawn, with late-night "
    "strangers, a broken dryer, and a lost-and-found nobody remembers filling.",
    group="scene demo",
    uses_seed=False,
)
