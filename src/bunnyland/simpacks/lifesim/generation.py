"""Declarative lifesim generation contributions."""

from ...core.ecs import parse_entity_id
from ...core.generation import (
    GenerationDelta,
    GenerationEdge,
    GenerationRequest,
    GenerationTarget,
)
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
    ClaimsRoom,
    CustomerComponent,
    HomeObjectComponent,
    HouseholdComponent,
    JobScheduleComponent,
    OwnsHome,
    ReproductiveComponent,
    ReputationComponent,
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


class LifeGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}
        edges = []

        def add(component):
            components[type(component)] = component

        if ctx.is_character:
            room_target = (
                ctx.room_id
                if parse_entity_id(ctx.room_id) is not None
                else GenerationTarget(ctx.room_key)
            )
            household = next(
                (
                    component
                    for component in request.context.get("base_components", ())
                    if isinstance(component, HouseholdComponent)
                ),
                None,
            )
            if generation_wants(ctx, "bunnyland.lifesim.home"):
                edges.append(
                    GenerationEdge(
                        OwnsHome(
                            household_id=household.household_id if household is not None else None
                        ),
                        room_target,
                    )
                )
            if generation_wants(ctx, "bunnyland.lifesim.room-claim"):
                edges.append(
                    GenerationEdge(ClaimsRoom(claimed_at_epoch=ctx.world_epoch), room_target)
                )
            if generation_wants(
                ctx, "bunnyland.lifesim.profile", "bunnyland.lifesim.character-profile"
            ) or generation_mentions(ctx, "routine", "interest", "hobby", "backstory"):
                add(
                    CharacterProfileComponent(
                        traits=tuple(ctx.generation.tags),
                        interests=tuple(ctx.generation.wants),
                        preferred_routine="generated routine"
                        if generation_mentions(ctx, "routine")
                        else "",
                    )
                )
            if generation_wants(ctx, "bunnyland.lifesim.aspiration") or generation_mentions(
                ctx, "aspiration", "life goal"
            ):
                add(
                    AspirationComponent(
                        name=ctx.intent or "generated aspiration",
                        milestones=tuple(ctx.generation.tags),
                    )
                )
            if generation_wants(ctx, "bunnyland.lifesim.career") or generation_mentions(
                ctx, "career", "job"
            ):
                add(CareerComponent(title=ctx.intent or "Generated Career"))
            if generation_wants(ctx, "bunnyland.lifesim.job-schedule") or generation_mentions(
                ctx, "shift", "schedule"
            ):
                add(JobScheduleComponent(next_shift_epoch=ctx.world_epoch))
            if generation_wants(ctx, "bunnyland.lifesim.customer") or generation_mentions(
                ctx, "customer", "shopper"
            ):
                add(CustomerComponent())
            if generation_wants(ctx, "bunnyland.lifesim.household") or generation_mentions(
                ctx, "household", "family"
            ):
                add(
                    HouseholdComponent(
                        household_id=generation_generated_id(ctx, "household"),
                        name=ctx.intent or ctx.name,
                    )
                )
            if generation_wants(ctx, "bunnyland.lifesim.routine") or generation_mentions(
                ctx, "daily routine"
            ):
                add(
                    RoutineComponent(
                        activity=ctx.intent or "generated routine", next_due_epoch=ctx.world_epoch
                    )
                )
            if generation_wants(ctx, "bunnyland.lifesim.reputation") or generation_mentions(
                ctx, "known for", "famous"
            ):
                add(ReputationComponent(known_for=tuple(ctx.generation.tags)))
            if generation_wants(ctx, "bunnyland.lifesim.skill-set") or generation_mentions(
                ctx, "skill", "skilled"
            ):
                resource_type = generation_resource_type(ctx)
                add(SkillSetComponent(levels={resource_type: 1}, xp={resource_type: 0.0}))
            if generation_wants(ctx, "bunnyland.lifesim.reproductive") or generation_mentions(
                ctx, "fertile"
            ):
                add(ReproductiveComponent(species_group=ctx.species))
        elif not ctx.is_room:
            name = ctx.name
            if generation_wants(ctx, "bunnyland.lifesim.whim") or generation_mentions(
                ctx, "whim", "wish"
            ):
                add(WhimComponent(want=name))
            if generation_wants(ctx, "bunnyland.lifesim.home-object") or generation_mentions(
                ctx, "chair", "bed", "stove", "sofa", "decor", "home"
            ):
                add(HomeObjectComponent(affordance="comfort", decor_score=1.0))
            if generation_wants(ctx, "bunnyland.lifesim.bill") or generation_mentions(
                ctx, "bill", "rent", "tax"
            ):
                add(BillComponent(amount=10, reason=ctx.intent or name))
            if generation_wants(ctx, "bunnyland.lifesim.business-owner") or generation_mentions(
                ctx, "business", "shop", "stall"
            ):
                add(BusinessOwnerComponent(name=name))
        return GenerationDelta(
            components=tuple(components.values()),
            edges=tuple(edges),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = LifeGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "LifeGenerationEnricher"]
