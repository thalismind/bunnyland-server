"""Declarative daggersim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import (
    GenerationContext,
    generation_expansion_trigger,
    generation_generated_id,
    generation_mentions,
    generation_wants,
)
from .mechanics import (
    AfflictionStigmaComponent,
    AutomapComponent,
    BankComponent,
    BountyComponent,
    CampingComponent,
    ClassTemplateComponent,
    ConversationToneComponent,
    CreatureLanguageComponent,
    CureRequestComponent,
    CustomClassComponent,
    CustomSpellComponent,
    DialogueApproachComponent,
    DungeonComponent,
    DungeonObjectiveComponent,
    DungeonRoomComponent,
    EnchantedItemComponent,
    EtiquetteSkillComponent,
    ExpansionHookComponent,
    FeedingNeedComponent,
    HostilityComponent,
    IngredientComponent,
    InstitutionComponent,
    InstitutionDuesComponent,
    InstitutionReputationComponent,
    InstitutionServiceComponent,
    LanguageSkillComponent,
    LawRegionComponent,
    LegalReputationComponent,
    LodgingComponent,
    PotionMakerComponent,
    ProceduralSiteComponent,
    PropertyDeedComponent,
    RecallAnchorComponent,
    RechargeServiceComponent,
    RegionalReputationComponent,
    RestRiskComponent,
    RumorComponent,
    RumorReliabilityComponent,
    RumorSourceComponent,
    RumorTargetComponent,
    SecretDoorComponent,
    ServiceAccessComponent,
    SocialRegisterComponent,
    SpellTemplateComponent,
    StreetwiseSkillComponent,
    SupernaturalAfflictionComponent,
    TravelHubComponent,
    TravelInterruptionComponent,
    TravelModeComponent,
    TravelSupplyComponent,
    UnrealizedLocationComponent,
)

_DEFAULT_EXPANSION_GENERATOR = "worldgen.recursive"

CAPABILITIES = (
    "bunnyland.daggersim.affliction-stigma",
    "bunnyland.daggersim.automap",
    "bunnyland.daggersim.bank",
    "bunnyland.daggersim.bounty",
    "bunnyland.daggersim.camping",
    "bunnyland.daggersim.class-template",
    "bunnyland.daggersim.conversation-tone",
    "bunnyland.daggersim.creature-language",
    "bunnyland.daggersim.cure-request",
    "bunnyland.daggersim.custom-class",
    "bunnyland.daggersim.custom-spell",
    "bunnyland.daggersim.dialogue-approach",
    "bunnyland.daggersim.dungeon",
    "bunnyland.daggersim.dungeon-objective",
    "bunnyland.daggersim.enchanted-item",
    "bunnyland.daggersim.etiquette-skill",
    "bunnyland.daggersim.expansion-hook",
    "bunnyland.daggersim.feeding-need",
    "bunnyland.daggersim.hostility",
    "bunnyland.daggersim.ingredient",
    "bunnyland.daggersim.institution",
    "bunnyland.daggersim.institution-dues",
    "bunnyland.daggersim.institution-reputation",
    "bunnyland.daggersim.institution-service",
    "bunnyland.daggersim.language-skill",
    "bunnyland.daggersim.law-region",
    "bunnyland.daggersim.legal-reputation",
    "bunnyland.daggersim.lodging",
    "bunnyland.daggersim.potion-maker",
    "bunnyland.daggersim.procedural-site",
    "bunnyland.daggersim.property-deed",
    "bunnyland.daggersim.recall-anchor",
    "bunnyland.daggersim.recharge-service",
    "bunnyland.daggersim.regional-reputation",
    "bunnyland.daggersim.rest-risk",
    "bunnyland.daggersim.rumor",
    "bunnyland.daggersim.rumor-reliability",
    "bunnyland.daggersim.rumor-source",
    "bunnyland.daggersim.rumor-target",
    "bunnyland.daggersim.secret-door",
    "bunnyland.daggersim.service-access",
    "bunnyland.daggersim.social-register",
    "bunnyland.daggersim.spell-template",
    "bunnyland.daggersim.streetwise-skill",
    "bunnyland.daggersim.supernatural-affliction",
    "bunnyland.daggersim.travel-hub",
    "bunnyland.daggersim.travel-interruption",
    "bunnyland.daggersim.travel-mode",
    "bunnyland.daggersim.travel-supply",
    "bunnyland.daggersim.unrealized-location",
)


class DaggerGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.daggersim.procedural-site"):
                add(ProceduralSiteComponent(site_type=ctx.biome, seed=ctx.seed))
            if generation_wants(
                ctx, "bunnyland.daggersim.unrealized-location"
            ) or generation_mentions(ctx, "unrealized location"):
                add(
                    UnrealizedLocationComponent(summary=ctx.intent or name, region_id=ctx.entity_id)
                )
            if generation_wants(ctx, "bunnyland.daggersim.expansion-hook"):
                add(
                    ExpansionHookComponent(
                        trigger=generation_expansion_trigger(ctx),
                        generator_plugin_id=_DEFAULT_EXPANSION_GENERATOR,
                    )
                )
            if generation_wants(ctx, "bunnyland.daggersim.dungeon") or generation_mentions(
                ctx, "dungeon", "crypt", "vault"
            ):
                add(
                    DungeonComponent(
                        dungeon_id=ctx.room_key,
                        theme=ctx.biome,
                        seed=ctx.seed,
                        entry_room_id=ctx.entity_id,
                    )
                )
                add(DungeonRoomComponent(dungeon_id=ctx.room_key, discovered=True))
            if generation_wants(ctx, "bunnyland.daggersim.travel-hub") or generation_mentions(
                ctx, "crossroads", "station"
            ):
                add(TravelHubComponent(name=name))
            if generation_wants(ctx, "bunnyland.daggersim.travel-mode"):
                add(TravelModeComponent(mode=ctx.biome or "foot"))
            if generation_wants(ctx, "bunnyland.daggersim.institution") or generation_mentions(
                ctx, "guild", "temple", "bank"
            ):
                add(InstitutionComponent(name=name))
            if generation_wants(ctx, "bunnyland.daggersim.institution-service"):
                add(InstitutionServiceComponent(service_name=name))
            if generation_wants(ctx, "bunnyland.daggersim.institution-dues"):
                add(InstitutionDuesComponent(amount_due=10))
            if generation_wants(ctx, "bunnyland.daggersim.bank") or generation_mentions(
                ctx, "bank"
            ):
                add(BankComponent(name=name, region_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.daggersim.law-region"):
                add(LawRegionComponent(region_id=ctx.entity_id, fines={"trespass": 5}))
            if generation_wants(ctx, "bunnyland.daggersim.property-deed"):
                add(PropertyDeedComponent(property_id=ctx.entity_id, region_id=ctx.entity_id))
            if generation_wants(ctx, "bunnyland.daggersim.lodging") or generation_mentions(
                ctx, "inn", "lodging"
            ):
                add(LodgingComponent(price=5))
            if generation_wants(ctx, "bunnyland.daggersim.camping") or generation_mentions(
                ctx, "camp"
            ):
                add(CampingComponent(risk="low", started_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.daggersim.travel-supply"):
                add(TravelSupplyComponent(quantity=3))
            if generation_wants(ctx, "bunnyland.daggersim.travel-interruption"):
                add(TravelInterruptionComponent(reason=ctx.intent or "worldgen"))
            if generation_wants(ctx, "bunnyland.daggersim.rest-risk"):
                add(RestRiskComponent(band="uneasy", note=ctx.intent or name))
        elif ctx.is_character:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.daggersim.bounty"):
                add(BountyComponent(amount=10, region_id=ctx.room_id))
            if generation_wants(ctx, "bunnyland.daggersim.regional-reputation"):
                add(RegionalReputationComponent(scores={ctx.room_id: 1}))
            if generation_wants(ctx, "bunnyland.daggersim.institution-reputation"):
                add(
                    InstitutionReputationComponent(
                        scores={generation_generated_id(ctx, "institution"): 1}
                    )
                )
            if generation_wants(ctx, "bunnyland.daggersim.legal-reputation"):
                add(LegalReputationComponent(scores={ctx.room_id: 0}))
            if generation_wants(ctx, "bunnyland.daggersim.service-access"):
                add(ServiceAccessComponent(service_ids=(generation_generated_id(ctx, "service"),)))
            if generation_wants(ctx, "bunnyland.daggersim.class-template"):
                add(ClassTemplateComponent(class_name=name, primary_skills=tuple(ctx.tags)))
            if generation_wants(ctx, "bunnyland.daggersim.custom-class"):
                add(CustomClassComponent(class_name=name, primary_skills=tuple(ctx.tags)))
            if generation_wants(ctx, "bunnyland.daggersim.language-skill"):
                add(LanguageSkillComponent(languages={ctx.species: 1}))
            if generation_wants(ctx, "bunnyland.daggersim.supernatural-affliction"):
                add(
                    SupernaturalAfflictionComponent(
                        affliction_type=ctx.intent or "worldgen",
                        contracted_at_epoch=ctx.world_epoch,
                    )
                )
            if generation_wants(ctx, "bunnyland.daggersim.affliction-stigma"):
                add(AfflictionStigmaComponent(region_id=ctx.room_id))
            if generation_wants(ctx, "bunnyland.daggersim.cure-request"):
                add(CureRequestComponent(affliction_type=ctx.intent or "worldgen"))
            if generation_wants(ctx, "bunnyland.daggersim.feeding-need"):
                add(FeedingNeedComponent(current=1.0, last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.daggersim.recall-anchor"):
                add(RecallAnchorComponent(room_id=ctx.room_id))
            if generation_wants(ctx, "bunnyland.daggersim.dialogue-approach"):
                add(DialogueApproachComponent(last_approach="worldgen"))
            if generation_wants(ctx, "bunnyland.daggersim.etiquette-skill"):
                add(EtiquetteSkillComponent(level=1))
            if generation_wants(ctx, "bunnyland.daggersim.streetwise-skill"):
                add(StreetwiseSkillComponent(level=1))
            if generation_wants(ctx, "bunnyland.daggersim.social-register"):
                add(SocialRegisterComponent(register=ctx.species))
            if generation_wants(ctx, "bunnyland.daggersim.conversation-tone"):
                add(ConversationToneComponent(tone="curious", last_reaction=ctx.intent or name))
        else:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.daggersim.expansion-hook"):
                add(
                    ExpansionHookComponent(
                        trigger=generation_expansion_trigger(ctx),
                        generator_plugin_id=_DEFAULT_EXPANSION_GENERATOR,
                    )
                )
            if generation_wants(ctx, "bunnyland.daggersim.rumor") or generation_mentions(
                ctx, "rumor"
            ):
                add(RumorComponent(text=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.daggersim.rumor-source"):
                add(RumorSourceComponent(source_id=ctx.room_id))
            if generation_wants(ctx, "bunnyland.daggersim.rumor-reliability"):
                add(RumorReliabilityComponent(score=0.75))
            if generation_wants(ctx, "bunnyland.daggersim.rumor-target"):
                add(RumorTargetComponent(target_id=ctx.room_id or ctx.entity_id))
            if generation_wants(ctx, "bunnyland.daggersim.bank") or generation_mentions(
                ctx, "bank"
            ):
                add(BankComponent(name=name, region_id=ctx.room_id or ""))
            if generation_wants(ctx, "bunnyland.daggersim.spell-template"):
                add(SpellTemplateComponent(spell_name=name, effect_type="worldgen", magnitude=1.0))
            if generation_wants(ctx, "bunnyland.daggersim.custom-spell"):
                add(CustomSpellComponent(spell_name=name, effect_type="worldgen", magnitude=1.0))
            if generation_wants(ctx, "bunnyland.daggersim.enchanted-item"):
                add(EnchantedItemComponent(spell_name=name, effect_type="worldgen", magnitude=1.0))
            if generation_wants(ctx, "bunnyland.daggersim.potion-maker"):
                add(PotionMakerComponent(recipe_name=name, output_item_name=f"{name} potion"))
            if generation_wants(ctx, "bunnyland.daggersim.recharge-service"):
                add(RechargeServiceComponent(charge_amount=1))
            if generation_wants(ctx, "bunnyland.daggersim.ingredient"):
                add(IngredientComponent(ingredient_name=name, effect=ctx.intent or "worldgen"))
            if generation_wants(ctx, "bunnyland.daggersim.creature-language"):
                add(CreatureLanguageComponent(language=ctx.entity_kind))
            if generation_wants(ctx, "bunnyland.daggersim.hostility"):
                add(HostilityComponent(hostile=True))
            if generation_wants(ctx, "bunnyland.daggersim.dungeon-objective"):
                add(
                    DungeonObjectiveComponent(
                        objective_kind=ctx.entity_kind, description=ctx.intent or name
                    )
                )
            if generation_wants(ctx, "bunnyland.daggersim.secret-door") or generation_mentions(
                ctx, "secret door"
            ):
                add(SecretDoorComponent(target_room_id=ctx.room_id or ctx.entity_id, hint=name))
            if generation_wants(ctx, "bunnyland.daggersim.automap"):
                add(AutomapComponent(marked_rooms=(ctx.room_id,) if ctx.room_id else ()))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = DaggerGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "DaggerGenerationEnricher"]
