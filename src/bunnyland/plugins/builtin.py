"""Builtin bunnyland plugins (spec 21.4): core verbs, lifesim, memory.

This module is a plugin source: ``bunnyland_plugins()`` returns the plugins it declares,
exactly as a third-party module would. The world actor still provides the always-on
spine (clock, Action/Focus regen, downed/death); these plugins add the optional verb
surface and mechanics so disabling one removes its components/systems/verbs.
"""

from __future__ import annotations

from ..core.handlers import (
    MoveHandler,
    PutHandler,
    SayHandler,
    SleepHandler,
    TakeHandler,
    TellHandler,
    UseHandler,
    WaitHandler,
    WakeHandler,
    WriteHandler,
)
from ..mechanics.affect import AffectAggregation, AffectReactor
from ..mechanics.barbariansim import (
    ArmorComponent,
    AttackHandler,
    ChallengeHandler,
    DefendHandler,
    DefendingComponent,
    FortificationComponent,
    FortifyHandler,
    PickpocketHandler,
    RaidHandler,
    SparHandler,
    WeaponComponent,
    barbariansim_fragments,
    install_barbariansim,
)
from ..mechanics.colonysim import (
    AssignedTo,
    AssignJobHandler,
    ClaimOwnershipHandler,
    CompleteJobHandler,
    CraftHandler,
    GatherResourceHandler,
    JobComponent,
    Owns,
    RecipeComponent,
    ReleaseOwnershipHandler,
    ReleaseReservationHandler,
    ReservedBy,
    ReserveHandler,
    ResourceNodeComponent,
    ResourceRegenSystem,
    ResourceStackComponent,
    WorkstationComponent,
    colonysim_fragments,
)
from ..mechanics.consumables import ConsumableComponent, DrinkableComponent, FoodComponent
from ..mechanics.dragonsim import (
    AcceptQuestHandler,
    CompleteObjectiveHandler,
    DiscoverLocationHandler,
    DiscoveryComponent,
    FactionComponent,
    FactionJoinedEvent,
    FactionLeftEvent,
    FactionReputationComponent,
    JoinFactionHandler,
    LeaveFactionHandler,
    LocationDiscoveredEvent,
    MemberOf,
    PointOfInterestComponent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestComponent,
    QuestObjectiveCompletedEvent,
    QuestObjectiveComponent,
    QuestRewardComponent,
    QuestStageComponent,
    dragonsim_fragments,
)
from ..mechanics.eat_drink import DrinkHandler, EatHandler
from ..mechanics.environment import (
    CalendarComponent,
    TimeOfDayComponent,
    WeatherComponent,
    environment_fragments,
    install_environment,
)
from ..mechanics.gardensim import (
    CropComponent,
    CropGrewEvent,
    CropGrowthComponent,
    CropHarvestedEvent,
    CropReadyEvent,
    CropWateredEvent,
    CropWitheredEvent,
    FertilizeHandler,
    FertilizerAppliedEvent,
    FertilizerComponent,
    HarvestableComponent,
    HarvestCropHandler,
    PlantHandler,
    SeedComponent,
    SeedPlantedEvent,
    SoilComponent,
    SoilTilledEvent,
    TilledComponent,
    TillHandler,
    WaterCropHandler,
    WateredComponent,
    gardensim_fragments,
    install_gardensim,
)
from ..mechanics.lifesim import (
    AdoptChildHandler,
    AspirationChosenEvent,
    AspirationComponent,
    BirthDueComponent,
    BusinessOpenedEvent,
    BusinessOwnerComponent,
    BusinessPromotedEvent,
    BusinessSaleEvent,
    CareerComponent,
    CareerStartedEvent,
    ChooseAspirationHandler,
    ClaimHomeHandler,
    ClaimRoomHandler,
    CompleteMilestoneHandler,
    CustomerComponent,
    EndPartnershipHandler,
    FindJobHandler,
    GossipSpreadEvent,
    GoToWorkHandler,
    HasRoutine,
    HomeClaimedEvent,
    HomeComponent,
    HouseholdComponent,
    HouseholdFundsComponent,
    HouseholdJoinedEvent,
    JealousOf,
    JealousyTriggeredEvent,
    JobScheduleComponent,
    JoinHouseholdHandler,
    LifeStageComponent,
    MentorshipCompletedEvent,
    MentorSkillHandler,
    MilestoneCompletedEvent,
    MilestoneComponent,
    OpenBusinessHandler,
    OwnsBusiness,
    ParentOf,
    PartnerOf,
    PracticeSkillHandler,
    PregnancyComponent,
    PromoteBusinessHandler,
    PromotionEarnedEvent,
    QuitJobHandler,
    RelationshipStatus,
    RelationshipStatusChangedEvent,
    ReproductiveComponent,
    ReputationComponent,
    ResolveBirthHandler,
    RoomClaimComponent,
    RoomClaimedEvent,
    RoutineComponent,
    RoutineDueEvent,
    RoutineSetEvent,
    SellItemHandler,
    SetRelationshipStatusHandler,
    SetRoutineHandler,
    SkillLeveledEvent,
    SkillSetComponent,
    SkillXPChangedEvent,
    SpreadGossipHandler,
    StartPartnershipHandler,
    StartPregnancyHandler,
    StudySkillHandler,
    WitnessRomanceHandler,
    WorkShiftCompletedEvent,
    install_lifesim,
    lifesim_fragments,
)
from ..mechanics.mechanisms import install_mechanisms
from ..mechanics.needs import (
    HungerComponent,
    HungerSystem,
    ThirstComponent,
    ThirstSystem,
    need_fragments,
)
from ..mechanics.persona import (
    GoalComponent,
    PreferenceComponent,
    TraitSetComponent,
    persona_fragments,
)
from ..mechanics.policy import (
    CharacterBoundaryComponent,
    WorldPolicyComponent,
    install_policy,
)
from ..mechanics.social import SocialBond, install_social, relationship_fragments
from ..memory import install_memory
from ..worldgen.generators import WorldGenerator, oneshot_generator, recursive_generator
from .model import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    RuntimeContribution,
)

