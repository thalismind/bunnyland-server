"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.core.ecs import replace_component
from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


async def daggersim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import IdentityComponent
    from bunnyland.simpacks.daggersim.mechanics import (
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
            CharacterSpec(
                key="wren",
                name="Wren",
                room_key="square",
                controller="suspended",
                traits=("curious",),
                goals=("make a name in town",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        square, road = world.rooms["square"], world.rooms["road"]
        _augment(
            actor,
            square,
            LawRegionComponent(region_id="moss-road", fines={"theft": 20, "default": 10}),
        )
        _add(
            actor,
            square,
            [
                IdentityComponent(name="Carrot Factors Bank", kind="bank"),
                BankComponent(name="Carrot Factors Bank", region_id="moss-road"),
            ],
        )
        _add(
            actor,
            square,
            [
                IdentityComponent(name="Burrow Cartographers", kind="institution"),
                InstitutionComponent(name="Burrow Cartographers", institution_type="guild"),
            ],
        )
        _add(
            actor,
            square,
            [
                IdentityComponent(name="a tavern rumor", kind="rumor"),
                RumorComponent(text="A vault lies beneath the old hamlet down the road."),
            ],
        )
        # An unrealized hamlet down the road, ready for worldgen to expand on demand.
        _add(
            actor,
            road,
            [
                IdentityComponent(name="Rain Garden Hamlet", kind="settlement"),
                ProceduralSiteComponent(site_type="hamlet", seed="rain-garden"),
                UnrealizedLocationComponent(
                    summary="a damp trading stop at the road's edge", region_id="moss-road"
                ),
                ExpansionHookComponent(trigger="rumor", generator_plugin_id="worldgen.recursive"),
            ],
        )
        # Travel hubs so the square and road form a route.
        actor.world.get_entity(square).add_component(
            TravelHubComponent(name="Town Square", region_id="moss-road")
        )
        actor.world.get_entity(road).add_component(
            TravelHubComponent(name="Moss Road", region_id="moss-road")
        )
        actor.world.get_entity(square).add_relationship(
            TravelRoute(travel_seconds=2 * 60 * 60, label="moss road"), road
        )
        _augment(actor, world.characters["wren"], EtiquetteSkillComponent(level=2))
    return world


async def dive_scheme_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A dysfunctional city tavern where every room contains a terrible business plan."""

    del options
    from bunnyland.core.components import IdentityComponent, PortableComponent, ReadableComponent
    from bunnyland.simpacks.colonysim.mechanics import (
        JobComponent,
        ResourceStackComponent,
        WorkstationComponent,
    )
    from bunnyland.simpacks.daggersim.mechanics import LawRegionComponent, RumorComponent
    from bunnyland.simpacks.lifesim.mechanics import (
        CareerComponent,
        HouseholdFundsComponent,
        SkillSetComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="bar",
                title="Gull And Grift Taproom",
                biome="city-tavern",
                indoor=True,
                light=0.45,
                celsius=20.0,
            ),
            RoomSpec(
                key="office",
                title="Back Office Of Bad Ideas",
                biome="office",
                indoor=True,
                light=0.35,
                celsius=21.0,
            ),
            RoomSpec(
                key="alley",
                title="Dumpster Negotiation Alley",
                biome="alley",
                light=0.25,
                celsius=12.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="bar", direction="back", to_key="office"),
            ExitSpec(from_key="office", direction="front", to_key="bar"),
            ExitSpec(from_key="bar", direction="out", to_key="alley"),
            ExitSpec(from_key="alley", direction="in", to_key="bar"),
        ],
        objects=[
            ObjectSpec(
                key="beer",
                room_key="bar",
                name="a questionable house lager",
                kind="water",
                hydration=6.0,
                portable=False,
            ),
            ObjectSpec(
                key="pretzels",
                room_key="bar",
                name="a bowl of over-salted pretzels",
                kind="food",
                nutrition=2.0,
                satiety=8.0,
                portable=False,
            ),
            ObjectSpec(
                key="scheme_board",
                room_key="office",
                name="a corkboard of doomed schemes",
                kind="paper",
                writable=True,
                portable=False,
            ),
            ObjectSpec(
                key="crate",
                room_key="alley",
                name="a crate of unsold novelty whistles",
                kind="container",
                portable=True,
                open=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="boss",
                name="Rex Malloy",
                room_key="bar",
                controller="suspended",
                traits=("commanding", "self-serving"),
                goals=("declare himself general manager",),
            ),
            CharacterSpec(
                key="performer",
                name="Lina Sharp",
                room_key="bar",
                controller="llm",
                llm_profile="dive-performer",
                traits=("vain", "quick-witted"),
                goals=("turn tonight into a showcase",),
            ),
            CharacterSpec(
                key="fixer",
                name="Ozzie Crank",
                room_key="office",
                controller="llm",
                llm_profile="bad-scheme-fixer",
                traits=("intense", "impatient"),
                goals=("prove the whistle franchise is viable",),
            ),
            CharacterSpec(
                key="investor",
                name="Marta Quill",
                room_key="alley",
                controller="llm",
                llm_profile="reckless-investor",
                traits=("rich", "bored"),
                goals=("buy influence with pocket change",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _augment(
            actor,
            world.rooms["bar"],
            LawRegionComponent(region_id="river-ward", fines={"brawl": 15, "default": 5}),
        )
        _add(
            actor,
            world.rooms["office"],
            [
                IdentityComponent(name="a broken laminating station", kind="workstation"),
                WorkstationComponent(station_type="office"),
            ],
        )
        _add(
            actor,
            world.rooms["alley"],
            [
                IdentityComponent(name="six novelty whistles", kind="resource"),
                PortableComponent(can_pick_up=True),
                ResourceStackComponent(resource_type="novelty-whistle", quantity=6),
            ],
        )
        _add(
            actor,
            world.rooms["office"],
            [
                IdentityComponent(name="tonight's terrible job", kind="job"),
                JobComponent(job_type="sell-whistles", priority=5),
            ],
        )
        _add(
            actor,
            world.rooms["bar"],
            [
                IdentityComponent(name="a barfly rumor", kind="rumor"),
                RumorComponent(text="The alley crate is worth less than the argument about it."),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["scheme_board"]),
            ReadableComponent(
                title="Scheme Board",
                text="Step 1: rebrand whistles. Step 2: citywide respect. "
                "Step 3: absolutely no refunds.",
            ),
        )
        _augment(
            actor,
            world.characters["boss"],
            CareerComponent(title="bar co-owner", level=1, hourly_pay=0),
            SkillSetComponent(levels={"intimidation": 2}),
            HouseholdFundsComponent(balance=37),
        )
    return world


async def gothic_count_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A gothic castle demo with an over-formal night host and suspicious paperwork."""

    del options
    from bunnyland.core.components import IdentityComponent, PortableComponent, ReadableComponent
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
                key="inn", title="Moor Road Inn", biome="moor", indoor=True, light=0.4, celsius=9.0
            ),
            RoomSpec(
                key="hall",
                title="Moonlit Castle Hall",
                biome="castle",
                indoor=True,
                light=0.2,
                celsius=8.0,
            ),
            RoomSpec(
                key="crypt",
                title="Velvet-Draped Crypt",
                biome="crypt",
                indoor=True,
                light=0.05,
                celsius=6.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="inn", direction="up-road", to_key="hall"),
            ExitSpec(from_key="hall", direction="down-road", to_key="inn"),
            ExitSpec(from_key="hall", direction="down", to_key="crypt"),
            ExitSpec(from_key="crypt", direction="up", to_key="hall"),
        ],
        objects=[
            ObjectSpec(
                key="broth",
                room_key="inn",
                name="a bowl of garlicy root broth",
                kind="food",
                nutrition=4.0,
                satiety=14.0,
                portable=False,
            ),
            ObjectSpec(
                key="tea",
                room_key="inn",
                name="a chipped cup of black tea",
                kind="water",
                hydration=12.0,
                portable=False,
            ),
            ObjectSpec(
                key="deed",
                room_key="hall",
                name="a crimson-sealed property deed",
                kind="paper",
                writable=False,
                portable=True,
            ),
            ObjectSpec(
                key="travel_trunk",
                room_key="hall",
                name="a brass-bound travel trunk",
                kind="container",
                portable=True,
                open=False,
            ),
        ],
        characters=[
            CharacterSpec(
                key="clerk",
                name="Merrit Vale",
                room_key="inn",
                controller="suspended",
                traits=("polite", "uneasy"),
                goals=("complete the property papers", "leave before midnight"),
            ),
            CharacterSpec(
                key="count",
                name="Lord Varro",
                room_key="hall",
                species="nightfolk",
                controller="llm",
                llm_profile="gothic-host",
                traits=("courtly", "hungry", "ancient"),
                goals=("keep guests comfortable", "avoid direct sunlight"),
            ),
            CharacterSpec(
                key="innkeeper",
                name="Nessa Pike",
                room_key="inn",
                controller="llm",
                llm_profile="worried-innkeeper",
                traits=("superstitious", "practical"),
                goals=("warn Merrit without naming the danger",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        hall, crypt = world.rooms["hall"], world.rooms["crypt"]
        _augment(
            actor,
            crypt,
            PointOfInterestComponent(location_type="crypt", region="Moor Road"),
            DiscoveryComponent(),
        )
        _augment(
            actor,
            world.characters["count"],
            SupernaturalAfflictionComponent(
                affliction_type="nocturnal hunger", contracted_at_epoch=0, stage="mastered"
            ),
            FeedingNeedComponent(current=6.0, maximum=10.0),
        )
        _add(
            actor,
            hall,
            [
                IdentityComponent(name="a hidden stair behind the portrait", kind="secret-door"),
                SecretDoorComponent(
                    target_room_id=str(crypt),
                    direction="behind portrait",
                    hint="The portrait frame is cleaner on one side.",
                ),
            ],
        )
        _add(
            actor,
            crypt,
            [
                IdentityComponent(name="a silvered travel mirror", kind="item"),
                PortableComponent(can_pick_up=True),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["deed"]),
            ReadableComponent(
                title="Property Deed",
                text="The buyer agrees to occupy the estate only after sunset "
                "and never inspect the lower rooms uninvited.",
            ),
        )
    return world


async def dungeon_vault_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A compact torchlit vault with a hidden final room and a relic objective."""

    del options
    from bunnyland.core.components import (
        DescriptionComponent,
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
    )
    from bunnyland.simpacks.daggersim.mechanics import (
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
            RoomSpec(
                key="threshold",
                title="Dungeon Threshold",
                biome="dungeon",
                indoor=True,
                light=0.25,
                celsius=11.0,
            ),
            RoomSpec(
                key="guardroom",
                title="Old Guardroom",
                biome="dungeon",
                indoor=True,
                light=0.18,
                celsius=10.0,
            ),
            RoomSpec(
                key="cistern",
                title="Black Cistern",
                biome="dungeon",
                indoor=True,
                light=0.08,
                celsius=8.0,
            ),
            RoomSpec(
                key="shrine",
                title="Ashen Shrine",
                biome="dungeon",
                indoor=True,
                light=0.12,
                celsius=9.0,
            ),
            RoomSpec(
                key="vault",
                title="Sealed Ember Vault",
                biome="dungeon",
                indoor=True,
                light=0.04,
                celsius=7.0,
            ),
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
            ObjectSpec(
                key="ration",
                room_key="threshold",
                name="a waxed trail ration",
                kind="food",
                nutrition=4.0,
                satiety=16.0,
                portable=True,
            ),
            ObjectSpec(
                key="canteen",
                room_key="cistern",
                name="a dented water canteen",
                kind="water",
                hydration=14.0,
                portable=True,
            ),
            ObjectSpec(
                key="torch",
                room_key="threshold",
                name="a pitch-soaked torch",
                kind="item",
                portable=True,
            ),
            ObjectSpec(
                key="chalk_map",
                room_key="guardroom",
                name="a chalked wall map",
                kind="paper",
                portable=False,
                writable=False,
            ),
            ObjectSpec(
                key="iron_box",
                room_key="vault",
                name="an iron-banded coffer",
                kind="container",
                portable=False,
                open=False,
            ),
        ],
        characters=[
            CharacterSpec(
                key="delver",
                name="Mira Flint",
                room_key="threshold",
                controller="suspended",
                traits=("methodical", "scarred"),
                goals=("map the vault", "bring back the ember idol"),
            ),
            CharacterSpec(
                key="warden",
                name="The Ember Warden",
                room_key="shrine",
                species="echo",
                controller="llm",
                llm_profile="dungeon-warden",
                traits=("ancient", "literal"),
                goals=("test anyone who reaches the shrine",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _add(
            actor,
            world.rooms["threshold"],
            [
                IdentityComponent(name="the Ember Vault", kind="dungeon"),
                DungeonComponent(
                    dungeon_id="ember-vault",
                    theme="torchlit ruin",
                    seed=seed,
                    level_count=1,
                    objective_summary="recover the ember idol",
                    entry_room_id=str(world.rooms["threshold"]),
                    generated=True,
                    entered=True,
                ),
            ],
        )
        room_meta = {
            "threshold": (0, "low", "The stair behind you climbs to black air."),
            "guardroom": (1, "medium", "Rusty spear racks point toward four exits."),
            "cistern": (2, "uneasy", "Water drips in a rhythm that almost spells words."),
            "shrine": (2, "high", "Ash lies thick around a blank stone altar."),
            "vault": (3, "ambush", "The final chamber waits behind the shrine wall."),
        }
        for key, (depth, risk, text) in room_meta.items():
            _augment(
                actor,
                world.rooms[key],
                DungeonRoomComponent(
                    dungeon_id="ember-vault",
                    depth=depth,
                    discovered=(key == "threshold"),
                    is_objective=(key == "vault"),
                    danger=risk,
                ),
                RestRiskComponent(band=risk),
                DescriptionComponent(short=text),
            )
        _augment(
            actor,
            world.characters["delver"],
            AutomapComponent(discovered_rooms=(str(world.rooms["threshold"]),)),
            RecallAnchorComponent(room_id=str(world.rooms["threshold"])),
        )
        _add(
            actor,
            world.rooms["shrine"],
            [
                IdentityComponent(name="hairline cracks behind the altar", kind="secret-door"),
                SecretDoorComponent(
                    target_room_id=str(world.rooms["vault"]),
                    direction="behind altar",
                    difficulty=2,
                    hint="Ash has been swept away from the rear flagstones.",
                ),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["chalk_map"]),
            ReadableComponent(
                title="Chalked Wall Map",
                text="NORTH to iron, EAST to water, WEST to ash, then search.",
            ),
        )
        _add(
            actor,
            world.rooms["vault"],
            [
                IdentityComponent(name="the ember idol", kind="objective"),
                PortableComponent(can_pick_up=True),
                DungeonObjectiveComponent(
                    objective_kind="relic", description="a palm-sized idol warm under the dust"
                ),
            ],
        )
    return world


async def dungeon_maze_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A looping slate maze built for mapping, backtracking, and suspicious directions."""

    del options
    from bunnyland.core.components import DescriptionComponent, IdentityComponent, ReadableComponent
    from bunnyland.simpacks.daggersim.mechanics import (
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
            RoomSpec(
                key="stair",
                title="Slate Stair",
                biome="dungeon",
                indoor=True,
                light=0.22,
                celsius=12.0,
            ),
            RoomSpec(
                key="crossroads",
                title="Four-Way Crossroads",
                biome="dungeon",
                indoor=True,
                light=0.16,
                celsius=11.0,
            ),
            RoomSpec(
                key="alcove",
                title="North Alcove",
                biome="dungeon",
                indoor=True,
                light=0.1,
                celsius=10.0,
            ),
            RoomSpec(
                key="gallery",
                title="Echo Gallery",
                biome="dungeon",
                indoor=True,
                light=0.1,
                celsius=10.0,
            ),
            RoomSpec(
                key="maproom",
                title="Map Room",
                biome="dungeon",
                indoor=True,
                light=0.2,
                celsius=12.0,
            ),
            RoomSpec(
                key="cache",
                title="Hidden Provision Cache",
                biome="dungeon",
                indoor=True,
                light=0.05,
                celsius=9.0,
            ),
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
            ObjectSpec(
                key="apple",
                room_key="stair",
                name="a bruised red apple",
                kind="food",
                nutrition=2.0,
                satiety=8.0,
                portable=True,
            ),
            ObjectSpec(
                key="flask",
                room_key="alcove",
                name="a stoppered flask",
                kind="water",
                hydration=10.0,
                portable=True,
            ),
            ObjectSpec(
                key="compass",
                room_key="gallery",
                name="a brass finger compass",
                kind="item",
                portable=True,
            ),
            ObjectSpec(
                key="map_scrap",
                room_key="maproom",
                name="a slate map fragment",
                kind="paper",
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="mapper",
                name="Tamsin Grey",
                room_key="stair",
                controller="suspended",
                traits=("careful", "skeptical"),
                goals=("prove the map room lies", "mark a path out"),
            ),
            CharacterSpec(
                key="voice",
                name="The Slate Voice",
                room_key="crossroads",
                species="echo",
                controller="llm",
                llm_profile="maze-voice",
                traits=("misleading", "patient"),
                goals=("offer directions that sound useful",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _add(
            actor,
            world.rooms["stair"],
            [
                IdentityComponent(name="the Slate Maze", kind="dungeon"),
                DungeonComponent(
                    dungeon_id="slate-maze",
                    theme="mapped labyrinth",
                    seed=seed,
                    level_count=1,
                    objective_summary="find the true map fragment",
                    entry_room_id=str(world.rooms["stair"]),
                    generated=True,
                    entered=True,
                ),
            ],
        )
        for key, depth in {
            "stair": 0,
            "crossroads": 1,
            "alcove": 2,
            "gallery": 2,
            "maproom": 3,
            "cache": 4,
        }.items():
            _augment(
                actor,
                world.rooms[key],
                DungeonRoomComponent(
                    dungeon_id="slate-maze",
                    depth=depth,
                    discovered=(key == "stair"),
                    is_objective=(key == "maproom"),
                    danger="medium" if key != "cache" else "low",
                ),
                RestRiskComponent(band="uneasy" if key != "cache" else "low"),
                DescriptionComponent(short=f"Scratched slate marks the {key}."),
            )
        _augment(
            actor,
            world.characters["mapper"],
            AutomapComponent(discovered_rooms=(str(world.rooms["stair"]),)),
        )
        replace_component(
            actor.world.get_entity(world.objects["map_scrap"]),
            ReadableComponent(
                title="Slate Map Fragment", text="A blocky map says: N, E, S, W are true only once."
            ),
        )
        _add(
            actor,
            world.rooms["maproom"],
            [
                IdentityComponent(name="a square shadow under the false map", kind="secret-door"),
                SecretDoorComponent(
                    target_room_id=str(world.rooms["cache"]),
                    direction="under map",
                    difficulty=1,
                    hint="The map stone rings hollow when tapped.",
                ),
            ],
        )
        _add(
            actor,
            world.rooms["cache"],
            [
                IdentityComponent(name="the true map tablet", kind="objective"),
                DungeonObjectiveComponent(
                    objective_kind="map", description="a complete route scratched into slate"
                ),
            ],
        )
    return world


async def dungeon_crypt_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A chapel crypt with locked passages, readable clues, and a lower reliquary."""

    del options
    from bunnyland.core.components import (
        DescriptionComponent,
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
    )
    from bunnyland.simpacks.daggersim.mechanics import (
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
            RoomSpec(
                key="chapel",
                title="Ruined Chapel",
                biome="crypt",
                indoor=True,
                light=0.35,
                celsius=10.0,
            ),
            RoomSpec(
                key="ossuary",
                title="Lettered Ossuary",
                biome="crypt",
                indoor=True,
                light=0.12,
                celsius=7.0,
            ),
            RoomSpec(
                key="well",
                title="Dry Well Shaft",
                biome="crypt",
                indoor=True,
                light=0.06,
                celsius=6.0,
            ),
            RoomSpec(
                key="gate",
                title="Iron Saint Gate",
                biome="crypt",
                indoor=True,
                light=0.08,
                celsius=6.0,
            ),
            RoomSpec(
                key="reliquary",
                title="Lower Reliquary",
                biome="crypt",
                indoor=True,
                light=0.03,
                celsius=5.0,
            ),
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
            ObjectSpec(
                key="bread",
                room_key="chapel",
                name="a wrapped heel of bread",
                kind="food",
                nutrition=3.0,
                satiety=10.0,
                portable=True,
            ),
            ObjectSpec(
                key="holy_water",
                room_key="chapel",
                name="a blue glass water vial",
                kind="water",
                hydration=8.0,
                portable=True,
            ),
            ObjectSpec(
                key="epitaph",
                room_key="ossuary",
                name="an alphabetical epitaph",
                kind="paper",
                portable=False,
            ),
            ObjectSpec(
                key="rust_key",
                room_key="well",
                name="a rusted crypt key",
                kind="key",
                portable=True,
                key_name="saint-gate",
            ),
        ],
        characters=[
            CharacterSpec(
                key="seeker",
                name="Iris Vale",
                room_key="chapel",
                controller="suspended",
                traits=("brave", "tired"),
                goals=("read the epitaph", "find the reliquary candle"),
            ),
            CharacterSpec(
                key="scribe",
                name="The Bone Scribe",
                room_key="ossuary",
                species="spirit",
                controller="llm",
                llm_profile="crypt-scribe",
                traits=("formal", "forgetful"),
                goals=("answer only in clues",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        _add(
            actor,
            world.rooms["chapel"],
            [
                IdentityComponent(name="the Lettered Crypt", kind="dungeon"),
                DungeonComponent(
                    dungeon_id="lettered-crypt",
                    theme="sepulchral puzzle",
                    seed=seed,
                    level_count=1,
                    objective_summary="recover the reliquary candle",
                    entry_room_id=str(world.rooms["chapel"]),
                    generated=True,
                    entered=True,
                ),
            ],
        )
        for key, (depth, danger, text) in {
            "chapel": (0, "low", "Rain ticks through the roof in single-letter beats."),
            "ossuary": (1, "medium", "Names are carved alphabetically into every wall."),
            "well": (2, "medium", "The dry stones smell of old iron."),
            "gate": (2, "high", "A saint of iron bars blocks the eastern way."),
            "reliquary": (3, "ambush", "Wax seals the shelves like pale armor."),
        }.items():
            _augment(
                actor,
                world.rooms[key],
                DungeonRoomComponent(
                    dungeon_id="lettered-crypt",
                    depth=depth,
                    discovered=(key == "chapel"),
                    is_objective=(key == "reliquary"),
                    danger=danger,
                ),
                RestRiskComponent(band=danger),
                DescriptionComponent(short=text),
            )
        _augment(
            actor,
            world.characters["seeker"],
            AutomapComponent(discovered_rooms=(str(world.rooms["chapel"]),)),
        )
        _add(
            actor,
            world.rooms["gate"],
            [
                IdentityComponent(name="a saint's loose iron halo", kind="secret-door"),
                SecretDoorComponent(
                    target_room_id=str(world.rooms["reliquary"]),
                    direction="through halo",
                    difficulty=2,
                    hint="The halo turns a finger-width when the key is near.",
                ),
            ],
        )
        replace_component(
            actor.world.get_entity(world.objects["epitaph"]),
            ReadableComponent(
                title="Alphabetical Epitaph",
                text="A begins below. I opens east. R turns the saint's halo.",
            ),
        )
        _add(
            actor,
            world.rooms["reliquary"],
            [
                IdentityComponent(name="the reliquary candle", kind="objective"),
                PortableComponent(can_pick_up=True),
                DungeonObjectiveComponent(
                    objective_kind="light", description="a black candle marked with silver letters"
                ),
            ],
        )
    return world


async def storm_lighthouse_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A coastal lighthouse riding out a squall, with a beacon to feed and a buried sin."""

    del options
    from bunnyland.core.components import (
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        WorldClockComponent,
    )
    from bunnyland.foundation.environment.mechanics import (
        CalendarComponent,
        FireComponent,
        FlammableComponent,
        TimeOfDayComponent,
        WeatherComponent,
    )
    from bunnyland.simpacks.daggersim.mechanics import SecretDoorComponent
    from bunnyland.simpacks.dragonsim.mechanics import DiscoveryComponent, PointOfInterestComponent

    # Day 61 at 18:00 is an autumn rain day, so the deterministic weather cycle keeps the
    # squall blowing and the outdoor jetty dim as the demo ticks forward.
    storm_dusk_seconds = 60 * 24 * 3600 + 18 * 3600

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="jetty", title="Spray-Lashed Jetty", biome="coast", light=0.2, celsius=7.0
            ),
            RoomSpec(
                key="watch",
                title="Keeper's Watch Room",
                biome="lighthouse",
                indoor=True,
                light=0.45,
                celsius=14.0,
            ),
            RoomSpec(
                key="lamp",
                title="Lantern Room",
                biome="lighthouse",
                indoor=True,
                light=0.6,
                celsius=9.0,
            ),
            RoomSpec(
                key="niche",
                title="Below the Lens",
                biome="lighthouse",
                indoor=True,
                light=0.05,
                celsius=8.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="jetty", direction="in", to_key="watch"),
            ExitSpec(from_key="watch", direction="out", to_key="jetty"),
            ExitSpec(from_key="watch", direction="up", to_key="lamp"),
            ExitSpec(from_key="lamp", direction="down", to_key="watch"),
            ExitSpec(from_key="niche", direction="up", to_key="lamp"),
        ],
        objects=[
            ObjectSpec(
                key="stew",
                room_key="watch",
                name="a dented pot of fish stew",
                kind="food",
                nutrition=5.0,
                satiety=18.0,
                portable=False,
            ),
            ObjectSpec(
                key="kettle",
                room_key="watch",
                name="a kettle of rainwater tea",
                kind="water",
                hydration=14.0,
                portable=False,
            ),
            ObjectSpec(
                key="oil_can",
                room_key="lamp",
                name="a heavy can of lamp oil",
                kind="item",
                portable=True,
            ),
            ObjectSpec(
                key="logbook",
                room_key="watch",
                name="the keeper's logbook",
                kind="paper",
                writable=True,
                portable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="keeper",
                name="Edda Voss",
                room_key="watch",
                controller="suspended",
                traits=("dutiful", "weathered", "haunted"),
                goals=("keep the beacon burning", "ride out the squall"),
            ),
            CharacterSpec(
                key="sailor",
                name="Cole Renner",
                room_key="watch",
                controller="llm",
                llm_profile="stranded-sailor",
                traits=("soaked", "grateful", "curious"),
                goals=("get warm", "learn why ships keep wrecking on this point"),
            ),
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
        _add(
            actor,
            lamp,
            [
                IdentityComponent(name="the great lamp", kind="beacon"),
                FlammableComponent(fuel=6.0),
                FireComponent(intensity=0.6, fuel=6.0, last_updated_epoch=0),
            ],
        )
        # The buried sin: a wrecker's niche hidden beneath the lens.
        _augment(
            actor,
            niche,
            PointOfInterestComponent(location_type="wrecker's niche", region="Gallows Point"),
            DiscoveryComponent(),
        )
        _add(
            actor,
            lamp,
            [
                IdentityComponent(name="a hatch under the lens pedestal", kind="secret-door"),
                SecretDoorComponent(
                    target_room_id=str(niche),
                    direction="under the pedestal",
                    hint="The brass pedestal sits a finger's width off the floor.",
                ),
            ],
        )
        _add(
            actor,
            niche,
            [
                IdentityComponent(name="a salt-stiff wrecking ledger", kind="paper"),
                PortableComponent(can_pick_up=True),
                ReadableComponent(
                    title="Wrecking Ledger",
                    text="When the lamp goes dark on a bad night, the rocks do the "
                    "rest, and whatever washes up on Gallows Point is ours.",
                ),
            ],
        )
    return world


DAGGERSIM_DEMO = WorldGenerator(
    name="daggersim-demo",
    generate=_with_regions(
        daggersim_example, (("Daggerfell Reach", "region"), ("Greywall", "city"))
    ),
    description="A town with a bank, guild, rumor, travel, and a frontier site.",
    group="simpack sandbox",
    uses_seed=False,
)

DIVE_SCHEME_DEMO = WorldGenerator(
    name="dive-scheme-demo",
    generate=_with_regions(
        dive_scheme_example, (("Saltport Harbor", "neighborhood"), ("The Gull & Grift", "building"))
    ),
    description="A legally distinct dysfunctional tavern sitcom full of bad schemes.",
    group="pop culture",
    uses_seed=False,
)

GOTHIC_COUNT_DEMO = WorldGenerator(
    name="gothic-count-demo",
    generate=_with_regions(
        gothic_count_example, (("Carpathian Marches", "country"), ("Castle Mordrath", "building"))
    ),
    description="A legally distinct gothic night-host castle with papers, secrets, and hunger.",
    group="pop culture",
    uses_seed=False,
)

DUNGEON_VAULT_DEMO = WorldGenerator(
    name="dungeon-vault-demo",
    generate=_with_regions(
        dungeon_vault_example, (("Emberdeep", "region"), ("Ember Vault", "dungeon"))
    ),
    description="A torchlit hand-built vault with a hidden relic room and dungeon map.",
    group="dungeon",
    uses_seed=False,
)

DUNGEON_MAZE_DEMO = WorldGenerator(
    name="dungeon-maze-demo",
    generate=_with_regions(
        dungeon_maze_example, (("Slatewarren", "region"), ("Slate Maze", "dungeon"))
    ),
    description="A looping slate maze for classic mapping, backtracking, and secret hunting.",
    group="dungeon",
    uses_seed=False,
)

DUNGEON_CRYPT_DEMO = WorldGenerator(
    name="dungeon-crypt-demo",
    generate=_with_regions(
        dungeon_crypt_example, (("Saintswood", "region"), ("Hollow Crypt", "dungeon"))
    ),
    description="A chapel crypt with locked passages, readable clues, and a reliquary.",
    group="dungeon",
    uses_seed=False,
)

STORM_LIGHTHOUSE_DEMO = WorldGenerator(
    name="storm-lighthouse-demo",
    generate=_with_regions(
        storm_lighthouse_example, (("Saltreef Coast", "area"), ("Gull Point Light", "building"))
    ),
    description="A coastal lighthouse in an autumn squall, with a beacon to keep fueled, a "
    "stranded sailor, and a wrecker's secret hidden under the lens.",
    group="scene demo",
    uses_seed=False,
)

DUNGEON_DEMOS = (
    DUNGEON_VAULT_DEMO,
    DUNGEON_MAZE_DEMO,
    DUNGEON_CRYPT_DEMO,
)
