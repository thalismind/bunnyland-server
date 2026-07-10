"""Toon Sim generation contribution surface."""

from ...mechanics.toonsim import ToonPlacementWorldgenHook, ToonWorldgenHook
from ...worldgen.enrichment import LegacyWorldgenEnricher

CAPABILITIES = ()
ALIASES = {}
GENERATION_ENRICHER = LegacyWorldgenEnricher(ToonWorldgenHook, provided_capabilities=CAPABILITIES)

__all__ = ["GENERATION_ENRICHER", "ToonPlacementWorldgenHook", "ToonWorldgenHook"]
