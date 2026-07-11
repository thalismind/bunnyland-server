"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.core.ecs import spawn_entity
from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, RoomSpec, WorldProposal


async def colonysim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import IdentityComponent, PortableComponent
    from bunnyland.simpacks.colonysim.mechanics import (
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
            RoomSpec(
                key="store", title="Storeroom", biome="forest", indoor=True, light=0.4, celsius=15.0
            ),
        ],
        exits=[
            ExitSpec(from_key="camp", direction="in", to_key="store"),
            ExitSpec(from_key="store", direction="out", to_key="camp"),
        ],
        characters=[
            CharacterSpec(
                key="rowan",
                name="Rowan",
                room_key="camp",
                controller="suspended",
                traits=("industrious",),
            ),
            CharacterSpec(
                key="fern",
                name="Fern",
                room_key="camp",
                controller="llm",
                llm_profile="worker",
                goals=("stock the storeroom",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        camp, store = world.rooms["camp"], world.rooms["store"]
        rowan, fern = world.characters["rowan"], world.characters["fern"]
        _augment(
            actor,
            rowan,
            PawnProfileComponent(
                backstory="field builder",
                passions={"construction": 2, "plants": 1},
                expectations="modest",
            ),
        )
        _augment(actor, fern, PrisonerComponent(recruitment_difficulty=8.0, policy="recruit"))
        left_arm = spawn_entity(
            actor.world,
            [
                IdentityComponent(name="Rowan's left arm", kind="body-part"),
                BodyPartHealthComponent(part="left arm", health=0.65),
            ],
        )
        actor.world.get_entity(rowan).add_relationship(HasBodyPart(), left_arm.id)
        _add(
            actor,
            camp,
            [
                IdentityComponent(name="a berry bush", kind="resource-node"),
                ResourceNodeComponent(
                    resource_type="berries", current=20, maximum=20, regen_per_day=6.0
                ),
            ],
        )
        _add(
            actor,
            camp,
            [
                IdentityComponent(name="a carpentry bench", kind="workstation"),
                WorkstationComponent(station_type="workbench"),
            ],
        )
        _add(
            actor,
            camp,
            [
                IdentityComponent(name="plank recipe", kind="recipe"),
                RecipeComponent(
                    recipe_id="plank",
                    inputs={"wood": 2},
                    outputs={"plank": 1},
                    required_station="workbench",
                ),
            ],
        )
        _add(
            actor,
            store,
            [
                IdentityComponent(name="a wood stockpile", kind="stockpile"),
                StockpileComponent(capacity=24),
                StorageFilterComponent(allowed_types=("wood", "plank")),
            ],
        )
        _add(
            actor,
            store,
            [
                IdentityComponent(name="a stack of logs", kind="resource"),
                PortableComponent(can_pick_up=True),
                ResourceStackComponent(resource_type="wood", quantity=8),
            ],
        )
        _add(
            actor,
            store,
            [
                IdentityComponent(name="hauling job", kind="job"),
                JobComponent(job_type="haul", priority=3),
                JobBillComponent(recipe_id="plank", work_required=6.0, work_done=2.0),
            ],
        )
        _add(
            actor,
            camp,
            [
                IdentityComponent(name="treehouse research notes", kind="research"),
                ResearchProjectComponent(project_id="treehouse", work_required=20.0, work_done=5.0),
            ],
        )
        _add(
            actor,
            camp,
            [
                IdentityComponent(name="wandering trader offer", kind="trade-offer"),
                TradeOfferComponent(
                    faction_id="pine-traders",
                    gives={"medicine": 1},
                    wants={"wood": 4},
                    goodwill_delta=1.0,
                ),
            ],
        )
        _add(
            actor,
            camp,
            [
                IdentityComponent(name="minor crop blight incident", kind="incident"),
                ColonyIncidentComponent(incident_type="crop blight", severity=1),
            ],
        )
        _add(
            actor,
            camp,
            [
                IdentityComponent(name="install splint surgery", kind="surgery"),
                SurgeryBillComponent(part="left arm", operation="splint", work_required=4.0),
            ],
        )
    return world


COLONYSIM_DEMO = WorldGenerator(
    name="colonysim-demo",
    generate=_with_regions(
        colonysim_example, (("Verdant Frontier", "region"), ("Camp Theta", "zone"))
    ),
    description="A work camp with resources, a workstation, a recipe, and a job.",
    group="simpack sandbox",
    uses_seed=False,
)
