"""Declarative barbariansim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import (
    GenerationContext,
    generation_generated_id,
    generation_mentions,
    generation_resource_type,
    generation_wants,
)
from .mechanics import (
    ArmorComponent,
    BaseClaimComponent,
    BlessingComponent,
    BossComponent,
    BuildingComponent,
    ClimbingGateComponent,
    ClimbingSkillComponent,
    CorruptionComponent,
    CurseComponent,
    DangerZoneComponent,
    DurabilityComponent,
    FortificationComponent,
    PoisonComponent,
    PurgeWaveComponent,
    RitualComponent,
    ShelterComponent,
    ShrineComponent,
    SiegeReadinessComponent,
    StaminaComponent,
    SurvivalGapComponent,
    TemperatureExposureComponent,
    TemperatureResistanceComponent,
    TrapComponent,
    TreasureComponent,
    WeaponComponent,
)

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


class BarbarianGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.barbariansim.shelter") or generation_mentions(
                ctx, "shelter", "camp"
            ):
                add(ShelterComponent(temperature_buffer=10.0))
            if generation_wants(ctx, "bunnyland.barbariansim.base-claim"):
                add(
                    BaseClaimComponent(
                        claimed_by=generation_generated_id(ctx, "claimant"),
                        clan=name,
                        claimed_at_epoch=ctx.world_epoch,
                    )
                )
            if generation_wants(ctx, "bunnyland.barbariansim.survival-gap") or generation_mentions(
                ctx, "shortage", "survival gap"
            ):
                add(SurvivalGapComponent(required_resource=generation_resource_type(ctx)))
            if generation_wants(ctx, "bunnyland.barbariansim.building") or generation_mentions(
                ctx, "building", "hall"
            ):
                add(BuildingComponent(integrity=20.0, maximum_integrity=20.0))
            if generation_wants(
                ctx, "bunnyland.barbariansim.siege-readiness"
            ) or generation_mentions(ctx, "siege"):
                add(SiegeReadinessComponent(score=1.0))
            if generation_wants(ctx, "bunnyland.barbariansim.purge-wave") or generation_mentions(
                ctx, "purge wave"
            ):
                add(PurgeWaveComponent(wave=1, started_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.barbariansim.danger-zone") or generation_mentions(
                ctx, "danger zone", "ruin"
            ):
                add(DangerZoneComponent(zone_type=ctx.biome))
            if generation_wants(ctx, "bunnyland.barbariansim.boss") or generation_mentions(
                ctx, "boss", "warlord"
            ):
                add(BossComponent(name=name))
        elif ctx.is_character:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.barbariansim.temperature-resistance"):
                add(TemperatureResistanceComponent(heat=5.0, cold=5.0))
            if generation_wants(ctx, "bunnyland.barbariansim.temperature-exposure"):
                add(TemperatureExposureComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.barbariansim.poison") or generation_mentions(
                ctx, "poisoned"
            ):
                add(PoisonComponent(severity=1.0))
            if generation_wants(ctx, "bunnyland.barbariansim.corruption") or generation_mentions(
                ctx, "corrupted"
            ):
                add(CorruptionComponent(amount=1.0))
            if generation_wants(
                ctx, "bunnyland.barbariansim.stamina", "bunnyland.barbariansim.combatant"
            ) or generation_mentions(ctx, "warrior", "fighter"):
                add(StaminaComponent())
            if generation_wants(ctx, "bunnyland.barbariansim.blessing"):
                add(BlessingComponent(name=name, source_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.barbariansim.curse"):
                add(CurseComponent(name=name, source_id=ctx.entity_id))
            if generation_wants(
                ctx, "bunnyland.barbariansim.climbing-skill"
            ) or generation_mentions(ctx, "climber"):
                add(ClimbingSkillComponent(level=1))
        else:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.barbariansim.weapon") or generation_mentions(
                ctx, "sword", "axe", "spear", "club"
            ):
                add(WeaponComponent(damage=8.0, lethal_capable=True))
            if generation_wants(ctx, "bunnyland.barbariansim.armor") or generation_mentions(
                ctx, "armor", "shield"
            ):
                add(ArmorComponent(rating=2.0))
            if generation_wants(ctx, "bunnyland.barbariansim.durability") or generation_mentions(
                ctx, "durable"
            ):
                add(DurabilityComponent(current=10.0, maximum=10.0))
            if generation_wants(
                ctx, "bunnyland.barbariansim.durable-fortification"
            ) or generation_mentions(ctx, "barricade", "wall"):
                add(FortificationComponent(rating=2.0, durability=20.0))
            if generation_wants(ctx, "bunnyland.barbariansim.trap") or generation_mentions(
                ctx, "trap"
            ):
                add(TrapComponent(damage=6.0))
            if generation_wants(ctx, "bunnyland.barbariansim.shrine") or generation_mentions(
                ctx, "shrine", "altar"
            ):
                add(ShrineComponent(deity=name))
            if generation_wants(ctx, "bunnyland.barbariansim.ritual") or generation_mentions(
                ctx, "ritual"
            ):
                add(RitualComponent(ritual_type=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.barbariansim.blessing"):
                add(BlessingComponent(name=name, source_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.barbariansim.curse"):
                add(CurseComponent(name=name, source_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.barbariansim.treasure") or generation_mentions(
                ctx, "treasure", "cache"
            ):
                add(TreasureComponent(treasure_type=ctx.entity_kind, key_name=name))
            if generation_wants(ctx, "bunnyland.barbariansim.climbing-gate") or generation_mentions(
                ctx, "cliff", "climb"
            ):
                add(ClimbingGateComponent(required_level=1))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = BarbarianGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "BarbarianGenerationEnricher"]