CORE_VERBS = "bunnyland.core_verbs"
LIFESIM = "bunnyland.lifesim"
MEMORY = "bunnyland.memory"
WORLDGEN = "bunnyland.worldgen"
ENVIRONMENT = "bunnyland.environment"
MECHANISMS = "bunnyland.mechanisms"
SOCIAL = "bunnyland.social"
POLICY = "bunnyland.policy"
PERSONA = "bunnyland.persona"
COLONYSIM = "bunnyland.colonysim"
BARBARIANSIM = "bunnyland.barbariansim"
GARDENSIM = "bunnyland.gardensim"
DRAGONSIM = "bunnyland.dragonsim"


def _install_affect(actor) -> None:
    reactor = AffectReactor(actor.world)
    reactor.subscribe(actor.bus)
    actor.register_consequence(AffectAggregation())


def core_verbs_plugin() -> Plugin:
    return Plugin(
        id=CORE_VERBS,
        name="Core Verbs",
        commands=CommandContribution(
            action_handlers=(
                MoveHandler,
                TakeHandler,
                PutHandler,
                UseHandler,
                WriteHandler,
                SleepHandler,
                WakeHandler,
                WaitHandler,
                SayHandler,
                TellHandler,
            )
        ),
    )


def lifesim_plugin() -> Plugin:
    return Plugin(
        id=LIFESIM,
        name="Life Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                HungerComponent,
                ThirstComponent,
                FoodComponent,
                DrinkableComponent,
                ConsumableComponent,
                AspirationComponent,
                MilestoneComponent,
                HouseholdFundsComponent,
                CareerComponent,
                JobScheduleComponent,
                BusinessOwnerComponent,
                CustomerComponent,
                HouseholdComponent,
                HomeComponent,
                RoomClaimComponent,
                RoutineComponent,
                ReputationComponent,
                SkillSetComponent,
                LifeStageComponent,
                ReproductiveComponent,
                PregnancyComponent,
                BirthDueComponent,
            ),
            edges=(ParentOf, HasRoutine, OwnsBusiness, PartnerOf, RelationshipStatus, JealousOf),
            systems=(HungerSystem, ThirstSystem),
        ),
        commands=CommandContribution(
            action_handlers=(
                EatHandler,
                DrinkHandler,
                ChooseAspirationHandler,
                CompleteMilestoneHandler,
                PracticeSkillHandler,
                StudySkillHandler,
                MentorSkillHandler,
                FindJobHandler,
                GoToWorkHandler,
                QuitJobHandler,
                OpenBusinessHandler,
                SellItemHandler,
                PromoteBusinessHandler,
                JoinHouseholdHandler,
                ClaimHomeHandler,
                ClaimRoomHandler,
                SetRoutineHandler,
                SetRelationshipStatusHandler,
                SpreadGossipHandler,
                WitnessRomanceHandler,
                StartPartnershipHandler,
                EndPartnershipHandler,
                StartPregnancyHandler,
                ResolveBirthHandler,
                AdoptChildHandler,
            ),
            typed_events=(
                AspirationChosenEvent,
                MilestoneCompletedEvent,
                SkillXPChangedEvent,
                SkillLeveledEvent,
                MentorshipCompletedEvent,
                CareerStartedEvent,
                WorkShiftCompletedEvent,
                PromotionEarnedEvent,
                BusinessOpenedEvent,
                BusinessSaleEvent,
                BusinessPromotedEvent,
                HouseholdJoinedEvent,
                HomeClaimedEvent,
                RoomClaimedEvent,
                RoutineSetEvent,
                RoutineDueEvent,
                RelationshipStatusChangedEvent,
                GossipSpreadEvent,
                JealousyTriggeredEvent,
            )
        ),
        runtime=RuntimeContribution(service_factories=(_install_affect, install_lifesim)),
        content=ContentContribution(prompt_fragments=(need_fragments, lifesim_fragments)),
    )


