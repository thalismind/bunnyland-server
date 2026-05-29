"""bunnyland gameplay mechanics (lifesim and beyond).

Each mechanic is self-contained: its own components, systems, commands, events, and
handlers (spec 9.4). These are wired into the world actor today and are structured to
move into plugins (spec 21) without changing their internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .affect import install_affect
from .eat_drink import DrinkHandler, EatHandler
from .needs import HungerSystem, ThirstSystem

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


def install_needs(actor: WorldActor) -> None:
    """Register the hunger/thirst systems and the eat/drink handlers on an actor.

    A preview of the plugin-contribution shape (spec 21.2): systems run in the passive
    simulation phase; handlers expose the eat/drink verbs.
    """
    actor.world.register_system(HungerSystem())
    actor.world.register_system(ThirstSystem())
    actor.register_handler(EatHandler())
    actor.register_handler(DrinkHandler())


__all__ = ["install_affect", "install_needs"]
