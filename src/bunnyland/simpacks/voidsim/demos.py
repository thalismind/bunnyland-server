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


async def voidsim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.simpacks.voidsim.mechanics import (
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
            RoomSpec(
                key="bridge", title="Bridge", biome="ship", indoor=True, light=0.7, celsius=21.0
            ),
            RoomSpec(
                key="engineering",
                title="Engineering",
                biome="ship",
                indoor=True,
                light=0.5,
                celsius=24.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="bridge", direction="aft", to_key="engineering"),
            ExitSpec(from_key="engineering", direction="fore", to_key="bridge"),
        ],
        characters=[
            CharacterSpec(
                key="captain",
                name="Captain Vesta",
                room_key="bridge",
                controller="suspended",
                traits=("steady",),
                goals=("keep the ship flying",),
            ),
            CharacterSpec(
                key="engineer",
                name="Sprocket",
                room_key="engineering",
                controller="llm",
                llm_profile="engineer",
                goals=("keep systems online",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        bridge, engineering = world.rooms["bridge"], world.rooms["engineering"]
        # The two rooms are pressurized habitat modules with their own life support.
        _augment(
            actor,
            bridge,
            HabitatModuleComponent(module_type="bridge"),
            PressurizedComponent(pressure=1.0),
            OxygenComponent(level=96.0, maximum=100.0),
            LifeSupportComponent(online=True),
        )
        _augment(
            actor,
            engineering,
            HabitatModuleComponent(module_type="engineering"),
            PressurizedComponent(pressure=1.0),
            OxygenComponent(level=88.0, maximum=100.0),
            LifeSupportComponent(online=True),
        )
        # The ship itself, with power, fuel, jump drive, and sensors.
        _add(
            actor,
            bridge,
            [
                IdentityComponent(name="the Marsh Lark", kind="ship"),
                ShipComponent(name="Marsh Lark", hull_integrity=82.0),
                PowerGridComponent(capacity=100.0, available=60.0),
                FuelComponent(level=70.0, maximum=100.0),
                JumpDriveComponent(charged=True),
                SensorComponent(scan_range=2.0),
            ],
        )
        _add(
            actor,
            bridge,
            [
                IdentityComponent(name="the forward airlock", kind="airlock"),
                AirlockComponent(module_id=str(bridge), exposes_vacuum=True),
            ],
        )
        # A damaged reactor to repair, and a distress signal to scan and answer.
        _add(
            actor,
            engineering,
            [
                IdentityComponent(name="the reactor", kind="ship-system"),
                ShipSystemComponent(system_type="reactor", integrity=55.0, online=True),
            ],
        )
        _add(
            actor,
            bridge,
            [
                IdentityComponent(name="a distress beacon", kind="signal"),
                DistressSignalComponent(text="Derelict hauler adrift, life signs faint."),
            ],
        )
    return world


async def star_opera_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A bright star-opera demo with rebels, a rusty courier ship, and a masked officer."""

    del options
    from bunnyland.core.components import PortableComponent, ReadableComponent
    from bunnyland.simpacks.barbariansim.mechanics import DurabilityComponent, WeaponComponent
    from bunnyland.simpacks.dragonsim.mechanics import FactionComponent
    from bunnyland.simpacks.voidsim.mechanics import (
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
            RoomSpec(
                key="duneport",
                title="Saffron Duneport Market",
                biome="desert-port",
                light=0.95,
                celsius=34.0,
            ),
            RoomSpec(
                key="freighter",
                title="Rustwing Freighter Hold",
                biome="ship",
                indoor=True,
                light=0.55,
                celsius=22.0,
            ),
            RoomSpec(
                key="checkpoint",
                title="Black-Helmet Checkpoint",
                biome="checkpoint",
                indoor=True,
                light=0.7,
                celsius=20.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="duneport", direction="aboard", to_key="freighter"),
            ExitSpec(from_key="freighter", direction="down-ramp", to_key="duneport"),
            ExitSpec(from_key="duneport", direction="east", to_key="checkpoint"),
            ExitSpec(from_key="checkpoint", direction="west", to_key="duneport"),
        ],
        objects=[
            ObjectSpec(
                key="ration",
                room_key="duneport",
                name="a packet of sun-baked rations",
                kind="food",
                nutrition=4.0,
                satiety=15.0,
                portable=True,
            ),
            ObjectSpec(
                key="canteen",
                room_key="duneport",
                name="a dented vapor canteen",
                kind="water",
                hydration=20.0,
                portable=True,
                renewable=False,
            ),
            ObjectSpec(
                key="data_spool",
                room_key="checkpoint",
                name="a coded courier spool",
                kind="paper",
                writable=False,
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="farmhand",
                name="Tavi Orun",
                room_key="duneport",
                controller="suspended",
                traits=("idealistic", "restless"),
                goals=("escape the dunes", "deliver the coded spool"),
            ),
            CharacterSpec(
                key="courier",
                name="Captain Brindle Voss",
                room_key="freighter",
                controller="llm",
                llm_profile="wry-courier",
                traits=("charming", "indebted"),
                goals=("get paid before helping anyone",),
            ),
            CharacterSpec(
                key="mentor",
                name="Old Sera",
                room_key="duneport",
                controller="llm",
                llm_profile="star-monk",
                traits=("patient", "cryptic"),
                goals=("teach Tavi restraint",),
            ),
            CharacterSpec(
                key="marshal",
                name="Marshal Vark",
                room_key="checkpoint",
                controller="llm",
                llm_profile="masked-officer",
                traits=("severe", "ceremonial"),
                goals=("recover the courier spool",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        duneport = world.rooms["duneport"]
        freighter = world.rooms["freighter"]
        _augment(actor, duneport, StarSystemComponent(name="Amber Verge"))
        _augment(
            actor,
            freighter,
            HabitatModuleComponent(module_type="freighter-hold"),
            PressurizedComponent(pressure=1.0),
            OxygenComponent(level=91.0),
            LifeSupportComponent(online=True),
            NavigationRouteComponent(destination_id="Free Lantern", fuel_cost=20.0),
        )
        _add(
            actor,
            freighter,
            [
                IdentityComponent(name="the Rustwing", kind="ship"),
                ShipComponent(name="Rustwing", hull_integrity=64.0),
                PowerGridComponent(capacity=80.0, available=38.0),
                FuelComponent(level=44.0, maximum=100.0),
                JumpDriveComponent(charged=False),
                SensorComponent(scan_range=1.5),
            ],
        )
        _add(
            actor,
            duneport,
            [
                IdentityComponent(name="Free Lantern Cell", kind="faction"),
                FactionComponent(
                    name="Free Lantern Cell", ideology="smuggle hope past checkpoints"
                ),
            ],
        )
        add_demo_quest(
            actor,
            duneport,
            "run-checkpoint",
            "Run The Checkpoint",
            "Carry the coded spool aboard the Rustwing",
        )
        _add(
            actor,
            world.rooms["checkpoint"],
            [
                IdentityComponent(name="a humming training baton", kind="weapon"),
                PortableComponent(can_pick_up=True),
                WeaponComponent(damage=5.0, damage_type="energy", lethal_capable=False),
                DurabilityComponent(current=30.0, maximum=40.0),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["data_spool"]),
            ReadableComponent(
                title="Courier Spool",
                text="A compressed route ledger points toward the Free Lantern.",
            ),
        )
    return world


VOIDSIM_DEMO = WorldGenerator(
    name="voidsim-demo",
    generate=_with_regions(
        voidsim_example, (("Helios Sector", "sector"), ("ISV Wanderer", "ship"))
    ),
    description="A modular ship with life support, power, and a damaged reactor.",
    group="simpack sandbox",
    uses_seed=False,
)

STAR_OPERA_DEMO = WorldGenerator(
    name="star-opera-demo",
    generate=_with_regions(
        star_opera_example, (("Saffron Sector", "sector"), ("Duneport", "city"))
    ),
    description="A legally distinct star-opera rebellion at a desert port and rusty freighter.",
    group="pop culture",
    uses_seed=False,
)
