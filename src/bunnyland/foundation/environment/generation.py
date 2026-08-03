"""Declarative environment generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import GenerationContext, generation_mentions, generation_wants
from .mechanics import (
    FireComponent,
    FlammableComponent,
    MoistureComponent,
    ShelterComponent,
)

CAPABILITIES = (
    "bunnyland.environment.burning",
    "bunnyland.environment.fire",
    "bunnyland.environment.flammable",
    "bunnyland.environment.fuel",
    "bunnyland.environment.moisture",
    "bunnyland.environment.shelter",
)


class EnvironmentGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if not ctx.is_character:
            if ctx.is_room and (
                generation_wants(ctx, "bunnyland.environment.shelter")
                or generation_mentions(ctx, "shelter", "camp")
            ):
                add(
                    ShelterComponent(
                        temperature_buffer=10.0,
                        rain_protection=1.0,
                        wind_protection=0.5,
                    )
                )
            if ctx.is_room and (
                generation_wants(ctx, "bunnyland.environment.moisture")
                or generation_mentions(
                    ctx,
                    "river",
                    "pool",
                    "flooded",
                    "sump",
                    "pond",
                    "lake",
                    "marsh",
                    "swamp",
                )
            ):
                add(MoistureComponent())
            if generation_wants(
                ctx, "bunnyland.environment.flammable", "bunnyland.environment.fuel"
            ) or generation_mentions(
                ctx, "wood", "paper", "cloth", "grass", "forest", "brush", "fuel"
            ):
                add(FlammableComponent(fuel=8.0))
            if generation_wants(ctx, "bunnyland.environment.fire", "bunnyland.environment.burning"):
                add(FireComponent(last_updated_epoch=ctx.world_epoch))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = EnvironmentGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "EnvironmentGenerationEnricher"]
