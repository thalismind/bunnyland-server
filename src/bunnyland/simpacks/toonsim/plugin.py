"""Canonical Toon Sim plugin entrypoint."""

from ...mechanics.toonsim import (
    MoveSpriteHandler,
    PlacedOn,
    SpriteBoundsComponent,
    SpriteImageComponent,
    SpriteLayerComponent,
    SpriteMovedEvent,
    SpritePositionComponent,
    SpriteScaleComponent,
    ToonRoomComponent,
    install_toonsim,
)
from ...plugins.ids import TOONSIM
from ...plugins.model import (
    CommandContribution,
    ContentContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)
from .actions import ACTION_DEFINITIONS
from .generation import (
    ALIASES,
    CAPABILITIES,
    GENERATION_ENRICHER,
    ToonPlacementWorldgenHook,
)


def _definition() -> Plugin:
    return Plugin(
        id=TOONSIM,
        name="Toon Sim",
        ecs=EcsContribution(
            components=(
                SpritePositionComponent,
                SpriteImageComponent,
                SpriteLayerComponent,
                SpriteScaleComponent,
                SpriteBoundsComponent,
                ToonRoomComponent,
            ),
            edges=(PlacedOn,),
        ),
        commands=CommandContribution(
            action_definitions=ACTION_DEFINITIONS,
            action_handlers=(MoveSpriteHandler,),
            typed_events=(SpriteMovedEvent,),
        ),
        runtime=RuntimeContribution(service_factories=(install_toonsim,)),
        content=ContentContribution(
            generation_capabilities=CAPABILITIES,
            generation_aliases=ALIASES,
            generation_enrichers=(GENERATION_ENRICHER,),
            worldgen_hooks=(ToonPlacementWorldgenHook,),
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.OUTER})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