def memory_plugin() -> Plugin:
    return Plugin(
        id=MEMORY,
        name="Memory",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        runtime=RuntimeContribution(service_factories=(_memory_factory,)),
    )


def _memory_factory(actor) -> None:
    install_memory(actor)


def _environment_factory(actor) -> None:
    install_environment(actor)


def environment_plugin() -> Plugin:
    return Plugin(
        id=ENVIRONMENT,
        name="Environment",
        ecs=EcsContribution(
            components=(CalendarComponent, TimeOfDayComponent, WeatherComponent)
        ),
        runtime=RuntimeContribution(service_factories=(_environment_factory,)),
        content=ContentContribution(prompt_fragments=(environment_fragments,)),
    )


def _mechanisms_factory(actor) -> None:
    install_mechanisms(actor)


def mechanisms_plugin() -> Plugin:
    return Plugin(
        id=MECHANISMS,
        name="Mechanisms",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        runtime=RuntimeContribution(service_factories=(_mechanisms_factory,)),
    )


def _social_factory(actor) -> None:
    install_social(actor)


def social_plugin() -> Plugin:
    return Plugin(
        id=SOCIAL,
        name="Social Bonds",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(edges=(SocialBond,)),
        runtime=RuntimeContribution(service_factories=(_social_factory,)),
        content=ContentContribution(prompt_fragments=(relationship_fragments,)),
    )


def _policy_factory(actor) -> None:
    install_policy(actor)


def policy_plugin() -> Plugin:
    return Plugin(
        id=POLICY,
        name="Policy & Boundaries",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(components=(WorldPolicyComponent, CharacterBoundaryComponent)),
        runtime=RuntimeContribution(service_factories=(_policy_factory,)),
    )


def persona_plugin() -> Plugin:
    return Plugin(
        id=PERSONA,
        name="Persona",
        ecs=EcsContribution(
            components=(TraitSetComponent, PreferenceComponent, GoalComponent)
        ),
        content=ContentContribution(prompt_fragments=(persona_fragments,)),
    )


def worldgen_plugin() -> Plugin:
    return Plugin(
        id=WORLDGEN,
        name="World Generators",
        content=ContentContribution(
            world_generators=(
                WorldGenerator(
                    "oneshot", oneshot_generator, "single LLM proposal, instantiated at once"
                ),
                WorldGenerator(
                    "recursive", recursive_generator, "breadth-first graph, grown room-by-room"
                ),
            )
        ),
    )


def colonysim_plugin() -> Plugin:
    return Plugin(
        id=COLONYSIM,
        name="Colony Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                ResourceNodeComponent,
                ResourceStackComponent,
                WorkstationComponent,
                RecipeComponent,
                JobComponent,
            ),
            edges=(ReservedBy, AssignedTo, Owns),
            systems=(ResourceRegenSystem,),
        ),
        commands=CommandContribution(
            action_handlers=(
                ReserveHandler,
                ReleaseReservationHandler,
                GatherResourceHandler,
                CraftHandler,
                AssignJobHandler,
                CompleteJobHandler,
                ClaimOwnershipHandler,
                ReleaseOwnershipHandler,
            )
        ),
        content=ContentContribution(prompt_fragments=(colonysim_fragments,)),
    )


