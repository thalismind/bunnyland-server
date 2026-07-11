"""lifesim generation contribution compatibility surface."""

from ...worldgen.enrichment import ComponentPlanEnricher, LifeWorldgenHook

CAPABILITIES = (
    "bunnyland.lifesim.aspiration",
    "bunnyland.lifesim.bill",
    "bunnyland.lifesim.business-owner",
    "bunnyland.lifesim.career",
    "bunnyland.lifesim.character-profile",
    "bunnyland.lifesim.customer",
    "bunnyland.lifesim.home",
    "bunnyland.lifesim.home-object",
    "bunnyland.lifesim.household",
    "bunnyland.lifesim.job-schedule",
    "bunnyland.lifesim.profile",
    "bunnyland.lifesim.reproductive",
    "bunnyland.lifesim.reputation",
    "bunnyland.lifesim.room-claim",
    "bunnyland.lifesim.routine",
    "bunnyland.lifesim.skill-set",
    "bunnyland.lifesim.whim",
)
ALIASES = {
    "aspiration": "bunnyland.lifesim.aspiration",
    "bill": "bunnyland.lifesim.bill",
    "business-owner": "bunnyland.lifesim.business-owner",
    "career": "bunnyland.lifesim.career",
    "character-profile": "bunnyland.lifesim.character-profile",
    "customer": "bunnyland.lifesim.customer",
    "home": "bunnyland.lifesim.home",
    "home-object": "bunnyland.lifesim.home-object",
    "household": "bunnyland.lifesim.household",
    "job-schedule": "bunnyland.lifesim.job-schedule",
    "profile": "bunnyland.lifesim.profile",
    "reproductive": "bunnyland.lifesim.reproductive",
    "reputation": "bunnyland.lifesim.reputation",
    "room-claim": "bunnyland.lifesim.room-claim",
    "routine": "bunnyland.lifesim.routine",
    "skill-set": "bunnyland.lifesim.skill-set",
    "whim": "bunnyland.lifesim.whim",
}
GENERATION_ENRICHER = ComponentPlanEnricher(LifeWorldgenHook, provided_capabilities=CAPABILITIES)

__all__ = ["GENERATION_ENRICHER", "LifeWorldgenHook"]
