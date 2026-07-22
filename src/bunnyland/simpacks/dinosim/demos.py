"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


async def dinosim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import (
        ActionOverrideComponent,
        ActionOverrideEntry,
        IdentityComponent,
        PortableComponent,
    )
    from bunnyland.simpacks.dinosim.mechanics import (
        BoneComponent,
        CreatureMilkComponent,
        CreatureProductComponent,
        DinosaurComponent,
        EggComponent,
        EnclosureComponent,
        FeedingPenComponent,
        FeedStoreComponent,
        FenceComponent,
        FertilityComponent,
        FossilFragmentComponent,
        GateComponent,
        HideComponent,
        IncubationComponent,
        ReptileProcreationComponent,
        SpeciesComponent,
        ToxinComponent,
        TranquilizerComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="lab",
                title="Amber Hatchery Lab",
                biome="field-lab",
                indoor=True,
                light=0.65,
                celsius=24.0,
            ),
            RoomSpec(
                key="paddock",
                title="Fern Paddock",
                biome="paddock",
                light=0.9,
                celsius=27.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="lab", direction="out", to_key="paddock"),
            ExitSpec(from_key="paddock", direction="in", to_key="lab"),
        ],
        objects=[
            ObjectSpec(
                key="ration",
                room_key="lab",
                name="a basket of fern cakes",
                kind="food",
                nutrition=4.0,
                satiety=18.0,
                portable=True,
            ),
            ObjectSpec(
                key="water",
                room_key="paddock",
                name="a clear trough",
                kind="water",
                hydration=20.0,
                portable=False,
                renewable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="keeper",
                name="Mira",
                room_key="lab",
                controller="suspended",
                traits=("careful", "curious"),
                goals=("hatch the prepared egg", "catalogue the amber shard"),
            ),
            CharacterSpec(
                key="raptor",
                name="Clever Raptor",
                room_key="paddock",
                species="velociraptor",
                controller="llm",
                llm_profile="alert hatchery creature",
                traits=("watchful", "fast"),
                goals=("guard the paddock", "inspect new hatchlings"),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        lab = world.rooms["lab"]
        paddock = world.rooms["paddock"]
        raptor = world.characters["raptor"]
        _augment(
            actor,
            paddock,
            EnclosureComponent(name="Fern Paddock", capacity=3),
            FenceComponent(integrity=8.0, maximum=10.0),
            GateComponent(open=False, locked=True),
            FeedingPenComponent(feed=5.0),
            FeedStoreComponent(feed=5.0, capacity=12.0),
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="an amber bone shard", kind="fossil"),
                PortableComponent(can_pick_up=True),
                FossilFragmentComponent(sample_quality=0.85),
            ],
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="a warm velociraptor egg", kind="egg"),
                PortableComponent(can_pick_up=True),
                EggComponent(
                    species_name="velociraptor",
                    laid_at_epoch=0,
                    fertilized=True,
                    source="clone",
                ),
                IncubationComponent(
                    started_at_epoch=0,
                    required_seconds=60,
                    progress_seconds=60,
                    last_updated_epoch=0,
                    ready=True,
                ),
                ActionOverrideComponent(
                    (
                        ActionOverrideEntry(
                            "take",
                            destination_action="collect-egg",
                            destination_argument="egg_id",
                        ),
                    )
                ),
            ],
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="scented bait", kind="food"),
                PortableComponent(can_pick_up=True),
            ],
        )
        _add(
            actor,
            lab,
            [
                IdentityComponent(name="sleep dart", kind="tool"),
                PortableComponent(can_pick_up=True),
                TranquilizerComponent(potency=1.0, uses=1),
            ],
        )
        _augment(
            actor,
            raptor,
            DinosaurComponent(species_name="velociraptor"),
            SpeciesComponent(
                common_name="velociraptor",
                scientific_name="Velociraptor mongoliensis",
                diet="carnivore",
                size_class="small",
            ),
            FertilityComponent(fertile=True),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
            CreatureMilkComponent(volume=1.0, maximum=1.0),
            ToxinComponent(potency=1.0, quantity=1.0, maximum=1.0),
            HideComponent(quality=1.0),
            BoneComponent(quality=1.0),
            CreatureProductComponent(
                product_type="fertilizer",
                quantity=2.0,
                renewable=True,
            ),
        )
    return world


DINOSIM_DEMO = WorldGenerator(
    name="dinosim-demo",
    generate=_with_regions(
        dinosim_example, (("Isla Vega", "region"), ("Cretaceous Compound", "zone"))
    ),
    description="A hatchery with fossils, a ready egg, and a fertile dinosaur parent.",
    group="simpack sandbox",
    uses_seed=False,
)
