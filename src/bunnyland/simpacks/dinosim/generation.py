"""Declarative dinosim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
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

ALIASES = {
    "ancient-sample": "bunnyland.dinosim.ancient-sample",
    "apex-predator": "bunnyland.dinosim.apex-predator",
    "armor-plate": "bunnyland.dinosim.armor-plate",
    "bait": "bunnyland.dinosim.bait",
    "bone": "bunnyland.dinosim.bone",
    "charge": "bunnyland.dinosim.charge",
    "creature-attack": "bunnyland.dinosim.creature-attack",
    "creature-need": "bunnyland.dinosim.creature-need",
    "creature-product": "bunnyland.dinosim.creature-product",
    "dinosaur": "bunnyland.dinosim.dinosaur",
    "egg": "bunnyland.dinosim.egg",
    "enclosure": "bunnyland.dinosim.enclosure",
    "fossil": "bunnyland.dinosim.fossil",
    "fossil-survey": "bunnyland.dinosim.fossil-survey",
    "herd": "bunnyland.dinosim.herd",
    "hide": "bunnyland.dinosim.hide",
    "kaiju": "bunnyland.dinosim.kaiju",
    "nest": "bunnyland.dinosim.nest",
    "roar": "bunnyland.dinosim.roar",
    "scent": "bunnyland.dinosim.scent",
    "territory": "bunnyland.dinosim.territory",
    "toxin": "bunnyland.dinosim.toxin",
    "track": "bunnyland.dinosim.track",
    "trample": "bunnyland.dinosim.trample",
    "tranquilizer": "bunnyland.dinosim.tranquilizer",
    "water-creature": "bunnyland.dinosim.water-creature",
    "weak-point": "bunnyland.dinosim.weak-point",
}


class DinoGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            species = generation_resource_type(ctx)
            if generation_wants(ctx, "enclosure") or generation_mentions(ctx, "enclosure", "pen"):
                add(EnclosureComponent(name=ctx.name))
                add(EscapeRiskComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "track") or generation_mentions(ctx, "tracks", "footprints"):
                add(TrackComponent(room_id=ctx.entity_id, last_tracked_epoch=ctx.world_epoch))
            if generation_wants(ctx, "territory") or generation_mentions(ctx, "territory"):
                add(TerritoryComponent(species_name=species, marked_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "herd") or generation_mentions(ctx, "herd"):
                add(HerdComponent(species_name=species, last_tracked_epoch=ctx.world_epoch))
            if generation_wants(ctx, "nest") or generation_mentions(ctx, "nest"):
                add(NestComponent(species_name=species))
            if generation_wants(ctx, "scent"):
                add(ScentComponent(species_name=species))
        elif ctx.is_character:
            if generation_wants(ctx, "dinosaur") or generation_mentions(
                ctx, "dinosaur", "raptor", "rex"
            ):
                add(DinosaurComponent(species_name=ctx.species))
                add(SpeciesComponent(common_name=ctx.species))
                add(FertilityComponent())
            if generation_wants(ctx, "water-creature") or generation_mentions(
                ctx, "aquatic", "water creature"
            ):
                add(WaterCreatureComponent(species_name=ctx.species))
            if generation_wants(ctx, "creature-need"):
                add(CreatureNeedComponent(last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "kaiju") or generation_mentions(ctx, "kaiju"):
                add(KaijuComponent())
            if generation_wants(ctx, "creature-attack"):
                add(CreatureAttackComponent())
            if generation_wants(ctx, "roar") or generation_mentions(ctx, "roar"):
                add(RoarComponent())
            if generation_wants(ctx, "charge"):
                add(ChargeComponent())
            if generation_wants(ctx, "trample"):
                add(TrampleComponent())
            if generation_wants(ctx, "armor-plate"):
                add(ArmorPlateComponent())
            if generation_wants(ctx, "weak-point"):
                add(WeakPointComponent())
            if generation_wants(ctx, "apex-predator"):
                add(ApexPredatorComponent())
        else:
            species = generation_resource_type(ctx)
            if generation_wants(ctx, "fossil") or generation_mentions(ctx, "fossil", "amber"):
                add(FossilFragmentComponent(sample_quality=0.8))
            if generation_wants(ctx, "fossil-survey"):
                add(FossilSurveyComponent())
            if generation_wants(ctx, "ancient-sample"):
                add(AncientSampleComponent(species_name=species))
            if generation_wants(ctx, "bait"):
                add(BaitComponent(target_species=species))
            if generation_wants(ctx, "tranquilizer"):
                add(TranquilizerComponent())
            if generation_wants(ctx, "creature-product"):
                add(CreatureProductComponent(product_type=species))
            if generation_wants(ctx, "hide"):
                add(HideComponent())
            if generation_wants(ctx, "bone"):
                add(BoneComponent())
            if generation_wants(ctx, "toxin"):
                add(ToxinComponent())
            if generation_wants(ctx, "egg") or generation_mentions(ctx, "egg"):
                add(EggComponent(species_name=species, laid_at_epoch=ctx.world_epoch))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = DinoGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "DinoGenerationEnricher"]
