"""Canonical History plugin entrypoint."""

from bunnyland.foundation.history.mechanics import (
    CreatedBy,
    CreatorSignatureComponent,
    DeathConsequenceComponent,
    DeathOf,
    DeedReputationComponent,
    HistoryActor,
    HistoryTarget,
    MarkOn,
    PhysicalMarkComponent,
    WorldHistoryRecordComponent,
    creator_fragments,
    death_consequence_fragments,
    deed_reputation_fragments,
    history_fragments,
    install_history,
    mark_fragments,
)

from ...plugins.ids import (
    CORE_VERBS,
    HISTORY,
)
from ...plugins.model import (
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)


def _history_factory(actor) -> None:
    install_history(actor)


def _definition() -> Plugin:
    return Plugin(
        id=HISTORY,
        name="World History",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                CreatorSignatureComponent,
                DeathConsequenceComponent,
                DeedReputationComponent,
                PhysicalMarkComponent,
                WorldHistoryRecordComponent,
            ),
            edges=(CreatedBy, DeathOf, HistoryActor, HistoryTarget, MarkOn),
        ),
        runtime=RuntimeContribution(service_factories=(_history_factory,)),
        content=ContentContribution(
            prompt_fragments=(
                creator_fragments,
                death_consequence_fragments,
                deed_reputation_fragments,
                history_fragments,
                mark_fragments,
            )
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
