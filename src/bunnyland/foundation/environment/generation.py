"""Environment generation contribution compatibility surface."""

from ...worldgen.enrichment import ComponentPlanEnricher, EnvironmentWorldgenHook

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
GENERATION_ENRICHER = ComponentPlanEnricher(
    EnvironmentWorldgenHook, provided_capabilities=CAPABILITIES
)

__all__ = ["EnvironmentWorldgenHook", "GENERATION_ENRICHER"]