def barbariansim_plugin() -> Plugin:
    return Plugin(
        id=BARBARIANSIM,
        name="Barbarian Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                WeaponComponent,
                ArmorComponent,
                DefendingComponent,
                FortificationComponent,
            )
        ),
        commands=CommandContribution(
            action_handlers=(
                AttackHandler,
                SparHandler,
                DefendHandler,
                ChallengeHandler,
                FortifyHandler,
                RaidHandler,
                PickpocketHandler,
            )
        ),
        runtime=RuntimeContribution(service_factories=(install_barbariansim,)),
        content=ContentContribution(prompt_fragments=(barbariansim_fragments,)),
    )


def gardensim_plugin() -> Plugin:
    return Plugin(
        id=GARDENSIM,
        name="Garden Sim",
        dependencies=DependencyContribution(
            requires=(CORE_VERBS,),
            recommends=(ENVIRONMENT, COLONYSIM),
        ),
        ecs=EcsContribution(
            components=(
                SoilComponent,
                TilledComponent,
                WateredComponent,
                FertilizerComponent,
                SeedComponent,
                CropComponent,
                CropGrowthComponent,
                HarvestableComponent,
            )
        ),
        commands=CommandContribution(
            action_handlers=(
                TillHandler,
                PlantHandler,
                WaterCropHandler,
                FertilizeHandler,
                HarvestCropHandler,
            ),
            typed_events=(
                SoilTilledEvent,
                SeedPlantedEvent,
                CropWateredEvent,
                FertilizerAppliedEvent,
                CropGrewEvent,
                CropReadyEvent,
                CropWitheredEvent,
                CropHarvestedEvent,
            ),
        ),
        runtime=RuntimeContribution(service_factories=(install_gardensim,)),
        content=ContentContribution(prompt_fragments=(gardensim_fragments,)),
    )


def dragonsim_plugin() -> Plugin:
    return Plugin(
        id=DRAGONSIM,
        name="Dragon Sim",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        ecs=EcsContribution(
            components=(
                PointOfInterestComponent,
                DiscoveryComponent,
                QuestComponent,
                QuestStageComponent,
                QuestObjectiveComponent,
                QuestRewardComponent,
                FactionComponent,
                FactionReputationComponent,
            ),
            edges=(MemberOf,),
        ),
        commands=CommandContribution(
            action_handlers=(
                DiscoverLocationHandler,
                AcceptQuestHandler,
                CompleteObjectiveHandler,
                JoinFactionHandler,
                LeaveFactionHandler,
            ),
            typed_events=(
                LocationDiscoveredEvent,
                QuestAcceptedEvent,
                QuestObjectiveCompletedEvent,
                QuestCompletedEvent,
                FactionJoinedEvent,
                FactionLeftEvent,
            ),
        ),
        content=ContentContribution(prompt_fragments=(dragonsim_fragments,)),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [
        core_verbs_plugin(),
        lifesim_plugin(),
        memory_plugin(),
        worldgen_plugin(),
        environment_plugin(),
        mechanisms_plugin(),
        social_plugin(),
        policy_plugin(),
        persona_plugin(),
        colonysim_plugin(),
        barbariansim_plugin(),
        gardensim_plugin(),
        dragonsim_plugin(),
    ]


__all__ = [
    "BARBARIANSIM",
    "CORE_VERBS",
    "COLONYSIM",
    "DRAGONSIM",
    "ENVIRONMENT",
    "GARDENSIM",
    "LIFESIM",
    "MECHANISMS",
    "MEMORY",
    "PERSONA",
    "POLICY",
    "SOCIAL",
    "WORLDGEN",
    "barbariansim_plugin",
    "bunnyland_plugins",
    "colonysim_plugin",
    "core_verbs_plugin",
    "dragonsim_plugin",
    "environment_plugin",
    "gardensim_plugin",
    "lifesim_plugin",
    "mechanisms_plugin",
    "memory_plugin",
    "persona_plugin",
    "policy_plugin",
    "social_plugin",
    "worldgen_plugin",
]
