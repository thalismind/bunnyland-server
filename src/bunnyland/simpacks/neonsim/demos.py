"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.core.components import (
    RegionComponent,
)
from bunnyland.core.ecs import replace_component
from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


async def neonsim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import IdentityComponent, PortableComponent
    from bunnyland.core.edges import ContainmentMode, Contains
    from bunnyland.simpacks.colonysim.mechanics import ResourceStackComponent
    from bunnyland.simpacks.neonsim.mechanics import (
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
            RoomSpec(key="strip", title="Glass Spire Strip", biome="city", light=0.4, celsius=14.0),
            RoomSpec(
                key="office",
                title="Arasaka Records Office",
                biome="corp",
                indoor=True,
                light=0.7,
                celsius=21.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="strip", direction="north", to_key="office"),
            ExitSpec(from_key="office", direction="south", to_key="strip"),
        ],
        characters=[
            CharacterSpec(
                key="runner",
                name="Vesper",
                room_key="strip",
                controller="suspended",
                traits=("paranoid",),
                goals=("exfiltrate the personnel files",),
            ),
            CharacterSpec(
                key="fixer",
                name="Padre",
                room_key="strip",
                controller="llm",
                llm_profile="neon-city fixer",
                goals=("keep the runners working",),
            ),
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

        kit = _add(
            actor,
            strip,
            [
                IdentityComponent(name="a breach kit", kind="tool"),
                PortableComponent(can_pick_up=True),
                ExploitComponent(power=3),
            ],
        )
        runner.add_relationship(Contains(mode=ContainmentMode.INVENTORY), kit.id)
        scrip = _add(
            actor,
            strip,
            [
                IdentityComponent(name="scrip x80", kind="resource"),
                PortableComponent(can_pick_up=True),
                ResourceStackComponent(resource_type="scrip", quantity=80),
            ],
        )
        runner.add_relationship(Contains(mode=ContainmentMode.INVENTORY), scrip.id)

        _add(
            actor,
            strip,
            [
                IdentityComponent(name="a corp turnstile", kind="checkpoint"),
                CheckpointComponent(clearance_required=2, bribe_cost=20),
            ],
        )
        _add(
            actor,
            strip,
            [
                IdentityComponent(name="a back-alley flop", kind="safehouse"),
                SafehouseComponent(),
            ],
        )
        _add(
            actor,
            strip,
            [
                IdentityComponent(name="a chrome dealer's stall", kind="vendor"),
                BlackMarketComponent(price=20, contraband_name="synthcoke", contraband_heat=3.0),
            ],
        )
        _add(
            actor,
            strip,
            [
                IdentityComponent(name="a ripperdoc booth", kind="clinic"),
                ClinicComponent(licensed=False, install_cost=40),
            ],
        )
        _add(
            actor,
            strip,
            [
                IdentityComponent(name="a reflex booster", kind="implant"),
                PortableComponent(can_pick_up=True),
                ImplantComponent(
                    implant_type="reflex",
                    slot="neural",
                    maintenance_interval=7200.0,
                    side_effect="hand tremors",
                ),
            ],
        )
        _add(
            actor,
            strip,
            [
                IdentityComponent(name="a data-run contract", kind="contract"),
                RunnerContractComponent(objective="courier the records", payout=250),
            ],
        )

        _add(
            actor,
            office,
            [
                IdentityComponent(name="a records vault", kind="cyberpunk-site"),
                CyberpunkSiteComponent(site_type="data center"),
                SecurityZoneComponent(clearance_required=3),
                RestrictedAreaComponent(),
            ],
        )
        _add(
            actor,
            office,
            [
                IdentityComponent(name="a ceiling camera", kind="camera"),
                DeviceComponent(device_type="camera"),
                CameraComponent(),
                SurveillanceCoverageComponent(),
            ],
        )
        _add(
            actor,
            office,
            [
                IdentityComponent(name="a records server", kind="server"),
                DeviceComponent(device_type="server"),
                HackableComponent(security=2, owner="arasaka"),
                DataPayloadComponent(name="personnel files", sensitive=True),
            ],
        )
    return world


async def stuck_subway_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A subway car stalled between stations, strangers and failing systems in the dark."""

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
    from bunnyland.simpacks.voidsim.mechanics import (
        DistressSignalComponent,
        LifeSupportComponent,
        OxygenComponent,
        PowerGridComponent,
        ShipSystemComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="car",
                title="Stalled Subway Car",
                biome="subway",
                indoor=True,
                light=0.3,
                celsius=27.0,
            ),
            RoomSpec(
                key="cab",
                title="Operator's Cab",
                biome="subway",
                indoor=True,
                light=0.45,
                celsius=26.0,
            ),
            RoomSpec(
                key="tunnel",
                title="Dark Tunnel Catwalk",
                biome="tunnel",
                indoor=True,
                light=0.05,
                celsius=18.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="car", direction="fore", to_key="cab"),
            ExitSpec(from_key="cab", direction="aft", to_key="car"),
            ExitSpec(from_key="car", direction="emergency-door", to_key="tunnel"),
            ExitSpec(from_key="tunnel", direction="back-aboard", to_key="car"),
        ],
        objects=[
            ObjectSpec(
                key="pretzel",
                room_key="car",
                name="a half-eaten soft pretzel",
                kind="food",
                nutrition=3.0,
                satiety=8.0,
                portable=True,
            ),
            ObjectSpec(
                key="bottle",
                room_key="car",
                name="a sweating water bottle",
                kind="water",
                hydration=10.0,
                portable=True,
            ),
            ObjectSpec(
                key="notice",
                room_key="car",
                name="a laminated service notice",
                kind="paper",
                writable=False,
                portable=False,
            ),
            ObjectSpec(
                key="map",
                room_key="car",
                name="a strip map of the line",
                kind="paper",
                writable=False,
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="commuter",
                name="Priya Nadeau",
                room_key="car",
                controller="suspended",
                traits=("anxious", "polite", "practical"),
                goals=("get home tonight", "keep everyone calm"),
            ),
            CharacterSpec(
                key="operator",
                name="Gus Holloway",
                room_key="cab",
                controller="llm",
                llm_profile="transit-operator",
                traits=("gruff", "reassuring"),
                goals=("restart the car", "keep passengers seated"),
            ),
            CharacterSpec(
                key="busker",
                name="Remy Osei",
                room_key="car",
                controller="llm",
                llm_profile="stuck-busker",
                traits=("easygoing", "talkative"),
                goals=("lighten the mood", "busk for transfer fare"),
            ),
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
        _augment(
            actor,
            car,
            PowerGridComponent(capacity=100.0, available=18.0),
            LifeSupportComponent(online=False),
            OxygenComponent(level=82.0, maximum=100.0),
        )
        # The dead traction motor up front, and the intercom crackling at control.
        _add(
            actor,
            cab,
            [
                IdentityComponent(name="the traction motor", kind="ship-system"),
                ShipSystemComponent(system_type="traction motor", integrity=40.0, online=False),
            ],
        )
        _add(
            actor,
            cab,
            [
                IdentityComponent(name="the cab intercom", kind="signal"),
                DistressSignalComponent(
                    text="Control, car 1142 dead in the tube past Junction St."
                ),
            ],
        )
        # The clamped social want that makes the wait bite: a transfer she may now miss.
        _augment(
            actor,
            world.characters["commuter"],
            WhimComponent(want="make the last cross-town transfer"),
        )
        # The tunnel is pitch-dark and not somewhere passengers should wander.
        _augment(
            actor,
            tunnel,
            PointOfInterestComponent(location_type="service tunnel", region="Junction St"),
            DiscoveryComponent(),
        )
        _add(
            actor,
            car,
            [
                IdentityComponent(name="a strip map marked at the dead spot", kind="paper"),
                PortableComponent(can_pick_up=True),
                ReadableComponent(
                    title="Strip Map",
                    text="Someone has circled the same stretch of tunnel three times "
                    "and written: it always stops here.",
                ),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["notice"]),
            ReadableComponent(
                title="Service Notice",
                text="In the event of an extended hold, remain in the car. Do not "
                "open the emergency door onto the trackway.",
            ),
        )
    return world


NEONSIM_DEMO = WorldGenerator(
    name="neonsim-demo",
    generate=_with_regions(neonsim_example, (("Night City", "city"), ("Watson", "neighborhood"))),
    description="A neon strip and corp office with surveillance, a hackable server, a fixer "
    "contract, a ripperdoc, and a runner ready to break in.",
    group="simpack sandbox",
    uses_seed=False,
)

STUCK_SUBWAY_DEMO = WorldGenerator(
    name="stuck-subway-demo",
    generate=_with_regions(
        stuck_subway_example, (("Metro Line 4", "zone"), ("Tunnel Section 12", "area"))
    ),
    description="A subway car stalled between stations with dim power, dead ventilation, a "
    "dead traction motor, and strangers waiting out the hold in the dark.",
    group="scene demo",
    uses_seed=False,
)
