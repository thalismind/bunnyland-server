"""neonsim generation contribution compatibility surface."""

from ...worldgen.enrichment import ComponentPlanEnricher, NeonWorldgenHook

CAPABILITIES = (
    "bunnyland.neonsim.black-market",
    "bunnyland.neonsim.camera",
    "bunnyland.neonsim.checkpoint",
    "bunnyland.neonsim.clinic",
    "bunnyland.neonsim.cyberpunk-site",
    "bunnyland.neonsim.data-broker",
    "bunnyland.neonsim.fixer",
    "bunnyland.neonsim.netrunner",
    "bunnyland.neonsim.safehouse",
    "bunnyland.neonsim.security-zone",
)
ALIASES = {
    "black-market": "bunnyland.neonsim.black-market",
    "camera": "bunnyland.neonsim.camera",
    "checkpoint": "bunnyland.neonsim.checkpoint",
    "clinic": "bunnyland.neonsim.clinic",
    "cyberpunk-site": "bunnyland.neonsim.cyberpunk-site",
    "data-broker": "bunnyland.neonsim.data-broker",
    "fixer": "bunnyland.neonsim.fixer",
    "netrunner": "bunnyland.neonsim.netrunner",
    "safehouse": "bunnyland.neonsim.safehouse",
    "security-zone": "bunnyland.neonsim.security-zone",
}
GENERATION_ENRICHER = ComponentPlanEnricher(NeonWorldgenHook, provided_capabilities=CAPABILITIES)

__all__ = ["GENERATION_ENRICHER", "NeonWorldgenHook"]
