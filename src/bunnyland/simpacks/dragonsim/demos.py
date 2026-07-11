"""Hand-built demo worlds owned by this simpack."""

from __future__ import annotations

from bunnyland.core.components import (
    IdentityComponent,
)
from bunnyland.core.ecs import spawn_entity
from bunnyland.worldgen.demo_support import _add, _augment, _with_regions
from bunnyland.worldgen.generators import GenOptions, WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld, instantiate
from bunnyland.worldgen.proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


def add_demo_quest(actor, room_id, quest_id, title, objective, reward=None):
    from bunnyland.simpacks.dragonsim.mechanics import (
        QuestComponent,
        QuestHasObjective,
        QuestHasReward,
        QuestObjectiveComponent,
        QuestRewardComponent,
        QuestStateComponent,
    )

    quest = _add(
        actor,
        room_id,
        [
            IdentityComponent(name=title, kind="quest"),
            QuestComponent(quest_id=quest_id, title=title, description=objective),
            QuestStateComponent(),
        ],
    )
    objective_entity = spawn_entity(actor.world, [QuestObjectiveComponent(description=objective)])
    quest.add_relationship(QuestHasObjective(), objective_entity.id)
    if reward is not None:
        reward_entity = spawn_entity(actor.world, [QuestRewardComponent(description=reward)])
        quest.add_relationship(QuestHasReward(), reward_entity.id)
    return quest


async def dragonsim_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from bunnyland.core.components import IdentityComponent
    from bunnyland.simpacks.dragonsim.mechanics import (
        DiscoveryComponent,
        FactionComponent,
        FactionReputationComponent,
        PointOfInterestComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="village", title="Mistmoor Village", biome="highland", light=0.7, celsius=12.0
            ),
            RoomSpec(
                key="ruin", title="Sunken Barrow", biome="ruin", indoor=True, light=0.1, celsius=6.0
            ),
        ],
        exits=[
            ExitSpec(from_key="village", direction="east", to_key="ruin"),
            ExitSpec(from_key="ruin", direction="west", to_key="village"),
        ],
        characters=[
            CharacterSpec(
                key="aldric",
                name="Aldric",
                room_key="village",
                controller="suspended",
                traits=("bold",),
                goals=("explore the barrow",),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        village, ruin = world.rooms["village"], world.rooms["ruin"]
        _augment(
            actor,
            ruin,
            PointOfInterestComponent(location_type="barrow", region="Mistmoor"),
            DiscoveryComponent(),
        )
        _add(
            actor,
            village,
            [
                IdentityComponent(name="the Moss Wardens", kind="faction"),
                FactionComponent(name="Moss Wardens", ideology="guard the old marsh"),
            ],
        )
        add_demo_quest(
            actor,
            village,
            "barrow",
            "Clear the Barrow",
            "Reach the inner sanctum",
            "an ancient relic",
        )
        _augment(
            actor,
            world.characters["aldric"],
            FactionReputationComponent(scores={"Moss Wardens": 5}),
        )
    return world


async def clue_snack_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    """A comic mystery demo with a nervous snack-lover and a talking sleuth-hound."""

    del options
    from bunnyland.core.components import IdentityComponent, PortableComponent, ReadableComponent
    from bunnyland.simpacks.dragonsim.mechanics import (
        DiscoveryComponent,
        PointOfInterestComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            RoomSpec(
                key="snack_van",
                title="Snack Van Pull-Off",
                biome="roadside",
                light=0.5,
                celsius=16.0,
            ),
            RoomSpec(
                key="lodge",
                title="Creaky Mascot Lodge",
                biome="lodge",
                indoor=True,
                light=0.25,
                celsius=13.0,
            ),
            RoomSpec(
                key="cellar",
                title="Stage-Trick Cellar",
                biome="cellar",
                indoor=True,
                light=0.1,
                celsius=11.0,
            ),
        ],
        exits=[
            ExitSpec(from_key="snack_van", direction="in", to_key="lodge"),
            ExitSpec(from_key="lodge", direction="out", to_key="snack_van"),
            ExitSpec(from_key="lodge", direction="down", to_key="cellar"),
            ExitSpec(from_key="cellar", direction="up", to_key="lodge"),
        ],
        objects=[
            ObjectSpec(
                key="sandwiches",
                room_key="snack_van",
                name="a hamper of tower sandwiches",
                kind="food",
                nutrition=5.0,
                satiety=22.0,
                portable=True,
            ),
            ObjectSpec(
                key="water_jug",
                room_key="snack_van",
                name="a sloshing water jug",
                kind="water",
                hydration=18.0,
                portable=True,
                renewable=False,
            ),
            ObjectSpec(
                key="mask",
                room_key="cellar",
                name="a rubber fog-beast mask",
                kind="item",
                portable=True,
            ),
            ObjectSpec(
                key="projector",
                room_key="cellar",
                name="a rattling shadow projector",
                kind="item",
                portable=False,
            ),
        ],
        characters=[
            CharacterSpec(
                key="munch",
                name="Jory Munch",
                room_key="snack_van",
                controller="suspended",
                traits=("nervous", "hungry", "loyal"),
                goals=("find the hidden snack stash", "avoid being volunteered"),
            ),
            CharacterSpec(
                key="hound",
                name="Biscuit",
                room_key="snack_van",
                species="dog",
                controller="llm",
                llm_profile="comic-hound",
                traits=("talkative", "brave-when-fed"),
                goals=("sniff out the prankster", "protect Jory's lunch"),
            ),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        cellar = world.rooms["cellar"]
        _augment(
            actor,
            cellar,
            PointOfInterestComponent(location_type="stage trick", region="Fogbank Pier"),
            DiscoveryComponent(),
        )
        add_demo_quest(
            actor,
            world.rooms["lodge"],
            "fog-prank",
            "Unmask the Fog Prank",
            "Find the stage equipment under the lodge",
            "a heroic share of the sandwich hamper",
        )
        actor.world.get_entity(world.objects["projector"]).add_component(
            ReadableComponent(
                title="Projector Label",
                text="Property of Pier Promotions. Do not use to frighten guests after hours.",
            )
        )
        _add(
            actor,
            world.rooms["lodge"],
            [
                IdentityComponent(name="a squeaky clue notebook", kind="paper"),
                PortableComponent(can_pick_up=True),
                ReadableComponent(
                    title="Clue Notebook",
                    text="Someone ordered extra fog, extra chains, and no witnesses.",
                ),
            ],
        )
    return world


DRAGONSIM_DEMO = WorldGenerator(
    name="dragonsim-demo",
    generate=_with_regions(
        dragonsim_example, (("Mistmoor Vale", "region"), ("Mistmoor Village", "neighborhood"))
    ),
    description="A village with an undiscovered barrow, a faction, and a quest.",
    group="simpack sandbox",
    uses_seed=False,
)

CLUE_SNACK_DEMO = WorldGenerator(
    name="clue-snack-demo",
    generate=_with_regions(
        clue_snack_example, (("Pinecrest", "area"), ("Mascot Lodge", "building"))
    ),
    description=(
        "A legally distinct comic mystery with snacks, a talking hound, and a fake haunting."
    ),
    group="pop culture",
    uses_seed=False,
)
