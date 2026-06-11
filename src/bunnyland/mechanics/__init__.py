"""bunnyland gameplay mechanics (lifesim and beyond).

Each mechanic is self-contained: its own components, systems, commands, events, and
handlers (spec 9.4). These are wired into the world actor today and are structured to
move into plugins (spec 21) without changing their internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .affect import install_affect
from .eat_drink import DrinkHandler, EatHandler
from .environment import install_environment
from .mechanisms import install_mechanisms
from .needs import (
    BatheHandler,
    CleanSelfHandler,
    ComfortNeedSystem,
    FatigueSystem,
    FunNeedSystem,
    HungerSystem,
    HygieneSystem,
    PlayHandler,
    PrivacyNeedSystem,
    RelaxHandler,
    SafetyNeedSystem,
    SeekPrivacyHandler,
    SeekSafetyHandler,
    SocialNeedSystem,
    ThirstSystem,
)
from .policy import install_policy
from .social import install_social

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


def install_needs(actor: WorldActor) -> None:
    """Register the hunger/thirst systems and the eat/drink handlers on an actor.

    A preview of the plugin-contribution shape (spec 21.2): systems run in the passive
    simulation phase; handlers expose the eat/drink verbs.
    """
    actor.world.register_system(HungerSystem())
    actor.world.register_system(ThirstSystem())
    actor.world.register_system(FatigueSystem())
    actor.world.register_system(HygieneSystem())
    actor.world.register_system(ComfortNeedSystem())
    actor.world.register_system(FunNeedSystem())
    actor.world.register_system(SocialNeedSystem())
    actor.world.register_system(PrivacyNeedSystem())
    actor.world.register_system(SafetyNeedSystem())
    actor.register_handler(EatHandler())
    actor.register_handler(DrinkHandler())
    actor.register_handler(BatheHandler())
    actor.register_handler(CleanSelfHandler())
    actor.register_handler(PlayHandler())
    actor.register_handler(RelaxHandler())
    actor.register_handler(SeekPrivacyHandler())
    actor.register_handler(SeekSafetyHandler())


__all__ = [
    "install_affect",
    "install_environment",
    "install_mechanisms",
    "install_needs",
    "install_policy",
    "install_social",
]
