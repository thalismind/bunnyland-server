"""Canonical Checkpoints plugin entrypoint."""

from ...mechanics.checkpoints import (
    CheckpointReloadedEvent,
    CheckpointReloadRequestedEvent,
    CheckpointSavedEvent,
    SaveCheckpointComponent,
    checkpoint_action_definitions,
    install_checkpoints,
)
from ...plugins.ids import (
    CHECKPOINTS,
    CORE_VERBS,
)
from ...plugins.model import (
    CommandContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)


def _definition() -> Plugin:
    return Plugin(
        id=CHECKPOINTS,
        name="Checkpoints",
        default_enabled=False,
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(components=(SaveCheckpointComponent,)),
        commands=CommandContribution(
            action_definitions=checkpoint_action_definitions(),
            typed_events=(
                CheckpointSavedEvent,
                CheckpointReloadRequestedEvent,
                CheckpointReloadedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(install_checkpoints,)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
