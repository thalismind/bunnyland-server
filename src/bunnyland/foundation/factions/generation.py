"""Declarative generation for shared faction identity and standing."""

from ...core.generation import GenerationDelta, GenerationEdge, GenerationRequest, GenerationTarget
from ...worldgen.enrichment import GenerationContext, generation_mentions, generation_wants
from .mechanics import FactionComponent, HasStandingWithFaction

CAPABILITIES = (
    "bunnyland.factions.faction",
    "bunnyland.factions.standing",
)
SUPPORTED_CAPABILITIES = (
    *CAPABILITIES,
    # These remain declared by Dragonsim for namespace compatibility, while the
    # foundation enricher produces their now-foundation-owned ECS values.
    "bunnyland.dragonsim.faction",
    "bunnyland.dragonsim.faction-reputation",
)


class FactionGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        context = GenerationContext.from_request(request)
        components = []
        edges = []
        if context.is_character:
            if generation_wants(
                context,
                "bunnyland.factions.standing",
                "bunnyland.dragonsim.faction-reputation",
            ):
                faction_id = request.context.get("faction_id")
                if faction_id:
                    edges.append(
                        GenerationEdge(
                            HasStandingWithFaction(), GenerationTarget(str(faction_id))
                        )
                    )
        elif generation_wants(
            context,
            "bunnyland.factions.faction",
            "bunnyland.dragonsim.faction",
        ) or generation_mentions(context, "faction", "guild", "clan"):
            components.append(FactionComponent(name=context.name))

        return GenerationDelta(
            components=tuple(components),
            edges=tuple(edges),
            satisfies=tuple(
                capability
                for capability in request.capabilities
                if capability in SUPPORTED_CAPABILITIES
            ),
        )


GENERATION_ENRICHER = FactionGenerationEnricher()

__all__ = [
    "CAPABILITIES",
    "SUPPORTED_CAPABILITIES",
    "FactionGenerationEnricher",
    "GENERATION_ENRICHER",
]
