"""Declarative lifesim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import (
    GenerationContext,
    generation_generated_id,
    generation_mentions,
    generation_resource_type,
    generation_wants,
)
from .mechanics import (
    AspirationComponent,
    BillComponent,
    BusinessOwnerComponent,
    CareerComponent,
    CharacterProfileComponent,
    CustomerComponent,
    HomeComponent,
    HomeObjectComponent,
    HouseholdComponent,
    JobScheduleComponent,
    ReproductiveComponent,
    ReputationComponent,
    RoomClaimComponent,
    RoutineComponent,
    SkillSetComponent,
    WhimComponent,
)

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


class LifeGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_room:
            if generation_wants(ctx, "home"):
                add(
                    HomeComponent(
                        owner_id=generation_generated_id(ctx, "owner"),
                        household_id=generation_generated_id(ctx, "household"),
                    )
                )
            if generation_wants(ctx, "room-claim"):
                add(
                    RoomClaimComponent(
                        claimed_by_id=generation_generated_id(ctx, "claimant"),
                        claimed_at_epoch=ctx.world_epoch,
                    )
                )
        elif ctx.is_character:
            if generation_wants(ctx, "profile", "character-profile") or generation_mentions(
                ctx, "routine", "interest", "hobby", "backstory"
            ):
                add(
                    CharacterProfileComponent(
                        traits=tuple(ctx.generation.tags),
                        interests=tuple(ctx.generation.wants),
                        preferred_routine="generated routine"
                        if generation_mentions(ctx, "routine")
                        else "",
                    )
                )
            if generation_wants(ctx, "aspiration") or generation_mentions(
                ctx, "aspiration", "life goal"
            ):
                add(
                    AspirationComponent(
                        name=ctx.intent or "generated aspiration",
                        milestones=tuple(ctx.generation.tags),
                    )
                )
            if generation_wants(ctx, "career") or generation_mentions(ctx, "career", "job"):
                add(CareerComponent(title=ctx.intent or "Generated Career"))
            if generation_wants(ctx, "job-schedule") or generation_mentions(
                ctx, "shift", "schedule"
            ):
                add(JobScheduleComponent(next_shift_epoch=ctx.world_epoch))
            if generation_wants(ctx, "customer") or generation_mentions(ctx, "customer", "shopper"):
                add(CustomerComponent())
            if generation_wants(ctx, "household") or generation_mentions(
                ctx, "household", "family"
            ):
                add(
                    HouseholdComponent(
                        household_id=generation_generated_id(ctx, "household"),
                        name=ctx.intent or ctx.name,
                    )
                )
            if generation_wants(ctx, "routine") or generation_mentions(ctx, "daily routine"):
                add(
                    RoutineComponent(
                        activity=ctx.intent or "generated routine", next_due_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "reputation") or generation_mentions(
                ctx, "known for", "famous"
            ):
                add(ReputationComponent(known_for=tuple(ctx.generation.tags)))
            if generation_wants(ctx, "skill-set") or generation_mentions(ctx, "skill", "skilled"):
                resource_type = generation_resource_type(ctx)
                add(SkillSetComponent(levels={resource_type: 1}, xp={resource_type: 0.0}))
            if generation_wants(ctx, "reproductive") or generation_mentions(ctx, "fertile"):
                add(ReproductiveComponent(species_group=ctx.species))
        else:
            name = ctx.name
            if generation_wants(ctx, "whim") or generation_mentions(ctx, "whim", "wish"):
                add(WhimComponent(want=name))
            if generation_wants(ctx, "home-object") or generation_mentions(
                ctx, "chair", "bed", "stove", "sofa", "decor", "home"
            ):
                add(HomeObjectComponent(affordance="comfort", decor_score=1.0))
            if generation_wants(ctx, "bill") or generation_mentions(ctx, "bill", "rent", "tax"):
                add(BillComponent(amount=10, reason=ctx.intent or name))
            if generation_wants(ctx, "business-owner") or generation_mentions(
                ctx, "business", "shop", "stall"
            ):
                add(BusinessOwnerComponent(name=name))
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = LifeGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "LifeGenerationEnricher"]
