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
from bunnyland.foundation.needs.mechanics import HungerComponent
from bunnyland.foundation.persona.mechanics import GoalComponent
from bunnyland.foundation.tutorial.mechanics import HungryCourierControllerComponent

from ..core.components import (
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
                        "but wants do not bypass world rules. Find an apple, bring it back, "
                        "and watch what happens."
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
                    "table where a courier waits beside a sealed letter."
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
                    "Help Pip deliver the courier letter. Find food at Apple Hedge, "
                    "bring or leave it where Pip can reach it, then watch Pip act.",
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

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key="green", title="Bell Green", biome="town", light=0.8, celsius=18.0),
            RoomSpec(
                key="post_office",
                title="Bell Green Post Office",
                biome="town",
                indoor=True,
                light=0.7,
                celsius=20.0,
            ),
            RoomSpec(key="garden_walk", title="Garden Walk", biome="garden", light=0.9),
            RoomSpec(
                key="garden_shed",
                title="Saffron's Garden Shed",
                biome="garden",
                indoor=True,
                light=0.55,
            ),
            RoomSpec(key="market_lane", title="Market Lane", biome="town", light=0.8),
            RoomSpec(
                key="store",
                title="Nettle's General Store",
                biome="town",
                indoor=True,
                light=0.7,
            ),
            RoomSpec(
                key="workshop",
                title="Jun's Workshop",
                biome="workshop",
                indoor=True,
                light=0.65,
            ),
            RoomSpec(
                key="inn",
                title="Hearthwick Inn",
                biome="inn",
                indoor=True,
                light=0.75,
            ),
            RoomSpec(key="footbridge", title="River Footbridge", biome="river", light=0.75),
            RoomSpec(key="pet_yard", title="Pet Yard", biome="yard", light=0.85),
            RoomSpec(key="bell_shrine", title="Old Bell Shrine", biome="shrine", light=0.55),
            RoomSpec(key="courier_path", title="Courier Path", biome="road", light=0.75),
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
            ObjectSpec(key="notice", room_key="green", name="central notice board", kind="paper"),
            ObjectSpec(
                key="mailbox",
                room_key="green",
                name="community mailbox",
                kind="container",
                portable=False,
            ),
            ObjectSpec(key="bell", room_key="green", name="town bell", portable=False),
            ObjectSpec(key="letters", room_key="post_office", name="sorted letters", kind="paper"),
            ObjectSpec(key="herbs", room_key="garden_walk", name="herb beds", portable=False),
            ObjectSpec(key="basket", room_key="garden_walk", name="harvest basket"),
            ObjectSpec(key="tools", room_key="garden_shed", name="seed packets", portable=True),
            ObjectSpec(key="crate", room_key="market_lane", name="produce crates", portable=False),
            ObjectSpec(key="food", room_key="store", name="food shelf", kind="food", satiety=18.0),
            ObjectSpec(key="bench", room_key="workshop", name="workbench", portable=False),
            ObjectSpec(key="stew", room_key="inn", name="stew pot", kind="food", satiety=25.0),
            ObjectSpec(key="bowl", room_key="pet_yard", name="feed bowl", portable=False),
            ObjectSpec(key="old_bell", room_key="bell_shrine", name="weathered bell"),
            ObjectSpec(key="milestone", room_key="courier_path", name="route milestone"),
        ],
        characters=[
            CharacterSpec(key="pippa", name="Pippa Bramble", room_key="post_office"),
            CharacterSpec(key="pip", name="Pip Thistle", room_key="courier_path"),
            CharacterSpec(key="mira", name="Mira Vale", room_key="bell_shrine"),
            CharacterSpec(key="saffron", name="Saffron Reed", room_key="garden_walk"),
            CharacterSpec(key="nettle", name="Nettle Price", room_key="store"),
            CharacterSpec(key="jun", name="Jun Copper", room_key="workshop"),
            CharacterSpec(key="lark", name="Lark Dandelion", room_key="inn"),
            CharacterSpec(key="bram", name="Bram Hollow", room_key="green"),
            CharacterSpec(key="wick", name="Wick Hearth", room_key="inn"),
            CharacterSpec(key="button", name="Button", room_key="pet_yard", species="pet"),
            CharacterSpec(key="morrow", name="Morrow Grey", room_key="courier_path"),
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
                    "Starter goals: help Pip finish a delivery; bring Saffron a harvest "
                    "basket; ask Jun what broke; feed Button; visit the Old Bell Shrine."
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
    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(key=key, title=title, biome=biome, indoor=indoor, light=0.65)
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
            ObjectSpec(key="directory", room_key="lobby", name="directory board", kind="paper"),
            ObjectSpec(key="bulletin", room_key="lobby", name="daily bulletin", kind="paper"),
            ObjectSpec(key="parcels", room_key="mailroom", name="parcel locker", portable=False),
            ObjectSpec(key="panel", room_key="elevator", name="button panel", portable=False),
            ObjectSpec(key="key", room_key="stairwell", name="dropped key", kind="key"),
            ObjectSpec(key="sock", room_key="laundry", name="lost sock basket", portable=False),
            ObjectSpec(key="planters", room_key="courtyard", name="planter boxes"),
            ObjectSpec(key="rain", room_key="roof", name="rain barrel", kind="water"),
            ObjectSpec(key="pantry", room_key="kitchen", name="community pantry", kind="food"),
            ObjectSpec(key="parts", room_key="workshop", name="spare parts"),
            ObjectSpec(key="snacks", room_key="store", name="snack shelf", kind="food"),
            ObjectSpec(key="clipboard", room_key="clinic", name="appointment clipboard"),
            ObjectSpec(key="piano", room_key="music", name="old piano", portable=False),
            ObjectSpec(key="log", room_key="security", name="incident log", kind="paper"),
        ],
        characters=[
            CharacterSpec(key="ada", name="Ada Warden", room_key="lobby"),
            CharacterSpec(key="pip", name="Pip Thistle", room_key="mailroom"),
            CharacterSpec(key="mira", name="Mira Vale", room_key="apt_mira"),
            CharacterSpec(key="jun", name="Jun Copper", room_key="workshop"),
            CharacterSpec(key="saffron", name="Saffron Reed", room_key="roof"),
            CharacterSpec(key="nettle", name="Nettle Price", room_key="store"),
            CharacterSpec(key="lark", name="Lark Dandelion", room_key="music"),
            CharacterSpec(key="bram", name="Bram Hollow", room_key="courtyard"),
            CharacterSpec(key="wick", name="Wick Hearth", room_key="kitchen"),
            CharacterSpec(key="kestrel", name="Kestrel Vale", room_key="clinic"),
            CharacterSpec(key="tavi", name="Tavi Quill", room_key="laundry"),
            CharacterSpec(key="brindle", name="Brindle", room_key="courtyard", species="pet"),
            CharacterSpec(key="orla", name="Orla Finch", room_key="security"),
            CharacterSpec(key="rook", name="Rook Vale", room_key="street"),
            CharacterSpec(key="cress", name="Cress Bell", room_key="security"),
            CharacterSpec(key="morrow", name="Morrow Grey", room_key="empty_unit"),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _augment(
            actor,
            world.objects["bulletin"],
            ReadableComponent(
                title="Clover City Daily Bulletin",
                text=(
                    "Missing package in the mailroom. Elevator unreliable. Noise complaint "
                    "near the music room. Kitchen chores open. Rooftop water ration active."
                ),
            ),
        )
        for index, character_id in enumerate(world.characters.values()):
            character = actor.world.get_entity(character_id)
            _augment(actor, character_id, CareerComponent(title="resident", hourly_pay=0))
            for hour, activity in (
                (8, "morning routine"),
                (14, "shared chore"),
                (20, "evening social"),
            ):
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
