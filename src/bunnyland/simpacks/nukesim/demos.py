"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.worldgen.demo_support import _add, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, RoomSpec, WorldProposal


async def nukesim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import IdentityComponent, PortableComponent
    from bunnyland.simpacks.colonysim.mechanics import RecipeComponent, WorkstationComponent
    from bunnyland.simpacks.nukesim.mechanics import (
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
            RoomSpec(
                key="checkpoint",
                title="Rustwater Checkpoint",
                biome="wasteland",
                light=0.8,
                celsius=29.0,
            ),
            RoomSpec(
                key="ruin",
                title="Glow-Marked Pharmacy",
                biome="ruin",
                indoor=True,
                light=0.2,
                celsius=31.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="checkpoint", direction="east", to_key="ruin"),
            ExitSpec(from_key="ruin", direction="west", to_key="checkpoint"),
        ],
        characters=[
            CharacterSpec(
                key="scavenger",
                name="Mara",
                room_key="checkpoint",
                controller="suspended",
                traits=("cautious",),
                goals=("bring back clean scrap",),
            ),
            CharacterSpec(
                key="mechanic",
                name="Patch",
                room_key="checkpoint",
                controller="llm",
                llm_profile="wasteland mechanic",
                goals=("keep the checkpoint supplied",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        checkpoint, ruin = world.rooms["checkpoint"], world.rooms["ruin"]
        _add(
            actor,
            checkpoint,
            [
                IdentityComponent(name="a decon arch", kind="decontamination"),
                DecontaminationComponent(
                    dose_reduction=5.0,
                    sickness_reduction=2.0,
                    mutation_pressure_reduction=3.0,
                    uses=3,
                ),
            ],
        )
        _add(
            actor,
            checkpoint,
            [
                IdentityComponent(name="a field workbench", kind="workstation"),
                WorkstationComponent(station_type="workbench"),
            ],
        )
        _add(
            actor,
            checkpoint,
            [
                IdentityComponent(name="pipe filter recipe", kind="recipe"),
                RecipeComponent(
                    recipe_id="pipe-filter",
                    inputs={"scrap": 2, "cloth": 1},
                    outputs={"pipe-filter": 1},
                    required_station="workbench",
                ),
            ],
        )
        _add(
            actor,
            checkpoint,
            [
                IdentityComponent(name="a patched rad poncho", kind="armor"),
                PortableComponent(can_pick_up=True),
                RadProtectionComponent(rating=0.35),
            ],
        )
        _add(
            actor,
            checkpoint,
            [
                IdentityComponent(name="a packet of rad-away", kind="medicine"),
                PortableComponent(can_pick_up=True),
                RadMedicineComponent(
                    dose_reduction=4.0,
                    sickness_reduction=2.0,
                    mutation_pressure_reduction=2.0,
                ),
            ],
        )
        _add(
            actor,
            ruin,
            [
                IdentityComponent(name="a cracked isotope case", kind="radiation-source"),
                RadiationSourceComponent(
                    source_type="cracked isotope case",
                    rads_per_hour=4.0,
                    mutation_pressure_per_rad=1.0,
                    sickness_per_rad=0.5,
                ),
            ],
        )
        _add(
            actor,
            ruin,
            [
                IdentityComponent(name="a pharmacy backroom cache", kind="scavenge-site"),
                ScavengeSiteComponent(site_type="pre-war pharmacy", charges=2, hazard_rads=2.0),
                LootTableComponent(outputs={"scrap": 2, "cloth": 1, "chemicals": 1}),
            ],
        )
        _add(
            actor,
            ruin,
            [
                IdentityComponent(name="a bent pressure cooker", kind="junk"),
                PortableComponent(can_pick_up=True),
                JunkComponent(outputs={"scrap": 2}, contaminated_rads=1.0),
            ],
        )
    return world


NUKESIM_DEMO = WorldGenerator(
    name="nukesim-demo",
    generate=_with_regions(
        nukesim_example, (("The Glowlands", "region"), ("Rustwater Flats", "area"))
    ),
    description="A wasteland checkpoint with radiation, scavenging, decon, and scrap crafting.",
    group="simpack sandbox",
    uses_seed=False,
)
