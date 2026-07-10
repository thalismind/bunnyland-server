"""barbariansim generation contribution compatibility surface."""

from ...worldgen.enrichment import BarbarianWorldgenHook, LegacyWorldgenEnricher

CAPABILITIES = (
    "bunnyland.barbariansim.armor",
    "bunnyland.barbariansim.base-claim",
    "bunnyland.barbariansim.blessing",
    "bunnyland.barbariansim.boss",
    "bunnyland.barbariansim.building",
    "bunnyland.barbariansim.climbing-gate",
    "bunnyland.barbariansim.climbing-skill",
    "bunnyland.barbariansim.combatant",
    "bunnyland.barbariansim.corruption",
    "bunnyland.barbariansim.curse",
    "bunnyland.barbariansim.danger-zone",
    "bunnyland.barbariansim.durability",
    "bunnyland.barbariansim.durable-fortification",
    "bunnyland.barbariansim.key",
    "bunnyland.barbariansim.poison",
    "bunnyland.barbariansim.purge-wave",
    "bunnyland.barbariansim.ritual",
    "bunnyland.barbariansim.shelter",
    "bunnyland.barbariansim.shrine",
    "bunnyland.barbariansim.siege-readiness",
    "bunnyland.barbariansim.stamina",
    "bunnyland.barbariansim.survival-gap",
    "bunnyland.barbariansim.temperature-exposure",
    "bunnyland.barbariansim.temperature-resistance",
    "bunnyland.barbariansim.trap",
    "bunnyland.barbariansim.treasure",
    "bunnyland.barbariansim.weapon",
)
ALIASES = {
    "armor": "bunnyland.barbariansim.armor",
    "base-claim": "bunnyland.barbariansim.base-claim",
    "blessing": "bunnyland.barbariansim.blessing",
    "boss": "bunnyland.barbariansim.boss",
    "building": "bunnyland.barbariansim.building",
    "climbing-gate": "bunnyland.barbariansim.climbing-gate",
    "climbing-skill": "bunnyland.barbariansim.climbing-skill",
    "combatant": "bunnyland.barbariansim.combatant",
    "corruption": "bunnyland.barbariansim.corruption",
    "curse": "bunnyland.barbariansim.curse",
    "danger-zone": "bunnyland.barbariansim.danger-zone",
    "durability": "bunnyland.barbariansim.durability",
    "durable-fortification": "bunnyland.barbariansim.durable-fortification",
    "key": "bunnyland.barbariansim.key",
    "poison": "bunnyland.barbariansim.poison",
    "purge-wave": "bunnyland.barbariansim.purge-wave",
    "ritual": "bunnyland.barbariansim.ritual",
    "shelter": "bunnyland.barbariansim.shelter",
    "shrine": "bunnyland.barbariansim.shrine",
    "siege-readiness": "bunnyland.barbariansim.siege-readiness",
    "stamina": "bunnyland.barbariansim.stamina",
    "survival-gap": "bunnyland.barbariansim.survival-gap",
    "temperature-exposure": "bunnyland.barbariansim.temperature-exposure",
    "temperature-resistance": "bunnyland.barbariansim.temperature-resistance",
    "trap": "bunnyland.barbariansim.trap",
    "treasure": "bunnyland.barbariansim.treasure",
    "weapon": "bunnyland.barbariansim.weapon",
}
GENERATION_ENRICHER = LegacyWorldgenEnricher(
    BarbarianWorldgenHook, provided_capabilities=CAPABILITIES
)

__all__ = ["GENERATION_ENRICHER", "BarbarianWorldgenHook"]
