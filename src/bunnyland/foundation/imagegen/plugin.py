"""Canonical Imagegen plugin entrypoint."""

from ...imagegen.components import (
    EventImageComponent,
    ImageRequestComponent,
    PortraitImageComponent,
)
from ...imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
)
from ...plugins.ids import IMAGEGEN
from ...plugins.model import (
    CommandContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
)


def _definition() -> Plugin:
    return Plugin(
        id=IMAGEGEN,
        name="Image Generation",
        ecs=EcsContribution(
            components=(
                PortraitImageComponent,
                EventImageComponent,
                ImageRequestComponent,
            ),
        ),
        commands=CommandContribution(
            typed_events=(
                ImageGenerationStartedEvent,
                ImageGenerationCompletedEvent,
                ImageGenerationFailedEvent,
            ),
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
