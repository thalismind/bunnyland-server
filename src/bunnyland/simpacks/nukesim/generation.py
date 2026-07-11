"""Declarative nukesim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import (
    GenerationContext,
    generation_mentions,
    generation_resource_type,
    generation_wants,
)
from .mechanics import (
    BeaconComponent,
    ChemComponent,
    ChemRecipeComponent,
    DecontaminationComponent,
    FactionSalvageComponent,
    FieldRepairComponent,
    GeneratorComponent,
    HotspotMarkerComponent,
    ItemModComponent,
    JunkComponent,
    LockedCrateComponent,
    LootTableComponent,
    MutationComponent,
    MutationResistanceComponent,
    MutationThresholdComponent,
    OldWorldTechComponent,
    RadiationDoseComponent,
    RadiationSourceComponent,
    RadMedicineComponent,
    RadProtectionComponent,
    RaiderPressureComponent,
    SampleComponent,
    ScavengeSiteComponent,
    SchematicComponent,
    SettlementComponent,
    SettlementSalvageComponent,
    SuppressantComponent,
    TechLeadComponent,
    TerminalComponent,
    TraderRouteComponent,
    WastelandArtifactComponent,
    WaterPurifierComponent,
    WaterPurityComponent,
)

CAPABILITIES = (
    "bunnyland.nukesim.beacon",
    "bunnyland.nukesim.chem",
    "bunnyland.nukesim.chem-recipe",
    "bunnyland.nukesim.decontamination",
    "bunnyland.nukesim.faction-salvage",
    "bunnyland.nukesim.field-repair",
    "bunnyland.nukesim.generator",
    "bunnyland.nukesim.hotspot-marker",
    "bunnyland.nukesim.item-mod",
    "bunnyland.nukesim.junk",
    "bunnyland.nukesim.locked-crate",
    "bunnyland.nukesim.mutation",
    "bunnyland.nukesim.mutation-resistance",
    "bunnyland.nukesim.mutation-threshold",
    "bunnyland.nukesim.old-world-tech",
    "bunnyland.nukesim.rad-medicine",
    "bunnyland.nukesim.rad-protection",
    "bunnyland.nukesim.radiation-dose",
    "bunnyland.nukesim.radiation-source",
    "bunnyland.nukesim.raider-pressure",
    "bunnyland.nukesim.sample",
    "bunnyland.nukesim.scavenge-site",
    "bunnyland.nukesim.schematic",
    "bunnyland.nukesim.settlement",
    "bunnyland.nukesim.settlement-salvage",
    "bunnyland.nukesim.suppressant",
    "bunnyland.nukesim.tech-lead",
    "bunnyland.nukesim.terminal",
    "bunnyland.nukesim.trader-route",
    "bunnyland.nukesim.wasteland-artifact",
    "bunnyland.nukesim.water-purifier",
    "bunnyland.nukesim.water-purity",
)


class NukeGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_character:
            if generation_wants(ctx, "bunnyland.nukesim.radiation-dose"):
                add(RadiationDoseComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.nukesim.mutation-threshold"):
                add(MutationThresholdComponent())
            if generation_wants(ctx, "bunnyland.nukesim.mutation-resistance"):
                add(MutationResistanceComponent(threshold_bonus=1.0))
        else:
            name = ctx.name
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "bunnyland.nukesim.radiation-source") or generation_mentions(
                ctx, "radiation", "fallout", "reactor"
            ):
                add(RadiationSourceComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.nukesim.scavenge-site") or generation_mentions(
                ctx, "ruin", "wasteland", "cache"
            ):
                add(ScavengeSiteComponent(hazard_rads=1.0))
                add(LootTableComponent(outputs={"scrap": 2}))
            if generation_wants(ctx, "bunnyland.nukesim.settlement") or generation_mentions(
                ctx, "settlement"
            ):
                add(SettlementComponent(name=name))
            if generation_wants(ctx, "bunnyland.nukesim.settlement-salvage") or generation_mentions(
                ctx, "settlement salvage"
            ):
                add(SettlementSalvageComponent(outputs={"scrap": 2}))
            if generation_wants(ctx, "bunnyland.nukesim.water-purifier") or generation_mentions(
                ctx, "water purifier"
            ):
                add(WaterPurifierComponent())
            if generation_wants(ctx, "bunnyland.nukesim.generator") or generation_mentions(
                ctx, "generator"
            ):
                add(GeneratorComponent())
            if generation_wants(ctx, "bunnyland.nukesim.beacon") or generation_mentions(
                ctx, "radio beacon"
            ):
                add(BeaconComponent(message=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.nukesim.trader-route") or generation_mentions(
                ctx, "trader route"
            ):
                add(TraderRouteComponent(destination=name))
            if generation_wants(ctx, "bunnyland.nukesim.raider-pressure") or generation_mentions(
                ctx, "raider"
            ):
                add(RaiderPressureComponent())
            if generation_wants(ctx, "bunnyland.nukesim.terminal") or generation_mentions(
                ctx, "terminal"
            ):
                add(TerminalComponent())
            if generation_wants(ctx, "bunnyland.nukesim.old-world-tech") or generation_mentions(
                ctx, "old-world", "pre-war"
            ):
                add(OldWorldTechComponent(tech_name=name))
            if generation_wants(ctx, "bunnyland.nukesim.tech-lead"):
                add(TechLeadComponent(target_tech=resource_type, location_hint=ctx.intent))
            if generation_wants(ctx, "bunnyland.nukesim.water-purity") or generation_mentions(
                ctx, "dirty water", "purified water"
            ):
                add(
                    WaterPurityComponent(
                        rads_per_drink=1.0
                        if generation_mentions(ctx, "dirty", "contaminated")
                        else 0.0,
                        purified=generation_mentions(ctx, "purified"),
                    )
                )
            if ctx.is_object:
                if generation_wants(ctx, "bunnyland.nukesim.rad-protection"):
                    add(RadProtectionComponent(rating=0.5))
                if generation_wants(ctx, "bunnyland.nukesim.decontamination"):
                    add(DecontaminationComponent())
                if generation_wants(ctx, "bunnyland.nukesim.rad-medicine"):
                    add(RadMedicineComponent())
                if generation_wants(ctx, "bunnyland.nukesim.mutation"):
                    add(
                        MutationComponent(
                            mutation_id=ctx.entity_key,
                            label=name,
                            manifested_at_epoch=ctx.world_epoch,
                        )
                    )
                if generation_wants(ctx, "bunnyland.nukesim.mutation-resistance"):
                    add(MutationResistanceComponent(threshold_bonus=1.0))
                if generation_wants(ctx, "bunnyland.nukesim.suppressant"):
                    add(SuppressantComponent())
                if generation_wants(ctx, "bunnyland.nukesim.sample") or generation_mentions(
                    ctx, "sample"
                ):
                    add(SampleComponent(sample_type=resource_type))
                if generation_wants(ctx, "bunnyland.nukesim.locked-crate") or generation_mentions(
                    ctx, "locked crate"
                ):
                    add(LockedCrateComponent())
                if generation_wants(
                    ctx, "bunnyland.nukesim.wasteland-artifact"
                ) or generation_mentions(ctx, "wasteland artifact"):
                    add(WastelandArtifactComponent(artifact_type=resource_type))
                if generation_wants(ctx, "bunnyland.nukesim.faction-salvage"):
                    add(FactionSalvageComponent(faction_id="generated-faction"))
                if generation_wants(ctx, "bunnyland.nukesim.schematic"):
                    add(SchematicComponent(mod_name=name))
                if generation_wants(ctx, "bunnyland.nukesim.item-mod"):
                    add(ItemModComponent(mod_name=name))
                if generation_wants(ctx, "bunnyland.nukesim.field-repair"):
                    add(FieldRepairComponent())
                if generation_wants(ctx, "bunnyland.nukesim.chem") or generation_mentions(
                    ctx, "chem"
                ):
                    add(ChemComponent(chem_type=resource_type))
                if generation_wants(ctx, "bunnyland.nukesim.chem-recipe"):
                    add(ChemRecipeComponent(chem_type=resource_type))
                if generation_wants(ctx, "bunnyland.nukesim.hotspot-marker"):
                    add(HotspotMarkerComponent(source_id=ctx.entity_id, marked_by="worldgen"))
                if generation_wants(ctx, "bunnyland.nukesim.junk") or generation_mentions(
                    ctx, "junk"
                ):
                    add(JunkComponent(outputs={"scrap": 1}, contaminated_rads=0.5))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = NukeGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "NukeGenerationEnricher"]
