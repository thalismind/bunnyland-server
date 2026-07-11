"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, RoomSpec, WorldProposal


async def barbariansim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import IdentityComponent, PortableComponent
    from bunnyland.simpacks.barbariansim.mechanics import (
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
            RoomSpec(key="ridge", title="Frozen Ridge", biome="tundra", light=0.7, celsius=-12.0),
            RoomSpec(
                key="cave",
                title="Sheltered Cave",
                biome="tundra",
                indoor=True,
                light=0.2,
                celsius=4.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="ridge", direction="in", to_key="cave"),
            ExitSpec(from_key="cave", direction="out", to_key="ridge"),
        ],
        characters=[
            CharacterSpec(
                key="kell",
                name="Kell",
                room_key="cave",
                controller="suspended",
                traits=("hardy", "grim"),
                goals=("survive the cold",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        ridge, cave = world.rooms["ridge"], world.rooms["cave"]
        _augment(actor, cave, ShelterComponent(temperature_buffer=12.0))
        _augment(
            actor,
            world.characters["kell"],
            StaminaComponent(current=8.0, maximum=10.0),
            CorruptionComponent(amount=3.0),
            TemperatureResistanceComponent(cold=0.25),
        )
        _add(
            actor,
            cave,
            [
                IdentityComponent(name="a bone axe", kind="weapon"),
                PortableComponent(can_pick_up=True),
                WeaponComponent(damage=7.0, damage_type="slashing", lethal_capable=True),
                DurabilityComponent(current=38.0, maximum=50.0),
            ],
        )
        _add(
            actor,
            ridge,
            [
                IdentityComponent(name="a hide jerkin", kind="armor"),
                PortableComponent(can_pick_up=True),
                ArmorComponent(rating=3.0),
                DurabilityComponent(current=44.0, maximum=50.0),
            ],
        )
    return world


BARBARIANSIM_DEMO = WorldGenerator(
    name="barbariansim-demo",
    generate=_with_regions(
        barbariansim_example, (("Frostfang Reaches", "region"), ("Wolfwind Pass", "zone"))
    ),
    description="A frozen ridge with a sheltered cave, gear, and corruption pressure.",
    group="simpack sandbox",
    uses_seed=False,
)
