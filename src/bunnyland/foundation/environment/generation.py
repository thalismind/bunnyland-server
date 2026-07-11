"""Declarative environment generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import GenerationContext, generation_mentions, generation_wants
from .mechanics import (
    FireComponent,
    FlammableComponent,
)

CAPABILITIES = (
    "bunnyland.environment.burning",
    "bunnyland.environment.fire",
    "bunnyland.environment.flammable",
    "bunnyland.environment.fuel",
)

ALIASES = {
    "burning": "bunnyland.environment.burning",
    "fire": "bunnyland.environment.fire",
    "flammable": "bunnyland.environment.flammable",
    "fuel": "bunnyland.environment.fuel",
}


class EnvironmentGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if not ctx.is_character:
            if generation_wants(ctx, "flammable", "fuel") or generation_mentions(
                ctx, "wood", "paper", "cloth", "grass", "forest", "brush", "fuel"
            ):
                add(FlammableComponent(fuel=8.0))
            if generation_wants(ctx, "fire", "burning"):
                add(FireComponent(last_updated_epoch=ctx.world_epoch))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = EnvironmentGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "EnvironmentGenerationEnricher"]
