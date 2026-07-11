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

ALIASES = {
    "beacon": "bunnyland.nukesim.beacon",
    "chem": "bunnyland.nukesim.chem",
    "chem-recipe": "bunnyland.nukesim.chem-recipe",
    "decontamination": "bunnyland.nukesim.decontamination",
    "faction-salvage": "bunnyland.nukesim.faction-salvage",
    "field-repair": "bunnyland.nukesim.field-repair",
    "generator": "bunnyland.nukesim.generator",
    "hotspot-marker": "bunnyland.nukesim.hotspot-marker",
    "item-mod": "bunnyland.nukesim.item-mod",
    "junk": "bunnyland.nukesim.junk",
    "locked-crate": "bunnyland.nukesim.locked-crate",
    "mutation": "bunnyland.nukesim.mutation",
    "mutation-resistance": "bunnyland.nukesim.mutation-resistance",
    "mutation-threshold": "bunnyland.nukesim.mutation-threshold",
    "old-world-tech": "bunnyland.nukesim.old-world-tech",
    "rad-medicine": "bunnyland.nukesim.rad-medicine",
    "rad-protection": "bunnyland.nukesim.rad-protection",
    "radiation-dose": "bunnyland.nukesim.radiation-dose",
    "radiation-source": "bunnyland.nukesim.radiation-source",
    "raider-pressure": "bunnyland.nukesim.raider-pressure",
    "sample": "bunnyland.nukesim.sample",
    "scavenge-site": "bunnyland.nukesim.scavenge-site",
    "schematic": "bunnyland.nukesim.schematic",
    "settlement": "bunnyland.nukesim.settlement",
    "settlement-salvage": "bunnyland.nukesim.settlement-salvage",
    "suppressant": "bunnyland.nukesim.suppressant",
    "tech-lead": "bunnyland.nukesim.tech-lead",
    "terminal": "bunnyland.nukesim.terminal",
    "trader-route": "bunnyland.nukesim.trader-route",
    "wasteland-artifact": "bunnyland.nukesim.wasteland-artifact",
    "water-purifier": "bunnyland.nukesim.water-purifier",
    "water-purity": "bunnyland.nukesim.water-purity",
}


class NukeGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_character:
            if generation_wants(ctx, "radiation-dose"):
                add(RadiationDoseComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "mutation-threshold"):
                add(MutationThresholdComponent())
            if generation_wants(ctx, "mutation-resistance"):
                add(MutationResistanceComponent(threshold_bonus=1.0))
        else:
            name = ctx.name
            resource_type = generation_resource_type(ctx)
            if generation_wants(ctx, "radiation-source") or generation_mentions(
                ctx, "radiation", "fallout", "reactor"
            ):
                add(RadiationSourceComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "scavenge-site") or generation_mentions(
                ctx, "ruin", "wasteland", "cache"
            ):
                add(ScavengeSiteComponent(hazard_rads=1.0))
                add(LootTableComponent(outputs={"scrap": 2}))
            if generation_wants(ctx, "settlement") or generation_mentions(ctx, "settlement"):
                add(SettlementComponent(name=name))
            if generation_wants(ctx, "settlement-salvage") or generation_mentions(
                ctx, "settlement salvage"
            ):
                add(SettlementSalvageComponent(outputs={"scrap": 2}))
            if generation_wants(ctx, "water-purifier") or generation_mentions(
                ctx, "water purifier"
            ):
                add(WaterPurifierComponent())
            if generation_wants(ctx, "generator") or generation_mentions(ctx, "generator"):
                add(GeneratorComponent())
            if generation_wants(ctx, "beacon") or generation_mentions(ctx, "radio beacon"):
                add(BeaconComponent(message=ctx.intent or name))
            if generation_wants(ctx, "trader-route") or generation_mentions(ctx, "trader route"):
                add(TraderRouteComponent(destination=name))
            if generation_wants(ctx, "raider-pressure") or generation_mentions(ctx, "raider"):
                add(RaiderPressureComponent())
            if generation_wants(ctx, "terminal") or generation_mentions(ctx, "terminal"):
                add(TerminalComponent())
            if generation_wants(ctx, "old-world-tech") or generation_mentions(
                ctx, "old-world", "pre-war"
            ):
                add(OldWorldTechComponent(tech_name=name))
            if generation_wants(ctx, "tech-lead"):
                add(TechLeadComponent(target_tech=resource_type, location_hint=ctx.intent))
            if generation_wants(ctx, "water-purity") or generation_mentions(
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
                if generation_wants(ctx, "rad-protection"):
                    add(RadProtectionComponent(rating=0.5))
                if generation_wants(ctx, "decontamination"):
                    add(DecontaminationComponent())
                if generation_wants(ctx, "rad-medicine"):
                    add(RadMedicineComponent())
                if generation_wants(ctx, "mutation"):
                    add(
                        MutationComponent(
                            mutation_id=ctx.entity_key,
                            label=name,
                            manifested_at_epoch=ctx.world_epoch,
                        )
                    )
                if generation_wants(ctx, "mutation-resistance"):
                    add(MutationResistanceComponent(threshold_bonus=1.0))
                if generation_wants(ctx, "suppressant"):
                    add(SuppressantComponent())
                if generation_wants(ctx, "sample") or generation_mentions(ctx, "sample"):
                    add(SampleComponent(sample_type=resource_type))
                if generation_wants(ctx, "locked-crate") or generation_mentions(
                    ctx, "locked crate"
                ):
                    add(LockedCrateComponent())
                if generation_wants(ctx, "wasteland-artifact") or generation_mentions(
                    ctx, "wasteland artifact"
                ):
                    add(WastelandArtifactComponent(artifact_type=resource_type))
                if generation_wants(ctx, "faction-salvage"):
                    add(FactionSalvageComponent(faction_id="generated-faction"))
                if generation_wants(ctx, "schematic"):
                    add(SchematicComponent(mod_name=name))
                if generation_wants(ctx, "item-mod"):
                    add(ItemModComponent(mod_name=name))
                if generation_wants(ctx, "field-repair"):
                    add(FieldRepairComponent())
                if generation_wants(ctx, "chem") or generation_mentions(ctx, "chem"):
                    add(ChemComponent(chem_type=resource_type))
                if generation_wants(ctx, "chem-recipe"):
                    add(ChemRecipeComponent(chem_type=resource_type))
                if generation_wants(ctx, "hotspot-marker"):
                    add(HotspotMarkerComponent(source_id=ctx.entity_id, marked_by="worldgen"))
                if generation_wants(ctx, "junk") or generation_mentions(ctx, "junk"):
                    add(JunkComponent(outputs={"scrap": 1}, contaminated_rads=0.5))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = NukeGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "NukeGenerationEnricher"]
