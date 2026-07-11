"""Canonical Worldgen plugin entrypoint."""

from bunnyland.foundation.tutorial.mechanics import (
    HungryCourierControllerComponent,
    install_tutorial,
)

from ...plugins.ids import WORLDGEN
from ...plugins.model import (
    ContentContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)
from ...worldgen.examples import APPLE_CROSSING_DEMO, BELL_GREEN_DEMO, CLOVER_CITY_DEMO
from ...worldgen.generators import (
    WorldGenerator,
    empty_generator,
    halloween_generator,
    holiday_generator,
    oneshot_generator,
    recursive_generator,
    tower_debate_generator,
    waiting_room_generator,
)


def _definition() -> Plugin:
    return Plugin(
        id=WORLDGEN,
        name="World Generators",
        ecs=EcsContribution(components=(HungryCourierControllerComponent,)),
        runtime=RuntimeContribution(service_factories=(install_tutorial,)),
        content=ContentContribution(
            world_generators=(
                WorldGenerator(
                    "empty",
                    empty_generator,
                    "Blank ECS world with only the world clock.",
                    group="administrative",
                    uses_seed=False,
                ),
                WorldGenerator(
                    "waiting-room",
                    waiting_room_generator,
                    "A single stark white room with one red chair.",
                    group="scene demo",
                    uses_seed=False,
                ),
                WorldGenerator(
                    "halloween",
                    halloween_generator,
                    "A haunted autumn porch, foyer, and cellar with seasonal props.",
                    group="seasonal",
                    uses_seed=False,
                ),
                WorldGenerator(
                    "holiday",
                    holiday_generator,
                    "A snowy holiday workshop, stable, and field with festive props.",
                    group="seasonal",
                    uses_seed=False,
                ),
                WorldGenerator(
                    "tower-debate",
                    tower_debate_generator,
                    "A locked tower room where an angel and devil debate forever.",
                    group="scene demo",
                    uses_seed=False,
                ),
                APPLE_CROSSING_DEMO,
                BELL_GREEN_DEMO,
                CLOVER_CITY_DEMO,
                WorldGenerator(
                    "oneshot",
                    oneshot_generator,
                    "Single LLM proposal, instantiated at once.",
                    group="algorithmic",
                ),
                WorldGenerator(
                    "recursive",
                    recursive_generator,
                    "Breadth-first graph, grown room-by-room.",
                    group="algorithmic",
                ),
            )
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
