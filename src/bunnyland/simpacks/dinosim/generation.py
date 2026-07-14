"""Declarative dinosim generation contributions."""

from ...core.generation import GenerationDelta, GenerationEdge, GenerationRequest, GenerationTarget
from ...worldgen.enrichment import (
    GenerationContext,
    generation_mentions,
    generation_resource_type,
    generation_wants,
)
from .mechanics import (
    AncientSampleComponent,
    ApexPredatorComponent,
    ArmorPlateComponent,
    BaitComponent,
    BoneComponent,
    ChargeComponent,
    CreatureAttackComponent,
    CreatureNeedComponent,
    CreatureProductComponent,
    DinosaurComponent,
    EggComponent,
    EnclosureComponent,
    EscapeRiskComponent,
    FertilityComponent,
    FossilFragmentComponent,
    FossilSurveyComponent,
    HerdComponent,
    HideComponent,
    KaijuComponent,
    NestComponent,
    RoarComponent,
    ScentComponent,
    SpeciesComponent,
    TerritoryComponent,
    ToxinComponent,
    TrackComponent,
    TrackedAt,
    TrampleComponent,
    TranquilizerComponent,
    WaterCreatureComponent,
    WeakPointComponent,
)

CAPABILITIES = (
    "bunnyland.dinosim.ancient-sample",
    "bunnyland.dinosim.apex-predator",
    "bunnyland.dinosim.armor-plate",
    "bunnyland.dinosim.bait",
    "bunnyland.dinosim.bone",
    "bunnyland.dinosim.charge",
    "bunnyland.dinosim.creature-attack",
    "bunnyland.dinosim.creature-need",
    "bunnyland.dinosim.creature-product",
    "bunnyland.dinosim.dinosaur",
    "bunnyland.dinosim.egg",
    "bunnyland.dinosim.enclosure",
    "bunnyland.dinosim.fossil",
    "bunnyland.dinosim.fossil-survey",
    "bunnyland.dinosim.herd",
    "bunnyland.dinosim.hide",
    "bunnyland.dinosim.kaiju",
    "bunnyland.dinosim.nest",
    "bunnyland.dinosim.roar",
    "bunnyland.dinosim.scent",
    "bunnyland.dinosim.territory",
    "bunnyland.dinosim.toxin",
    "bunnyland.dinosim.track",
    "bunnyland.dinosim.trample",
    "bunnyland.dinosim.tranquilizer",
    "bunnyland.dinosim.water-creature",
    "bunnyland.dinosim.weak-point",
)


class DinoGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}
        edges = []

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            species = generation_resource_type(ctx)
            if generation_wants(ctx, "bunnyland.dinosim.enclosure") or generation_mentions(
                ctx, "enclosure", "pen"
            ):
                add(EnclosureComponent(name=ctx.name))
                add(EscapeRiskComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dinosim.track") or generation_mentions(
                ctx, "tracks", "footprints"
            ):
                add(TrackComponent(last_tracked_epoch=ctx.world_epoch))
                edges.append(GenerationEdge(TrackedAt(), GenerationTarget(ctx.entity_key)))
            if generation_wants(ctx, "bunnyland.dinosim.territory") or generation_mentions(
                ctx, "territory"
            ):
                add(TerritoryComponent(species_name=species, marked_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dinosim.herd") or generation_mentions(ctx, "herd"):
                add(HerdComponent(species_name=species, last_tracked_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dinosim.nest") or generation_mentions(ctx, "nest"):
                add(NestComponent(species_name=species))
            if generation_wants(ctx, "bunnyland.dinosim.scent"):
                add(ScentComponent(species_name=species))
        elif ctx.is_character:
            if generation_wants(ctx, "bunnyland.dinosim.dinosaur") or generation_mentions(
                ctx, "dinosaur", "raptor", "rex"
            ):
                add(DinosaurComponent(species_name=ctx.species))
                add(SpeciesComponent(common_name=ctx.species))
                add(FertilityComponent())
            if generation_wants(ctx, "bunnyland.dinosim.water-creature") or generation_mentions(
                ctx, "aquatic", "water creature"
            ):
                add(WaterCreatureComponent(species_name=ctx.species))
            if generation_wants(ctx, "bunnyland.dinosim.creature-need"):
                add(CreatureNeedComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.dinosim.kaiju") or generation_mentions(
                ctx, "kaiju"
            ):
                add(KaijuComponent())
            if generation_wants(ctx, "bunnyland.dinosim.creature-attack"):
                add(CreatureAttackComponent())
            if generation_wants(ctx, "bunnyland.dinosim.roar") or generation_mentions(ctx, "roar"):
                add(RoarComponent())
            if generation_wants(ctx, "bunnyland.dinosim.charge"):
                add(ChargeComponent())
            if generation_wants(ctx, "bunnyland.dinosim.trample"):
                add(TrampleComponent())
            if generation_wants(ctx, "bunnyland.dinosim.armor-plate"):
                add(ArmorPlateComponent())
            if generation_wants(ctx, "bunnyland.dinosim.weak-point"):
                add(WeakPointComponent())
            if generation_wants(ctx, "bunnyland.dinosim.apex-predator"):
                add(ApexPredatorComponent())
        else:
            species = generation_resource_type(ctx)
            if generation_wants(ctx, "bunnyland.dinosim.fossil") or generation_mentions(
                ctx, "fossil", "amber"
            ):
                add(FossilFragmentComponent(sample_quality=0.8))
            if generation_wants(ctx, "bunnyland.dinosim.fossil-survey"):
                add(FossilSurveyComponent())
            if generation_wants(ctx, "bunnyland.dinosim.ancient-sample"):
                add(AncientSampleComponent(species_name=species))
            if generation_wants(ctx, "bunnyland.dinosim.bait"):
                add(BaitComponent(target_species=species))
            if generation_wants(ctx, "bunnyland.dinosim.tranquilizer"):
                add(TranquilizerComponent())
            if generation_wants(ctx, "bunnyland.dinosim.creature-product"):
                add(CreatureProductComponent(product_type=species))
            if generation_wants(ctx, "bunnyland.dinosim.hide"):
                add(HideComponent())
            if generation_wants(ctx, "bunnyland.dinosim.bone"):
                add(BoneComponent())
            if generation_wants(ctx, "bunnyland.dinosim.toxin"):
                add(ToxinComponent())
            if generation_wants(ctx, "bunnyland.dinosim.egg") or generation_mentions(ctx, "egg"):
                add(EggComponent(species_name=species, laid_at_epoch=ctx.world_epoch))
        return GenerationDelta(
            components=tuple(components.values()),
            edges=tuple(edges),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = DinoGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "DinoGenerationEnricher"]
