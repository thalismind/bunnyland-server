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

from bunnyland.foundation.meters.mechanics import Meter, with_value
from bunnyland.foundation.needs.mechanics import HungerComponent, ThirstComponent
from bunnyland.foundation.persona.mechanics import GoalComponent
from bunnyland.foundation.tutorial.mechanics import (
    HungryCourierControllerComponent,
    TutorialGuideComponent,
)

from ..core.components import (
    ButtonComponent,
    DescriptionComponent,
    ReadableComponent,
    SuspendedComponent,
    WritableComponent,
)
from ..core.ecs import spawn_entity
from ..llm_agents.scripts import register_script
from ..llm_agents.tools import ToolCall
from .demo_support import _augment, _region_stack, _with_regions
from .generators import GenOptions, WorldGenerator
from .instantiate import InstantiatedWorld, instantiate
from .proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal

# --------------------------------------------------------------------------------------
# life-sim — needs, careers, money, relationships, aspirations
# --------------------------------------------------------------------------------------


async def hungry_courier_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options

    register_script(
        "hungry-courier-intro",
        (
            ToolCall(
                "say",
                {
                    "text": (
                        "Welcome to Apple Crossing. Pip the courier has a letter for Mira, "
                        "but hunger is keeping him here. Apple Hedge is east. Bring back an "
                        "apple and drop it beside Pip, put it in the open courier basket, or "
                        "give it to him. Leave Pip's courier letter on the post table; if you "
                        "pick it up, drop it back here. Then watch Pip take it and follow the "
                        "route."
                    ),
                    "intent": "inform",
                    "approach": "friendly",
                },
            ),
        ),
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="crossing",
                title="Apple Crossing",
                biome="countryside",
                light=0.75,
                celsius=18.0,
                description=(
                    "A quiet countryside crossing with a signpost, a bench, and a post "
                    "table where Pip waits beside his sealed courier letter. Leave that "
                    "letter on the table for Pip to take after he eats."
                ),
            ),
            RoomSpec(
                key="post_hut",
                title="Pippa's Post Hut",
                biome="countryside",
                indoor=True,
                light=0.7,
                celsius=20.0,
                description="A tiny rural post office with sorted letters and a route ledger.",
            ),
            RoomSpec(
                key="apple_hedge",
                title="Apple Hedge",
                biome="orchard",
                light=0.9,
                celsius=18.0,
                description="A low hedge with bright apples, a dropped basket, and a watering can.",
            ),
            RoomSpec(
                key="footbridge",
                title="Old Footbridge",
                biome="creek",
                light=0.8,
                celsius=17.0,
                description="A short wooden bridge over a clear creek, halfway to Mira's lane.",
            ),
            RoomSpec(
                key="cottage_lane",
                title="Mira's Cottage Lane",
                biome="countryside",
                light=0.75,
                celsius=18.0,
                description="A quiet lane with a gate, a mailbox, and a cottage window.",
            ),
            RoomSpec(
                key="cottage",
                title="Mira's Cottage",
                biome="cottage",
                indoor=True,
                light=0.65,
                celsius=20.0,
                description=(
                    "A warm cottage with a kitchen table, reply stationery, and tea kettle."
                ),
            ),
        ],
        exits=[
            ExitSpec(from_key="crossing", direction="north", to_key="post_hut"),
            ExitSpec(from_key="post_hut", direction="south", to_key="crossing"),
            ExitSpec(from_key="crossing", direction="east", to_key="apple_hedge"),
            ExitSpec(from_key="apple_hedge", direction="west", to_key="crossing"),
            ExitSpec(from_key="crossing", direction="south", to_key="footbridge"),
            ExitSpec(from_key="footbridge", direction="north", to_key="crossing"),
            ExitSpec(from_key="footbridge", direction="west", to_key="cottage_lane"),
            ExitSpec(from_key="cottage_lane", direction="east", to_key="footbridge"),
            ExitSpec(from_key="cottage_lane", direction="in", to_key="cottage"),
            ExitSpec(from_key="cottage", direction="out", to_key="cottage_lane"),
        ],
        objects=[
            ObjectSpec(
                key="letter",
                room_key="crossing",
                name="courier letter",
                kind="paper",
                writable=True,
                portable=True,
            ),
            ObjectSpec(
                key="apple",
                room_key="apple_hedge",
                name="red crossing apple",
                kind="food",
                nutrition=4.0,
                satiety=55.0,
                portable=True,
            ),
            ObjectSpec(
                key="ledger",
                room_key="cottage",
                name="delivery ledger",
                kind="paper",
                writable=True,
                portable=False,
            ),
            ObjectSpec(
                key="notice_board",
                room_key="crossing",
                name="Apple Crossing notice board",
                kind="paper",
                portable=False,
            ),
            ObjectSpec(
                key="courier_basket",
                room_key="crossing",
                name="open courier basket",
                kind="container",
                portable=False,
                open=True,
                description="A fixed open basket where food remains within Pip's reach.",
            ),
            ObjectSpec(
                key="mailbox",
                room_key="cottage_lane",
                name="Mira's mailbox",
                kind="container",
                portable=False,
            ),
        ],
        characters=[
            CharacterSpec(
                key="player",
                name="Juniper",
                room_key="crossing",
                controller="suspended",
                traits=("curious", "helpful"),
                goals=("Help Pip the hungry courier deliver the letter.",),
            ),
            CharacterSpec(
                key="postmaster",
                name="Pippa Bramble",
                room_key="crossing",
                controller="scripted",
                script_name="hungry-courier-intro",
                traits=("brisk", "kind", "practical"),
            ),
            CharacterSpec(
                key="courier",
                name="Pip Thistle",
                room_key="crossing",
                controller="suspended",
                traits=("earnest", "hungry", "reliable"),
                goals=("Deliver the courier letter to Mira's Cottage after eating real food.",),
            ),
            CharacterSpec(
                key="recipient",
                name="Mira Vale",
                room_key="cottage",
                controller="suspended",
                traits=("patient", "observant"),
            ),
            CharacterSpec(
                key="caretaker",
                name="Rowan Reed",
                room_key="apple_hedge",
                controller="suspended",
                traits=("dry", "protective"),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        player = actor.world.get_entity(world.characters["player"])
        _augment(
            actor,
            player.id,
            GoalComponent(
                active_goals=(
                    "Help Pip deliver his courier letter without taking it away from him. "
                    "Find food at Apple Hedge, bring or leave it where Pip can reach it, "
                    "leave or drop the letter in Apple Crossing for Pip, then watch Pip act.",
                )
            ),
        )
        letter = actor.world.get_entity(world.objects["letter"])
        _augment(
            actor,
            letter.id,
            DescriptionComponent(
                short="A sealed first-run demo letter addressed to Mira's Cottage."
            ),
            ReadableComponent(text="Please deliver this to Mira's Cottage."),
        )
        ledger = actor.world.get_entity(world.objects["ledger"])
        _augment(
            actor,
            ledger.id,
            DescriptionComponent(short="A public ledger that records completed deliveries."),
            ReadableComponent(text="Delivery ledger entries:"),
            WritableComponent(remaining_space=1000),
        )
        _augment(
            actor,
            world.objects["notice_board"],
            ReadableComponent(
                title="Apple Crossing Courier Notice",
                text=(
                    "Hungry Courier route: Apple Hedge is east. Bring a red crossing apple "
                    "west to Apple Crossing and make it reachable to Pip by dropping it beside "
                    "him, putting it in the open courier basket, or giving it to him. Leave "
                    "Pip's courier letter on the post table; if you picked it up, drop it back "
                    "in Apple Crossing. Once fed, Pip takes the letter south to Old Footbridge, "
                    "west to Mira's Cottage Lane, then in to Mira's Cottage. The delivery "
                    "ledger there records confirmation."
                ),
            ),
        )
        _augment(
            actor,
            world.characters["postmaster"],
            TutorialGuideComponent(
                help_text=(
                    "Apple Hedge is east. Bring its red crossing apple west, then drop it beside "
                    "Pip, put it in the open courier basket, or give it to Pip. Leave his courier "
                    "letter on the post table, or drop it back in Apple Crossing if you picked "
                    "it up. He will take the letter south to Old Footbridge, west to Mira's "
                    "Cottage Lane, and in to Mira's Cottage; the delivery ledger confirms "
                    "completion."
                )
            ),
        )
        courier = actor.world.get_entity(world.characters["courier"])
        _augment(
            actor,
            courier.id,
            HungerComponent(meter=with_value(Meter(), 80.0), metabolism=0.0),
            GoalComponent(
                active_goals=("Deliver the courier letter, but eat real food first if hungry.",)
            ),
        )
        courier.remove_component(SuspendedComponent)
        controller = spawn_entity(
            actor.world,
            [
                HungryCourierControllerComponent(
                    destination_title="Mira's Cottage",
                    route=(
                        ("Apple Crossing", "south"),
                        ("Old Footbridge", "west"),
                        ("Mira's Cottage Lane", "in"),
                    ),
                )
            ],
        )
        actor.assign_controller(courier.id, controller.id)

    return world


async def bell_green_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options

    register_script(
        "bell-green-guide-intro",
        (
            ToolCall(
                "say",
                {
                    "text": (
                        "Welcome to Bell Green. The notice board has a town map and errands. "
                        "From here Bell Green Post Office is north, Garden Walk east, and "
                        "Hearthwick Inn south. Ask me if you get lost."
                    ),
                    "intent": "inform",
                    "approach": "friendly",
                },
            ),
        ),
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="green",
                title="Bell Green",
                biome="town",
                light=0.8,
                celsius=18.0,
                description=(
                    "The town hub gathers a fixed central notice board, a fixed community "
                    "mailbox, and four clear roads beneath the bell. The Old Bell Shrine route "
                    "is east to Garden Walk, south to River Footbridge, then east."
                ),
            ),
            RoomSpec(
                key="post_office",
                title="Bell Green Post Office",
                biome="town",
                indoor=True,
                light=0.7,
                celsius=20.0,
                description=(
                    "Pippa's fixed sorted-letter stacks and counter make this the town mail "
                    "stop; they can be inspected but not carried."
                ),
            ),
            RoomSpec(
                key="garden_walk",
                title="Garden Walk",
                biome="garden",
                light=0.9,
                description=(
                    "Herb beds and a portable harvest basket line the east walk; the river "
                    "footbridge continues south toward the shrine. A fixed shrine sign says "
                    "south to River Footbridge, then east to Old Bell Shrine."
                ),
            ),
            RoomSpec(
                key="garden_shed",
                title="Saffron's Garden Shed",
                biome="garden",
                indoor=True,
                light=0.55,
                description="A compact shed of seed packets beside Garden Walk.",
            ),
            RoomSpec(
                key="market_lane",
                title="Market Lane",
                biome="town",
                light=0.8,
                description="The west lane connects the general store and Jun's workshop.",
            ),
            RoomSpec(
                key="store",
                title="Nettle's General Store",
                biome="town",
                indoor=True,
                light=0.7,
                description="Nettle keeps everyday food and supplies on orderly shelves.",
            ),
            RoomSpec(
                key="workshop",
                title="Jun's Workshop",
                biome="workshop",
                indoor=True,
                light=0.65,
                description="A busy workbench marks Jun's repair shop south of Market Lane.",
            ),
            RoomSpec(
                key="inn",
                title="Hearthwick Inn",
                biome="inn",
                indoor=True,
                light=0.75,
                description=(
                    "A warm public inn directly south of Bell Green, with a stew pot and "
                    "residents near the hearth."
                ),
            ),
            RoomSpec(
                key="footbridge",
                title="River Footbridge",
                biome="river",
                light=0.75,
                description=(
                    "River Footbridge runs south from Garden Walk. A fixed shrine sign points "
                    "east to Old Bell Shrine and north to Garden Walk."
                ),
            ),
            RoomSpec(
                key="pet_yard",
                title="Pet Yard",
                biome="yard",
                light=0.85,
                description="Button's feed bowl sits just east of Hearthwick Inn.",
            ),
            RoomSpec(
                key="bell_shrine",
                title="Old Bell Shrine",
                biome="shrine",
                light=0.55,
                description="A weathered bell rests at the quiet end of the footbridge path.",
            ),
            RoomSpec(
                key="courier_path",
                title="Courier Path",
                biome="road",
                light=0.75,
                description="A route milestone points north back to the river footbridge.",
            ),
        ],
        exits=[
            ExitSpec(from_key="green", direction="north", to_key="post_office"),
            ExitSpec(from_key="post_office", direction="south", to_key="green"),
            ExitSpec(from_key="green", direction="east", to_key="garden_walk"),
            ExitSpec(from_key="garden_walk", direction="west", to_key="green"),
            ExitSpec(from_key="garden_walk", direction="in", to_key="garden_shed"),
            ExitSpec(from_key="garden_shed", direction="out", to_key="garden_walk"),
            ExitSpec(from_key="green", direction="west", to_key="market_lane"),
            ExitSpec(from_key="market_lane", direction="east", to_key="green"),
            ExitSpec(from_key="market_lane", direction="in", to_key="store"),
            ExitSpec(from_key="store", direction="out", to_key="market_lane"),
            ExitSpec(from_key="market_lane", direction="south", to_key="workshop"),
            ExitSpec(from_key="workshop", direction="north", to_key="market_lane"),
            ExitSpec(from_key="green", direction="south", to_key="inn"),
            ExitSpec(from_key="inn", direction="north", to_key="green"),
            ExitSpec(from_key="inn", direction="east", to_key="pet_yard"),
            ExitSpec(from_key="pet_yard", direction="west", to_key="inn"),
            ExitSpec(from_key="garden_walk", direction="south", to_key="footbridge"),
            ExitSpec(from_key="footbridge", direction="north", to_key="garden_walk"),
            ExitSpec(from_key="footbridge", direction="east", to_key="bell_shrine"),
            ExitSpec(from_key="bell_shrine", direction="west", to_key="footbridge"),
            ExitSpec(from_key="footbridge", direction="south", to_key="courier_path"),
            ExitSpec(from_key="courier_path", direction="north", to_key="footbridge"),
        ],
        objects=[
            ObjectSpec(
                key="notice",
                room_key="green",
                name="central notice board",
                kind="paper",
                portable=False,
                description="A fixed public board combining a town map with optional errands.",
            ),
            ObjectSpec(
                key="mailbox",
                room_key="green",
                name="community mailbox",
                kind="container",
                portable=False,
                open=False,
                description=(
                    "A fixed community mail container; open or inspect it to check local mail."
                ),
            ),
            ObjectSpec(key="bell", room_key="green", name="town bell", portable=False),
            ObjectSpec(
                key="letters",
                room_key="post_office",
                name="sorted letters",
                kind="paper",
                portable=False,
                description="Pippa's labeled stacks of incoming and outgoing town mail.",
            ),
            ObjectSpec(key="herbs", room_key="garden_walk", name="herb beds", portable=False),
            ObjectSpec(
                key="garden_shrine_sign",
                room_key="garden_walk",
                name="Garden Walk shrine sign",
                kind="paper",
                portable=False,
                description="A fixed route sign for the Old Bell Shrine.",
            ),
            ObjectSpec(
                key="basket",
                room_key="garden_walk",
                name="harvest basket",
                description="A harmless portable basket suitable for carrying between rooms.",
            ),
            ObjectSpec(key="tools", room_key="garden_shed", name="seed packets", portable=True),
            ObjectSpec(key="crate", room_key="market_lane", name="produce crates", portable=False),
            ObjectSpec(key="food", room_key="store", name="food shelf", kind="food", satiety=18.0),
            ObjectSpec(key="bench", room_key="workshop", name="workbench", portable=False),
            ObjectSpec(key="stew", room_key="inn", name="stew pot", kind="food", satiety=25.0),
            ObjectSpec(key="bowl", room_key="pet_yard", name="feed bowl", portable=False),
            ObjectSpec(
                key="bridge_shrine_sign",
                room_key="footbridge",
                name="River Footbridge shrine sign",
                kind="paper",
                portable=False,
                description="A fixed route sign for the Old Bell Shrine.",
            ),
            ObjectSpec(key="old_bell", room_key="bell_shrine", name="weathered bell"),
            ObjectSpec(key="milestone", room_key="courier_path", name="route milestone"),
        ],
        characters=[
            CharacterSpec(
                key="pippa",
                name="Pippa Bramble",
                room_key="post_office",
                description="Bell Green's practical postmaster, surrounded by sorted letters.",
            ),
            CharacterSpec(key="pip", name="Pip Thistle", room_key="courier_path"),
            CharacterSpec(key="mira", name="Mira Vale", room_key="bell_shrine"),
            CharacterSpec(
                key="saffron",
                name="Saffron Reed",
                room_key="garden_walk",
                description="The town gardener tending herbs beside the harvest basket.",
            ),
            CharacterSpec(key="nettle", name="Nettle Price", room_key="store"),
            CharacterSpec(
                key="jun",
                name="Jun Copper",
                room_key="workshop",
                description="Bell Green's repairer, usually found beside the workbench.",
            ),
            CharacterSpec(key="lark", name="Lark Dandelion", room_key="inn"),
            CharacterSpec(key="bram", name="Bram Hollow", room_key="green"),
            CharacterSpec(key="wick", name="Wick Hearth", room_key="inn"),
            CharacterSpec(key="button", name="Button", room_key="pet_yard", species="pet"),
            CharacterSpec(key="morrow", name="Morrow Grey", room_key="courier_path"),
            CharacterSpec(
                key="guide",
                name="Tansy Bell",
                room_key="green",
                controller="scripted",
                script_name="bell-green-guide-intro",
                description="A patient town guide stationed beside the central notice board.",
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _augment(
            actor,
            world.objects["notice"],
            ReadableComponent(
                title="Bell Green Notice Board",
                text=(
                    "Town map from Bell Green: north to Bell Green Post Office; east to "
                    "Garden Walk; south to Hearthwick Inn; west to Market Lane. For the Old "
                    "Bell Shrine, go east to Garden Walk, south to River Footbridge, then "
                    "east. Starter errands: help Pip finish a delivery, inspect the mail, "
                    "carry Saffron's harvest basket, ask Jun what broke, or feed Button."
                ),
            ),
        )
        _augment(
            actor,
            world.characters["guide"],
            TutorialGuideComponent(
                help_text=(
                    "From Bell Green: the north exit reaches Bell Green Post Office, the east "
                    "exit reaches Garden Walk, and the south exit reaches Hearthwick Inn. For "
                    "Old Bell Shrine, take the east exit to Garden Walk, the south exit to "
                    "River Footbridge, then the east exit to Old Bell Shrine."
                )
            ),
        )
        _augment(
            actor,
            world.objects["garden_shrine_sign"],
            ReadableComponent(
                title="Garden Walk Shrine Sign",
                text=(
                    "Old Bell Shrine: take the south exit to River Footbridge, then the east "
                    "exit to Old Bell Shrine."
                ),
            ),
        )
        _augment(
            actor,
            world.objects["bridge_shrine_sign"],
            ReadableComponent(
                title="River Footbridge Shrine Sign",
                text=(
                    "Old Bell Shrine: take the east exit. Garden Walk: take the north exit."
                ),
            ),
        )
        _region_stack(
            actor,
            world.rooms.values(),
            (("Bell Valley", "region"), ("Bell Green", "town")),
        )
    return world


async def clover_city_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    register_script(
        "clover-city-guide-intro",
        (
            ToolCall(
                "say",
                {
                    "text": (
                        "Welcome to Clover City. Inspect the directory for facility routes and "
                        "the daily bulletin for today's activity. Ask me for the exact shared-"
                        "facility routes whenever you need them."
                    ),
                    "intent": "inform",
                    "approach": "friendly",
                },
            ),
        ),
    )
    register_script(
        "clover-street-route",
        (
            ToolCall("move", {"direction": "east"}),
            ToolCall(
                "say",
                {
                    "text": (
                        "Rook route report — Corner Store: supplies checked; returning west "
                        "to Street Stop."
                    ),
                    "intent": "inform",
                    "approach": "plain",
                },
            ),
            ToolCall("move", {"direction": "west"}),
            ToolCall(
                "say",
                {
                    "text": (
                        "Rook route report — Street Stop: timetable checked; the next stop is "
                        "east at Corner Store."
                    ),
                    "intent": "inform",
                    "approach": "plain",
                },
            ),
        ),
    )
    from bunnyland.core.components import IdentityComponent, PortableComponent
    from bunnyland.core.edges import ContainmentMode, Contains
    from bunnyland.foundation.consumables.components import (
        ConsumableComponent,
        DrinkableComponent,
    )
    from bunnyland.foundation.social.mechanics import SocialBond, create_obligation
    from bunnyland.foundation.storyteller.mechanics import IncidentComponent, IncidentSpawned
    from bunnyland.simpacks.gardensim.mechanics import (
        MachineBreakdownComponent,
        MachineComponent,
    )
    from bunnyland.simpacks.lifesim.mechanics import CareerComponent, HasRoutine, RoutineComponent

    room_specs = [
        ("lobby", "Clover City Lobby", "building", True),
        ("mailroom", "Mailroom", "building", True),
        ("elevator", "Elevator", "building", True),
        ("stairwell", "Stairwell", "building", True),
        ("laundry", "Laundry Room", "building", True),
        ("courtyard", "Courtyard", "city", False),
        ("roof", "Rooftop Garden", "city", False),
        ("kitchen", "Community Kitchen", "building", True),
        ("workshop", "Basement Workshop", "building", True),
        ("store", "Corner Store", "city", True),
        ("clinic", "Clinic Room", "building", True),
        ("music", "Music Room", "building", True),
        ("security", "Security Office", "building", True),
        ("apt_mira", "Apartment 2A: Mira's Studio", "building", True),
        ("apt_jun", "Apartment 2B: Jun's Unit", "building", True),
        ("apt_lark", "Apartment 3A: Lark's Room", "building", True),
        ("apt_saffron", "Apartment 3B: Saffron's Room", "building", True),
        ("apt_nettle", "Apartment 4A: Nettle's Room", "building", True),
        ("empty_unit", "Apartment 4B: Empty Unit", "building", True),
        ("street", "Street Stop", "city", False),
    ]
    room_descriptions = {
        "lobby": (
            "The building's navigation hub holds a fixed directory and daily bulletin; "
            "eight labeled exits lead to shared facilities and the street."
        ),
        "mailroom": "Parcel lockers and Pip's mail station sit directly east of the lobby.",
        "elevator": "The north lift serves the apartment floors through numbered exits.",
        "stairwell": (
            "The west stairs hold a fixed directory: up to Rooftop Garden, down to Basement "
            "Workshop, and east to Clover City Lobby."
        ),
        "laundry": "A shared laundry west of the courtyard, with Tavi and a lost-sock basket.",
        "courtyard": (
            "The central outdoor court holds a fixed directory: east to Community Kitchen, "
            "west to Laundry Room, and north to Clover City Lobby."
        ),
        "roof": "A shared rooftop garden and rationed rain barrel sit above the stairwell.",
        "kitchen": "The community kitchen east of the courtyard holds a limited pantry.",
        "workshop": "Jun's basement workshop stores elevator parts below the stairwell.",
        "store": "The corner store stands east of Street Stop with food and emergency water.",
        "clinic": "Kestrel's clinic is northeast of the lobby.",
        "music": "The northwest music room contains an old piano and a noise complaint.",
        "security": "The southeast security office holds the city's readable incident log.",
        "apt_mira": "Mira's private studio opens from the elevator's 2A stop.",
        "apt_jun": "Jun's private unit opens from the elevator's 2B stop.",
        "apt_lark": "Lark's private room opens from the elevator's 3A stop.",
        "apt_saffron": "Saffron's private room opens from the elevator's 3B stop.",
        "apt_nettle": "Nettle's private room opens from the elevator's 4A stop.",
        "empty_unit": "An unoccupied fourth-floor unit opens from the elevator's 4B stop.",
        "street": (
            "The public street outside Clover City Lobby connects east to Corner Store. A "
            "fixed timetable posts Rook's repeating Street Stop–Corner Store route."
        ),
    }
    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key=key,
                title=title,
                biome=biome,
                indoor=indoor,
                light=0.65,
                description=room_descriptions[key],
            )
            for key, title, biome, indoor in room_specs
        ],
        exits=[
            ExitSpec(from_key="street", direction="in", to_key="lobby"),
            ExitSpec(from_key="lobby", direction="out", to_key="street"),
            ExitSpec(from_key="lobby", direction="east", to_key="mailroom"),
            ExitSpec(from_key="mailroom", direction="west", to_key="lobby"),
            ExitSpec(from_key="lobby", direction="north", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="south", to_key="lobby"),
            ExitSpec(from_key="lobby", direction="west", to_key="stairwell"),
            ExitSpec(from_key="stairwell", direction="east", to_key="lobby"),
            ExitSpec(from_key="lobby", direction="south", to_key="courtyard"),
            ExitSpec(from_key="courtyard", direction="north", to_key="lobby"),
            ExitSpec(from_key="stairwell", direction="up", to_key="roof"),
            ExitSpec(from_key="roof", direction="down", to_key="stairwell"),
            ExitSpec(from_key="stairwell", direction="down", to_key="workshop"),
            ExitSpec(from_key="workshop", direction="up", to_key="stairwell"),
            ExitSpec(from_key="courtyard", direction="east", to_key="kitchen"),
            ExitSpec(from_key="kitchen", direction="west", to_key="courtyard"),
            ExitSpec(from_key="courtyard", direction="west", to_key="laundry"),
            ExitSpec(from_key="laundry", direction="east", to_key="courtyard"),
            ExitSpec(from_key="street", direction="east", to_key="store"),
            ExitSpec(from_key="store", direction="west", to_key="street"),
            ExitSpec(from_key="lobby", direction="northeast", to_key="clinic"),
            ExitSpec(from_key="clinic", direction="southwest", to_key="lobby"),
            ExitSpec(from_key="lobby", direction="northwest", to_key="music"),
            ExitSpec(from_key="music", direction="southeast", to_key="lobby"),
            ExitSpec(from_key="lobby", direction="southeast", to_key="security"),
            ExitSpec(from_key="security", direction="northwest", to_key="lobby"),
            ExitSpec(from_key="elevator", direction="2a", to_key="apt_mira"),
            ExitSpec(from_key="apt_mira", direction="hall", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="2b", to_key="apt_jun"),
            ExitSpec(from_key="apt_jun", direction="hall", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="3a", to_key="apt_lark"),
            ExitSpec(from_key="apt_lark", direction="hall", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="3b", to_key="apt_saffron"),
            ExitSpec(from_key="apt_saffron", direction="hall", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="4a", to_key="apt_nettle"),
            ExitSpec(from_key="apt_nettle", direction="hall", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="4b", to_key="empty_unit"),
            ExitSpec(from_key="empty_unit", direction="hall", to_key="elevator"),
        ],
        objects=[
            ObjectSpec(
                key="directory",
                room_key="lobby",
                name="directory board",
                kind="paper",
                portable=False,
                description="A fixed route map for Clover City's shared facilities.",
            ),
            ObjectSpec(
                key="bulletin",
                room_key="lobby",
                name="daily bulletin",
                kind="paper",
                portable=False,
                description="A fixed public bulletin for current city tensions and activity.",
            ),
            ObjectSpec(
                key="parcels",
                room_key="mailroom",
                name="parcel locker",
                kind="container",
                portable=False,
                open=False,
                description=(
                    "A fixed closed bank of numbered delivery lockers; open or inspect it for "
                    "missing-parcel checks."
                ),
            ),
            ObjectSpec(key="panel", room_key="elevator", name="button panel", portable=False),
            ObjectSpec(key="key", room_key="stairwell", name="dropped key", kind="key"),
            ObjectSpec(
                key="stairwell_directory",
                room_key="stairwell",
                name="Stairwell directory",
                kind="paper",
                portable=False,
                description="A fixed directory for the stairwell branches.",
            ),
            ObjectSpec(key="sock", room_key="laundry", name="lost sock basket", portable=False),
            ObjectSpec(key="planters", room_key="courtyard", name="planter boxes"),
            ObjectSpec(
                key="courtyard_directory",
                room_key="courtyard",
                name="Courtyard directory",
                kind="paper",
                portable=False,
                description="A fixed directory for the courtyard branches.",
            ),
            ObjectSpec(
                key="rain",
                room_key="roof",
                name="rain barrel",
                kind="water",
                portable=False,
                renewable=False,
            ),
            ObjectSpec(
                key="pantry",
                room_key="kitchen",
                name="community pantry",
                kind="food",
                portable=False,
            ),
            ObjectSpec(key="parts", room_key="workshop", name="spare parts"),
            ObjectSpec(
                key="repair_kit",
                room_key="workshop",
                name="elevator repair kit",
                kind="repair_tool",
            ),
            ObjectSpec(
                key="water_jug",
                room_key="store",
                name="emergency water jug",
                kind="water",
                hydration=15.0,
                renewable=False,
            ),
            ObjectSpec(
                key="snacks",
                room_key="store",
                name="snack shelf",
                kind="food",
                portable=False,
            ),
            ObjectSpec(
                key="street_timetable",
                room_key="street",
                name="Street Stop timetable",
                kind="paper",
                portable=False,
                description="A fixed public timetable for Rook's recurring route.",
            ),
            ObjectSpec(key="clipboard", room_key="clinic", name="appointment clipboard"),
            ObjectSpec(key="piano", room_key="music", name="old piano", portable=False),
            ObjectSpec(
                key="log",
                room_key="security",
                name="incident log",
                kind="paper",
                portable=False,
                description="Security's fixed record of open and resolved city incidents.",
            ),
        ],
        characters=[
            CharacterSpec(key="ada", name="Ada Warden", room_key="lobby"),
            CharacterSpec(
                key="pip",
                name="Pip Thistle",
                room_key="mailroom",
                description="The resident courier watching the parcel lockers.",
            ),
            CharacterSpec(key="mira", name="Mira Vale", room_key="apt_mira"),
            CharacterSpec(
                key="jun",
                name="Jun Copper",
                room_key="workshop",
                description="The building repairer inspecting elevator parts in the basement.",
            ),
            CharacterSpec(
                key="saffron",
                name="Saffron Reed",
                room_key="roof",
                description="The rooftop gardener managing the rationed rain barrel.",
            ),
            CharacterSpec(key="nettle", name="Nettle Price", room_key="store"),
            CharacterSpec(key="lark", name="Lark Dandelion", room_key="music"),
            CharacterSpec(key="bram", name="Bram Hollow", room_key="courtyard"),
            CharacterSpec(
                key="wick",
                name="Wick Hearth",
                room_key="kitchen",
                description="The kitchen steward monitoring the shared pantry.",
            ),
            CharacterSpec(key="kestrel", name="Kestrel Vale", room_key="clinic"),
            CharacterSpec(
                key="tavi",
                name="Tavi Quill",
                room_key="laundry",
                description="A resident sorting laundry beside the lost-sock basket.",
            ),
            CharacterSpec(key="brindle", name="Brindle", room_key="courtyard", species="pet"),
            CharacterSpec(
                key="orla",
                name="Orla Finch",
                room_key="security",
                description="A security resident reviewing the incident log.",
            ),
            CharacterSpec(
                key="rook",
                name="Rook Vale",
                room_key="street",
                controller="scripted",
                script_name="clover-street-route",
                script_loop=True,
                description="A route checker walking between Street Stop and the corner store.",
            ),
            CharacterSpec(key="cress", name="Cress Bell", room_key="security"),
            CharacterSpec(key="morrow", name="Morrow Grey", room_key="empty_unit"),
            CharacterSpec(
                key="guide",
                name="Cleo Clover",
                room_key="lobby",
                controller="scripted",
                script_name="clover-city-guide-intro",
                description="The lobby concierge who explains routes without leaving the desk.",
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _augment(
            actor,
            world.objects["directory"],
            ReadableComponent(
                title="Clover City Directory",
                text=(
                    "From the lobby: east to Mailroom; north to Elevator; west to Stairwell; "
                    "south to Courtyard; northeast to Clinic Room; northwest to Music Room; "
                    "southeast to Security Office; out to Street Stop. From Courtyard, west "
                    "reaches Laundry Room and east reaches Community Kitchen. From Stairwell, "
                    "up reaches Rooftop Garden and down reaches Basement Workshop."
                ),
            ),
        )
        _augment(
            actor,
            world.objects["bulletin"],
            ReadableComponent(
                title="Clover City Daily Bulletin",
                text=(
                    "Missing package in Mailroom. Elevator unreliable. Noise complaint "
                    "near Music Room. Community Kitchen chores open. Rooftop Garden water "
                    "ration active. "
                    "Residents follow visible routines throughout shared facilities. Rook's "
                    "posted route alternates between Street Stop and Corner Store with a route "
                    "report at each stop; ordinary travel and inspection let the route advance."
                ),
            ),
        )
        _augment(
            actor,
            world.characters["guide"],
            TutorialGuideComponent(
                help_text=(
                    "From Clover City Lobby: east is Mailroom, north Elevator, west Stairwell, "
                    "south Courtyard, northeast Clinic Room, northwest Music Room, southeast "
                    "Security Office, and out Street Stop. Laundry Room and Community Kitchen "
                    "branch west and east from Courtyard; Rooftop Garden is up and Basement "
                    "Workshop down from Stairwell."
                )
            ),
        )
        _augment(
            actor,
            world.objects["courtyard_directory"],
            ReadableComponent(
                title="Courtyard Directory",
                text=(
                    "From Courtyard: west to Laundry Room; east to Community Kitchen; north "
                    "to Clover City Lobby."
                ),
            ),
        )
        _augment(
            actor,
            world.objects["stairwell_directory"],
            ReadableComponent(
                title="Stairwell Directory",
                text=(
                    "From Stairwell: up to Rooftop Garden; down to Basement Workshop; east "
                    "to Clover City Lobby."
                ),
            ),
        )
        _augment(
            actor,
            world.objects["street_timetable"],
            ReadableComponent(
                title="Street Stop Timetable",
                text=(
                    "Rook Vale repeats this public route: depart Street Stop east for Corner "
                    "Store, report there, return west to Street Stop, report here, repeat."
                ),
            ),
        )
        _augment(
            actor,
            world.objects["log"],
            ReadableComponent(
                title="Clover City Incident Log",
                text=(
                    "OPEN parcel-01: parcel missing from mailroom. "
                    "OPEN water-01: rooftop ration and pantry shortage. "
                    "OPEN lift-01: elevator fault follows a music-room noise complaint."
                ),
            ),
            WritableComponent(remaining_space=1200, erasable=False),
        )
        _augment(
            actor,
            world.objects["pantry"],
            ConsumableComponent(current_uses=2, max_uses=8),
        )
        _augment(
            actor,
            world.objects["rain"],
            ConsumableComponent(current_uses=1, max_uses=8),
        )
        _augment(
            actor,
            world.objects["water_jug"],
            DrinkableComponent(hydration=15.0),
            ConsumableComponent(current_uses=4, max_uses=4),
        )
        _augment(
            actor,
            world.objects["panel"],
            MachineComponent(machine_type="elevator control", quality=0.2),
            MachineBreakdownComponent(
                reason="intermittent relay fault",
                required_tool_kind="repair_tool",
            ),
        )
        _augment(
            actor,
            world.objects["piano"],
            ButtonComponent(active=True, toggle=True, pressed=False),
            ReadableComponent(
                title="Music Room Noise Notice",
                text=(
                    "OPEN noise complaint: rehearsal continues while the elevator relay "
                    "is unstable."
                ),
            ),
        )
        saffron = actor.world.get_entity(world.characters["saffron"])
        thirst = saffron.get_component(ThirstComponent)
        _augment(
            actor,
            saffron.id,
            ThirstComponent(
                meter=with_value(thirst.meter, 70.0),
                hydration_loss_rate=thirst.hydration_loss_rate,
                last_drank_epoch=thirst.last_drank_epoch,
            ),
        )
        parcel = spawn_entity(
            actor.world,
            [
                IdentityComponent(name="misrouted parcel", kind="parcel"),
                PortableComponent(can_pick_up=True),
            ],
        )
        actor.world.get_entity(world.rooms["laundry"]).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), parcel.id
        )

        story_specs = (
            (
                "missing_parcel",
                "mailroom",
                "pip",
                "ada",
                "Find the misrouted parcel, return it to the mailroom, and record "
                "a witness report marking the missing parcel resolved.",
            ),
            (
                "rooftop_water_shortage",
                "roof",
                "wick",
                "saffron",
                "Refill the rooftop water and share the remaining pantry supply fairly.",
            ),
            (
                "elevator_noise_dispute",
                "elevator",
                "jun",
                "orla",
                "Inspect the elevator fault, address the noise complaint, and close "
                "the incident log.",
            ),
        )
        for index, (kind, room_key, debtor_key, creditor_key, text) in enumerate(story_specs):
            incident = spawn_entity(
                actor.world,
                [
                    IdentityComponent(name=kind.replace("_", " "), kind="incident"),
                    IncidentComponent(
                        kind=kind,
                        budget_spent=0,
                        started_at_epoch=actor.epoch,
                    ),
                ],
            )
            actor.world.get_entity(world.rooms[room_key]).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), incident.id
            )
            debtor = world.characters[debtor_key]
            creditor = world.characters[creditor_key]
            create_obligation(
                actor.world,
                kind="request",
                text=text,
                debtor_id=debtor,
                creditor_id=creditor,
                source_event_id=f"clover-story-{index}",
                created_at_epoch=actor.epoch,
                due_epoch=actor.epoch + 24 * 60 * 60,
            )
            actor.world.get_entity(debtor).add_relationship(
                SocialBond(familiarity=0.4, trust=0.2), creditor
            )
            if kind == "missing_parcel":
                incident.add_relationship(IncidentSpawned(kind="returned"), parcel.id)
                incident.add_relationship(
                    IncidentSpawned(kind="reported"), world.objects["log"]
                )
            elif kind == "rooftop_water_shortage":
                incident.add_relationship(
                    IncidentSpawned(kind="returned"), world.objects["water_jug"]
                )
                incident.add_relationship(
                    IncidentSpawned(kind="reported"), world.objects["log"]
                )
            else:
                incident.add_relationship(
                    IncidentSpawned(kind="activated"), world.objects["piano"]
                )
                incident.add_relationship(
                    IncidentSpawned(kind="reported"), world.objects["log"]
                )
        for index, character_id in enumerate(world.characters.values()):
            character = actor.world.get_entity(character_id)
            _augment(actor, character_id, CareerComponent(title="resident", hourly_pay=0))
            for hour, activity in (
                (8, "morning routine"),
                (14, "shared chore"),
                (20, "evening social"),
            ):
                if character_id == world.characters["jun"] and activity == "shared chore":
                    activity = "inspect unreliable elevator after music-room noise"
                if character_id == world.characters["orla"] and activity == "shared chore":
                    activity = "review elevator and music-room disagreement"
                routine = spawn_entity(
                    actor.world,
                    [RoutineComponent(activity=activity, next_due_epoch=(hour + index) * 3600)],
                )
                character.add_relationship(HasRoutine(), routine.id)
        _region_stack(
            actor,
            world.rooms.values(),
            (("Clover City", "city"), ("Clover Commons", "district")),
        )
    return world


APPLE_CROSSING_DEMO = WorldGenerator(
    name="apple-crossing",
    generate=_with_regions(
        hungry_courier_example,
        (("Apple Vale", "region"), ("Apple Crossing", "area")),
    ),
    description=(
        "A guided first session at Apple Crossing where a hungry courier learns through "
        "normal world actions before delivering a letter."
    ),
    group="tutorials",
    uses_seed=False,
)

BELL_GREEN_DEMO = WorldGenerator(
    name="bell-green",
    generate=bell_green_example,
    description="A cozy online-style town sandbox with mail, garden, shop, inn, and shrine.",
    group="tutorials",
    uses_seed=False,
)

CLOVER_CITY_DEMO = WorldGenerator(
    name="clover-city",
    generate=clover_city_example,
    description="A dense city-block social simulation with shared facilities and routines.",
    group="tutorials",
    uses_seed=False,
)

__all__ = [
    "APPLE_CROSSING_DEMO",
    "BELL_GREEN_DEMO",
    "CLOVER_CITY_DEMO",
]
