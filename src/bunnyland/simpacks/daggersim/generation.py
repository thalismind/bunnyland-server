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
    "bunnyland.daggersim.camping",
    "bunnyland.daggersim.class-template",
    "bunnyland.daggersim.conversation-tone",
    "bunnyland.daggersim.creature-language",
    "bunnyland.daggersim.cure-quest-hook",
    "bunnyland.daggersim.custom-class",
    "bunnyland.daggersim.custom-spell",
    "bunnyland.daggersim.dagger-quest-reward",
    "bunnyland.daggersim.dialogue-approach",
    "bunnyland.daggersim.dungeon",
    "bunnyland.daggersim.dungeon-objective",
    "bunnyland.daggersim.enchanted-item",
    "bunnyland.daggersim.etiquette-skill",
    "bunnyland.daggersim.expansion-hook",
    "bunnyland.daggersim.feeding-need",
    "bunnyland.daggersim.generated-quest",
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
    "bunnyland.daggersim.quest-deadline",
    "bunnyland.daggersim.quest-template",
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

ALIASES = {
    "affliction-stigma": "bunnyland.daggersim.affliction-stigma",
    "automap": "bunnyland.daggersim.automap",
    "bank": "bunnyland.daggersim.bank",
    "camping": "bunnyland.daggersim.camping",
    "class-template": "bunnyland.daggersim.class-template",
    "conversation-tone": "bunnyland.daggersim.conversation-tone",
    "creature-language": "bunnyland.daggersim.creature-language",
    "cure-quest-hook": "bunnyland.daggersim.cure-quest-hook",
    "custom-class": "bunnyland.daggersim.custom-class",
    "custom-spell": "bunnyland.daggersim.custom-spell",
    "dagger-quest-reward": "bunnyland.daggersim.dagger-quest-reward",
    "dialogue-approach": "bunnyland.daggersim.dialogue-approach",
    "dungeon": "bunnyland.daggersim.dungeon",
    "dungeon-objective": "bunnyland.daggersim.dungeon-objective",
    "enchanted-item": "bunnyland.daggersim.enchanted-item",
    "etiquette-skill": "bunnyland.daggersim.etiquette-skill",
    "expansion-hook": "bunnyland.daggersim.expansion-hook",
    "feeding-need": "bunnyland.daggersim.feeding-need",
    "generated-quest": "bunnyland.daggersim.generated-quest",
    "hostility": "bunnyland.daggersim.hostility",
    "ingredient": "bunnyland.daggersim.ingredient",
    "institution": "bunnyland.daggersim.institution",
    "institution-dues": "bunnyland.daggersim.institution-dues",
    "institution-reputation": "bunnyland.daggersim.institution-reputation",
    "institution-service": "bunnyland.daggersim.institution-service",
    "language-skill": "bunnyland.daggersim.language-skill",
    "law-region": "bunnyland.daggersim.law-region",
    "legal-reputation": "bunnyland.daggersim.legal-reputation",
    "lodging": "bunnyland.daggersim.lodging",
    "potion-maker": "bunnyland.daggersim.potion-maker",
    "procedural-site": "bunnyland.daggersim.procedural-site",
    "property-deed": "bunnyland.daggersim.property-deed",
    "quest-deadline": "bunnyland.daggersim.quest-deadline",
    "quest-template": "bunnyland.daggersim.quest-template",
    "recall-anchor": "bunnyland.daggersim.recall-anchor",
    "recharge-service": "bunnyland.daggersim.recharge-service",
    "regional-reputation": "bunnyland.daggersim.regional-reputation",
    "rest-risk": "bunnyland.daggersim.rest-risk",
    "rumor": "bunnyland.daggersim.rumor",
    "rumor-reliability": "bunnyland.daggersim.rumor-reliability",
    "rumor-source": "bunnyland.daggersim.rumor-source",
    "rumor-target": "bunnyland.daggersim.rumor-target",
    "secret-door": "bunnyland.daggersim.secret-door",
    "service-access": "bunnyland.daggersim.service-access",
    "social-register": "bunnyland.daggersim.social-register",
    "spell-template": "bunnyland.daggersim.spell-template",
    "streetwise-skill": "bunnyland.daggersim.streetwise-skill",
    "supernatural-affliction": "bunnyland.daggersim.supernatural-affliction",
    "travel-hub": "bunnyland.daggersim.travel-hub",
    "travel-interruption": "bunnyland.daggersim.travel-interruption",
    "travel-mode": "bunnyland.daggersim.travel-mode",
    "travel-supply": "bunnyland.daggersim.travel-supply",
    "unrealized-location": "bunnyland.daggersim.unrealized-location",
}


class DaggerGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            name = ctx.name
            if generation_wants(ctx, "procedural-site"):
                add(ProceduralSiteComponent(site_type=ctx.biome, seed=ctx.seed))
            if generation_wants(ctx, "unrealized-location") or generation_mentions(
                ctx, "unrealized location"
            ):
                add(
                    UnrealizedLocationComponent(summary=ctx.intent or name, region_id=ctx.entity_id)
                )
            if generation_wants(ctx, "expansion-hook"):
                add(
                    ExpansionHookComponent(
                        trigger=generation_expansion_trigger(ctx),
                        generator_plugin_id=_DEFAULT_EXPANSION_GENERATOR,
                    )
                )
            if generation_wants(ctx, "dungeon") or generation_mentions(
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
            if generation_wants(ctx, "travel-hub") or generation_mentions(
                ctx, "crossroads", "station"
            ):
                add(TravelHubComponent(name=name))
            if generation_wants(ctx, "travel-mode"):
                add(TravelModeComponent(mode=ctx.biome or "foot"))
            if generation_wants(ctx, "institution") or generation_mentions(
                ctx, "guild", "temple", "bank"
            ):
                add(InstitutionComponent(name=name))
            if generation_wants(ctx, "institution-service"):
                add(InstitutionServiceComponent(service_name=name))
            if generation_wants(ctx, "institution-dues"):
                add(InstitutionDuesComponent(amount_due=10))
            if generation_wants(ctx, "bank") or generation_mentions(ctx, "bank"):
                add(BankComponent(name=name, region_id=ctx.entity_id))
            if generation_wants(ctx, "law-region"):
                add(LawRegionComponent(region_id=ctx.entity_id, fines={"trespass": 5}))
            if generation_wants(ctx, "property-deed"):
                add(PropertyDeedComponent(property_id=ctx.entity_id, region_id=ctx.entity_id))
            if generation_wants(ctx, "lodging") or generation_mentions(ctx, "inn", "lodging"):
                add(LodgingComponent(price=5))
            if generation_wants(ctx, "camping") or generation_mentions(ctx, "camp"):
                add(CampingComponent(risk="low", started_at_epoch=ctx.world_epoch))
            if generation_wants(ctx, "travel-supply"):
                add(TravelSupplyComponent(quantity=3))
            if generation_wants(ctx, "travel-interruption"):
                add(TravelInterruptionComponent(reason=ctx.intent or "worldgen"))
            if generation_wants(ctx, "rest-risk"):
                add(RestRiskComponent(band="uneasy", note=ctx.intent or name))
        elif ctx.is_character:
            name = ctx.name
            if generation_wants(ctx, "bounty"):
                add(BountyComponent(amount=10, region_id=ctx.room_id))
            if generation_wants(ctx, "regional-reputation"):
                add(RegionalReputationComponent(scores={ctx.room_id: 1}))
            if generation_wants(ctx, "institution-reputation"):
                add(
                    InstitutionReputationComponent(
                        scores={generation_generated_id(ctx, "institution"): 1}
                    )
                )
            if generation_wants(ctx, "legal-reputation"):
                add(LegalReputationComponent(scores={ctx.room_id: 0}))
            if generation_wants(ctx, "service-access"):
                add(ServiceAccessComponent(service_ids=(generation_generated_id(ctx, "service"),)))
            if generation_wants(ctx, "class-template"):
                add(ClassTemplateComponent(class_name=name, primary_skills=tuple(ctx.tags)))
            if generation_wants(ctx, "custom-class"):
                add(CustomClassComponent(class_name=name, primary_skills=tuple(ctx.tags)))
            if generation_wants(ctx, "language-skill"):
                add(LanguageSkillComponent(languages={ctx.species: 1}))
            if generation_wants(ctx, "supernatural-affliction"):
                add(
                    SupernaturalAfflictionComponent(
                        affliction_type=ctx.intent or "worldgen",
                        contracted_at_epoch=ctx.world_epoch,
                    )
                )
            if generation_wants(ctx, "affliction-stigma"):
                add(AfflictionStigmaComponent(region_id=ctx.room_id))
            if generation_wants(ctx, "feeding-need"):
                add(FeedingNeedComponent(current=1.0, last_updated_epoch=ctx.world_epoch))
            if generation_wants(ctx, "recall-anchor"):
                add(RecallAnchorComponent(room_id=ctx.room_id))
            if generation_wants(ctx, "dialogue-approach"):
                add(DialogueApproachComponent(last_approach="worldgen"))
            if generation_wants(ctx, "etiquette-skill"):
                add(EtiquetteSkillComponent(level=1))
            if generation_wants(ctx, "streetwise-skill"):
                add(StreetwiseSkillComponent(level=1))
            if generation_wants(ctx, "social-register"):
                add(SocialRegisterComponent(register=ctx.species))
            if generation_wants(ctx, "conversation-tone"):
                add(ConversationToneComponent(tone="curious", last_reaction=ctx.intent or name))
        else:
            name = ctx.name
            if generation_wants(ctx, "expansion-hook"):
                add(
                    ExpansionHookComponent(
                        trigger=generation_expansion_trigger(ctx),
                        generator_plugin_id=_DEFAULT_EXPANSION_GENERATOR,
                    )
                )
            if generation_wants(ctx, "rumor") or generation_mentions(ctx, "rumor"):
                add(RumorComponent(text=ctx.intent or name))
            if generation_wants(ctx, "rumor-source"):
                add(RumorSourceComponent(source_id=ctx.room_id))
            if generation_wants(ctx, "rumor-reliability"):
                add(RumorReliabilityComponent(score=0.75))
            if generation_wants(ctx, "rumor-target"):
                add(RumorTargetComponent(target_id=ctx.room_id or ctx.entity_id))
            if generation_wants(ctx, "bank") or generation_mentions(ctx, "bank"):
                add(BankComponent(name=name, region_id=ctx.room_id or ""))
            if generation_wants(ctx, "spell-template"):
                add(SpellTemplateComponent(spell_name=name, effect_type="worldgen", magnitude=1.0))
            if generation_wants(ctx, "custom-spell"):
                add(CustomSpellComponent(spell_name=name, effect_type="worldgen", magnitude=1.0))
            if generation_wants(ctx, "enchanted-item"):
                add(EnchantedItemComponent(spell_name=name, effect_type="worldgen", magnitude=1.0))
            if generation_wants(ctx, "potion-maker"):
                add(PotionMakerComponent(recipe_name=name, output_item_name=f"{name} potion"))
            if generation_wants(ctx, "recharge-service"):
                add(RechargeServiceComponent(charge_amount=1))
            if generation_wants(ctx, "ingredient"):
                add(IngredientComponent(ingredient_name=name, effect=ctx.intent or "worldgen"))
            if generation_wants(ctx, "creature-language"):
                add(CreatureLanguageComponent(language=ctx.entity_kind))
            if generation_wants(ctx, "hostility"):
                add(HostilityComponent(hostile=True))
            if generation_wants(ctx, "dungeon-objective"):
                add(
                    DungeonObjectiveComponent(
                        objective_kind=ctx.entity_kind, description=ctx.intent or name
                    )
                )
            if generation_wants(ctx, "secret-door") or generation_mentions(ctx, "secret door"):
                add(SecretDoorComponent(target_room_id=ctx.room_id or ctx.entity_id, hint=name))
            if generation_wants(ctx, "automap"):
                add(AutomapComponent(marked_rooms=(ctx.room_id,) if ctx.room_id else ()))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = DaggerGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "DaggerGenerationEnricher"]
