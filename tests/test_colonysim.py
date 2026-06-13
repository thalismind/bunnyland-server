"""Tests for colony-sim reservations, gathering, and crafting."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    AffectComponent,
    AffectVector,
    BleedingComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DownedComponent,
    HandlerContext,
    HasInjury,
    HealthComponent,
    IdentityComponent,
    InjuryComponent,
    Lane,
    PortableComponent,
    SleepingComponent,
    build_submitted_command,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import (
    CommandRejectedEvent,
    ItemCraftedEvent,
    ItemForbiddenEvent,
    ItemHauledEvent,
    JobAssignedEvent,
    JobCompletedEvent,
    OwnershipClaimedEvent,
    OwnershipReleasedEvent,
    ResourceGatheredEvent,
    StackMergedEvent,
    StackSplitEvent,
    StockpileCreatedEvent,
    StorageFilterChangedEvent,
)
from bunnyland.mechanics import colonysim
from bunnyland.mechanics.colonysim import (
    AllowedAreaComponent,
    AllowItemHandler,
    AssignedTo,
    AssignJobHandler,
    BakeHandler,
    BedRestComponent,
    BodyPartHealthComponent,
    CaravanComponent,
    CaravanFormedEvent,
    ClaimOwnershipHandler,
    ColonyIncidentComponent,
    ColonyIncidentResolvedEvent,
    ColonySimComponent,
    ColonyWealthComponent,
    ColonyWealthConsequence,
    CompleteJobHandler,
    CompleteTradeHandler,
    CraftHandler,
    CreateStockpileHandler,
    FactionRelationComponent,
    ForbiddenComponent,
    ForbidItemHandler,
    FormCaravanHandler,
    GatherResourceHandler,
    HasBodyPart,
    HaulItemHandler,
    InfectionComponent,
    JobBillComponent,
    JobBillProgressedEvent,
    JobComponent,
    MedicalBedComponent,
    MedicalRecoveryConsequence,
    MedicineComponent,
    MentalStateComponent,
    MentalStateConsequence,
    MergeStackHandler,
    Owns,
    PawnProfileComponent,
    PawnProfileUpdatedEvent,
    PerformSurgeryHandler,
    PrisonerComponent,
    PrisonerPolicySetEvent,
    ProgressJobBillHandler,
    ProstheticComponent,
    RecipeComponent,
    RecruitmentProgressedEvent,
    RecruitPrisonerHandler,
    ReleaseOwnershipHandler,
    ReleaseReservationHandler,
    RescueToBedHandler,
    ResearchProgressedEvent,
    ResearchProjectComponent,
    ResearchProjectHandler,
    ReservedBy,
    ReserveHandler,
    ResolveColonyIncidentHandler,
    ResourceNodeComponent,
    ResourceRegenSystem,
    ResourceStackComponent,
    RoomQualityComponent,
    RoomQualityConsequence,
    RoomRoleComponent,
    RoomStatComponent,
    SetAllowedAreaHandler,
    SetPrisonerPolicyHandler,
    SetStorageFilterHandler,
    SetWorkPriorityHandler,
    SplitStackHandler,
    StockpileComponent,
    StorageFilterComponent,
    SurgeryBillComponent,
    SurgeryPerformedEvent,
    TechUnlockComponent,
    TechUnlockedEvent,
    TendWoundHandler,
    TradeCompletedEvent,
    TradeOfferComponent,
    UpdatePawnProfileHandler,
    WorkPriorityComponent,
    WorkstationComponent,
    colonysim_fragments,
)
from bunnyland.mechanics.consumables import ConsumableComponent, DrinkableComponent, FoodComponent
from bunnyland.mechanics.meter import Meter
from bunnyland.mechanics.needs import FunNeedComponent
from bunnyland.prompts import ComponentPromptContext, PromptPerspective

HOUR = 3600.0


def _install(actor):
    if not list(actor.world.query().with_all([ColonySimComponent]).execute_entities()):
        spawn_entity(actor.world, [ColonySimComponent()])
    actor.register_handler(ReserveHandler())
    actor.register_handler(ReleaseReservationHandler())
    actor.register_handler(GatherResourceHandler())
    actor.register_handler(CreateStockpileHandler())
    actor.register_handler(SetStorageFilterHandler())
    actor.register_handler(ForbidItemHandler())
    actor.register_handler(AllowItemHandler())
    actor.register_handler(HaulItemHandler())
    actor.register_handler(SplitStackHandler())
    actor.register_handler(MergeStackHandler())
    actor.register_handler(CraftHandler())
    actor.register_handler(BakeHandler())
    actor.register_handler(SetWorkPriorityHandler())
    actor.register_handler(SetAllowedAreaHandler())
    actor.register_handler(UpdatePawnProfileHandler())
    actor.register_handler(ProgressJobBillHandler())
    actor.register_handler(SetPrisonerPolicyHandler())
    actor.register_handler(RecruitPrisonerHandler())
    actor.register_handler(ResearchProjectHandler())
    actor.register_handler(ResolveColonyIncidentHandler())
    actor.register_handler(CompleteTradeHandler())
    actor.register_handler(FormCaravanHandler())
    actor.register_handler(PerformSurgeryHandler())
    actor.register_handler(TendWoundHandler())
    actor.register_handler(RescueToBedHandler())
    actor.register_handler(AssignJobHandler())
    actor.register_handler(CompleteJobHandler())
    actor.register_handler(ClaimOwnershipHandler())
    actor.register_handler(ReleaseOwnershipHandler())
    actor.world.register_system(ResourceRegenSystem())
    actor.register_consequence(RoomQualityConsequence())
    actor.register_consequence(ColonyWealthConsequence())
    actor.register_consequence(MedicalRecoveryConsequence())
    actor.register_consequence(MentalStateConsequence())


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _handler_cmd(scenario, command_type, *, character_id=None, **payload):
    return build_submitted_command(
        character_id=str(scenario.character) if character_id is None else character_id,
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _resource_node(scenario, resource_type="wood", current=3):
    node = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{resource_type} patch", kind="resource_node"),
            ResourceNodeComponent(resource_type=resource_type, current=current, maximum=current),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), node.id
    )
    return node.id


def _stack(scenario, resource_type, quantity):
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{resource_type} x{quantity}", kind="resource"),
            ResourceStackComponent(resource_type=resource_type, quantity=quantity),
            PortableComponent(can_pick_up=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), item.id
    )
    return item.id


def _stockpile(scenario, capacity=10, allowed_types=()):
    stockpile = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="stockpile", kind="stockpile"),
            StockpileComponent(capacity=capacity),
            StorageFilterComponent(allowed_types=tuple(allowed_types)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), stockpile.id
    )
    return stockpile.id


def _job(scenario, job_type="haul", priority=5):
    job = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{job_type} job", kind="job"),
            JobComponent(job_type=job_type, priority=priority),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), job.id
    )
    return job.id


def test_colonysim_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Other", kind="character")],
    )

    node = _resource_node(scenario, current=2)
    empty_node = _resource_node(scenario, resource_type="stone", current=0)
    reserved_node = _resource_node(scenario, resource_type="berries", current=2)
    scenario.actor.world.get_entity(reserved_node).add_relationship(
        ReservedBy(since_epoch=0), other.id
    )
    already_reserved_node = _resource_node(scenario, resource_type="clay", current=2)
    scenario.actor.world.get_entity(already_reserved_node).add_relationship(
        ReservedBy(since_epoch=0), scenario.character
    )

    distant_node = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant ore", kind="resource_node"),
            ResourceNodeComponent(resource_type="ore", current=2, maximum=2),
        ],
    )
    distant_target = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="distant crate", kind="prop")],
    )
    distant_job = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant job", kind="job"),
            JobComponent(job_type="haul", priority=1),
        ],
    )
    room_b = scenario.actor.world.get_entity(scenario.room_b)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_node.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_target.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_job.id)

    complete_job = _job(scenario, job_type="complete")
    replace_component(
        scenario.actor.world.get_entity(complete_job),
        JobComponent(job_type="complete", priority=1, completed=True),
    )
    assigned_job = _job(scenario, job_type="assigned")
    scenario.actor.world.get_entity(assigned_job).add_relationship(
        AssignedTo(since_epoch=0), other.id
    )
    own_job = _job(scenario, job_type="own")
    scenario.actor.world.get_entity(own_job).add_relationship(
        AssignedTo(since_epoch=0), scenario.character
    )
    unassigned_job = _job(scenario, job_type="unassigned")

    owned_target = _resource_node(scenario, resource_type="owned", current=1)
    character.add_relationship(Owns(since_epoch=0), owned_target)
    other_owned_target = _resource_node(scenario, resource_type="other-owned", current=1)
    other.add_relationship(Owns(since_epoch=0), other_owned_target)

    spawn_entity(
        scenario.actor.world,
        [RecipeComponent(recipe_id="wood-tool", inputs={"wood": 1}, outputs={"tool": 1})],
    )
    spawn_entity(
        scenario.actor.world,
        [
            RecipeComponent(
                recipe_id="bench-tool",
                inputs={},
                outputs={"tool": 1},
                required_station="bench",
            )
        ],
    )

    cases = [
        (
            ReserveHandler(),
            _handler_cmd(scenario, "reserve", target_id="not-an-id"),
            "invalid character or target id",
        ),
        (
            ReserveHandler(),
            _handler_cmd(scenario, "reserve", target_id="entity_999"),
            "target does not exist",
        ),
        (
            ReserveHandler(),
            _handler_cmd(scenario, "reserve", target_id=str(distant_target.id)),
            "target is not reachable",
        ),
        (
            ReserveHandler(),
            _handler_cmd(scenario, "reserve", target_id=str(reserved_node)),
            "target is reserved",
        ),
        (
            ReserveHandler(),
            _handler_cmd(scenario, "reserve", target_id=str(already_reserved_node)),
            "already reserved",
        ),
        (
            ReleaseReservationHandler(),
            _handler_cmd(scenario, "release-reservation", target_id="not-an-id"),
            "invalid character or target id",
        ),
        (
            ReleaseReservationHandler(),
            _handler_cmd(scenario, "release-reservation", target_id="entity_999"),
            "target does not exist",
        ),
        (
            ReleaseReservationHandler(),
            _handler_cmd(scenario, "release-reservation", target_id=str(node)),
            "not reserved by you",
        ),
        (
            GatherResourceHandler(),
            _handler_cmd(scenario, "gather-resource", node_id="not-an-id"),
            "invalid character or resource node id",
        ),
        (
            GatherResourceHandler(),
            _handler_cmd(scenario, "gather-resource", node_id=str(node), quantity=0),
            "quantity must be positive",
        ),
        (
            GatherResourceHandler(),
            _handler_cmd(scenario, "gather-resource", node_id="entity_999"),
            "resource node does not exist",
        ),
        (
            GatherResourceHandler(),
            _handler_cmd(scenario, "gather-resource", node_id=str(distant_node.id)),
            "resource node is not reachable",
        ),
        (
            GatherResourceHandler(),
            _handler_cmd(scenario, "gather-resource", node_id=str(scenario.room_a)),
            "target is not a resource node",
        ),
        (
            GatherResourceHandler(),
            _handler_cmd(scenario, "gather-resource", node_id=str(reserved_node)),
            "resource node is reserved",
        ),
        (
            GatherResourceHandler(),
            _handler_cmd(scenario, "gather-resource", node_id=str(empty_node)),
            "not enough resource",
        ),
        (
            CraftHandler(),
            _handler_cmd(scenario, "craft", character_id="not-an-id", recipe_id="wood-tool"),
            "invalid character id",
        ),
        (
            CraftHandler(),
            _handler_cmd(scenario, "craft", recipe_id=" "),
            "missing recipe id",
        ),
        (
            CraftHandler(),
            _handler_cmd(scenario, "craft", recipe_id="missing"),
            "recipe does not exist",
        ),
        (
            CraftHandler(),
            _handler_cmd(scenario, "craft", recipe_id="bench-tool"),
            "required workstation is not reachable",
        ),
        (
            CraftHandler(),
            _handler_cmd(scenario, "craft", recipe_id="wood-tool"),
            "missing recipe inputs",
        ),
        (
            AssignJobHandler(),
            _handler_cmd(scenario, "assign-job", job_id="not-an-id"),
            "invalid character or job id",
        ),
        (
            AssignJobHandler(),
            _handler_cmd(scenario, "assign-job", job_id="entity_999"),
            "job does not exist",
        ),
        (
            AssignJobHandler(),
            _handler_cmd(scenario, "assign-job", job_id=str(distant_job.id)),
            "job is not reachable",
        ),
        (
            AssignJobHandler(),
            _handler_cmd(scenario, "assign-job", job_id=str(scenario.room_a)),
            "target is not a job",
        ),
        (
            AssignJobHandler(),
            _handler_cmd(scenario, "assign-job", job_id=str(complete_job)),
            "job is already complete",
        ),
        (
            AssignJobHandler(),
            _handler_cmd(scenario, "assign-job", job_id=str(assigned_job)),
            "job is assigned",
        ),
        (
            AssignJobHandler(),
            _handler_cmd(scenario, "assign-job", job_id=str(own_job)),
            "job already assigned to you",
        ),
        (
            CompleteJobHandler(),
            _handler_cmd(scenario, "complete-job", job_id="not-an-id"),
            "invalid character or job id",
        ),
        (
            CompleteJobHandler(),
            _handler_cmd(scenario, "complete-job", job_id="entity_999"),
            "job does not exist",
        ),
        (
            CompleteJobHandler(),
            _handler_cmd(scenario, "complete-job", job_id=str(scenario.room_a)),
            "target is not a job",
        ),
        (
            CompleteJobHandler(),
            _handler_cmd(scenario, "complete-job", job_id=str(unassigned_job)),
            "job is not assigned to you",
        ),
        (
            ClaimOwnershipHandler(),
            _handler_cmd(scenario, "claim-ownership", target_id="not-an-id"),
            "invalid character or target id",
        ),
        (
            ClaimOwnershipHandler(),
            _handler_cmd(scenario, "claim-ownership", target_id="entity_999"),
            "target does not exist",
        ),
        (
            ClaimOwnershipHandler(),
            _handler_cmd(scenario, "claim-ownership", target_id=str(distant_target.id)),
            "target is not reachable",
        ),
        (
            ClaimOwnershipHandler(),
            _handler_cmd(scenario, "claim-ownership", target_id=str(owned_target)),
            "already owned by you",
        ),
        (
            ClaimOwnershipHandler(),
            _handler_cmd(scenario, "claim-ownership", target_id=str(other_owned_target)),
            "target is already owned",
        ),
        (
            ReleaseOwnershipHandler(),
            _handler_cmd(scenario, "release-ownership", target_id="not-an-id"),
            "invalid character or target id",
        ),
        (
            ReleaseOwnershipHandler(),
            _handler_cmd(scenario, "release-ownership", target_id="entity_999"),
            "target does not exist",
        ),
        (
            ReleaseOwnershipHandler(),
            _handler_cmd(scenario, "release-ownership", target_id=str(node)),
            "not owned by you",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_colonysim_stockpile_and_stack_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    stack = _stack(scenario, "wood", 3)
    stone = _stack(scenario, "stone", 1)
    stockpile = _stockpile(scenario, capacity=2, allowed_types=("wood",))
    non_stack = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="crate", kind="prop")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), non_stack.id
    )
    distant_stack = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant wood", kind="resource"),
            ResourceStackComponent(resource_type="wood", quantity=1),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant_stack.id
    )

    forbidden_stack = _stack(scenario, "wood", 1)
    scenario.actor.world.get_entity(forbidden_stack).add_component(ForbiddenComponent())

    cases = [
        (
            CreateStockpileHandler(),
            _handler_cmd(scenario, "create-stockpile", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            CreateStockpileHandler(),
            _handler_cmd(scenario, "create-stockpile", capacity=0),
            "capacity must be positive",
        ),
        (
            SetStorageFilterHandler(),
            _handler_cmd(scenario, "set-storage-filter", stockpile_id="not-an-id"),
            "invalid character or stockpile id",
        ),
        (
            SetStorageFilterHandler(),
            _handler_cmd(scenario, "set-storage-filter", stockpile_id="entity_999"),
            "stockpile does not exist",
        ),
        (
            SetStorageFilterHandler(),
            _handler_cmd(scenario, "set-storage-filter", stockpile_id=str(distant_stack.id)),
            "stockpile is not reachable",
        ),
        (
            SetStorageFilterHandler(),
            _handler_cmd(scenario, "set-storage-filter", stockpile_id=str(stack)),
            "target is not a stockpile",
        ),
        (
            ForbidItemHandler(),
            _handler_cmd(scenario, "forbid-item", item_id="not-an-id"),
            "invalid character or item id",
        ),
        (
            ForbidItemHandler(),
            _handler_cmd(scenario, "forbid-item", item_id="entity_999"),
            "item does not exist",
        ),
        (
            ForbidItemHandler(),
            _handler_cmd(scenario, "forbid-item", item_id=str(distant_stack.id)),
            "item is not reachable",
        ),
        (
            AllowItemHandler(),
            _handler_cmd(scenario, "allow-item", item_id="not-an-id"),
            "invalid character or item id",
        ),
        (
            AllowItemHandler(),
            _handler_cmd(scenario, "allow-item", item_id="entity_999"),
            "item does not exist",
        ),
        (
            AllowItemHandler(),
            _handler_cmd(scenario, "allow-item", item_id=str(distant_stack.id)),
            "item is not reachable",
        ),
        (
            AllowItemHandler(),
            _handler_cmd(scenario, "allow-item", item_id=str(stack)),
            "item is not forbidden",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id="not-an-id",
                target_container_id=str(stockpile),
            ),
            "invalid character, item, or target container id",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id="entity_999",
                target_container_id=str(stockpile),
            ),
            "item does not exist",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id=str(stack),
                target_container_id="entity_999",
            ),
            "target container does not exist",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id=str(distant_stack.id),
                target_container_id=str(stockpile),
            ),
            "item is not reachable",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id=str(stack),
                target_container_id=str(distant_stack.id),
            ),
            "target container is not reachable",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(scenario, "haul-item", item_id=str(stack), target_container_id=str(stack)),
            "item cannot contain itself",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id=str(forbidden_stack),
                target_container_id=str(stockpile),
            ),
            "item is forbidden",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id=str(stone),
                target_container_id=str(stockpile),
            ),
            "item does not match storage filter",
        ),
        (
            HaulItemHandler(),
            _handler_cmd(
                scenario,
                "haul-item",
                item_id=str(stack),
                target_container_id=str(stockpile),
            ),
            "stockpile is full",
        ),
        (
            SplitStackHandler(),
            _handler_cmd(scenario, "split-stack", item_id="not-an-id"),
            "invalid character or item id",
        ),
        (
            SplitStackHandler(),
            _handler_cmd(scenario, "split-stack", item_id=str(stack), quantity=0),
            "quantity must be positive",
        ),
        (
            SplitStackHandler(),
            _handler_cmd(scenario, "split-stack", item_id="entity_999"),
            "stack does not exist",
        ),
        (
            SplitStackHandler(),
            _handler_cmd(scenario, "split-stack", item_id=str(distant_stack.id)),
            "stack is not reachable",
        ),
        (
            SplitStackHandler(),
            _handler_cmd(scenario, "split-stack", item_id=str(non_stack.id)),
            "target is not a resource stack",
        ),
        (
            SplitStackHandler(),
            _handler_cmd(scenario, "split-stack", item_id=str(stone), quantity=1),
            "quantity must be smaller than stack",
        ),
        (
            MergeStackHandler(),
            _handler_cmd(scenario, "merge-stack", source_id="not-an-id", target_id=str(stack)),
            "invalid character, source, or target id",
        ),
        (
            MergeStackHandler(),
            _handler_cmd(scenario, "merge-stack", source_id=str(stack), target_id=str(stack)),
            "source and target must differ",
        ),
        (
            MergeStackHandler(),
            _handler_cmd(scenario, "merge-stack", source_id="entity_999", target_id=str(stack)),
            "source stack does not exist",
        ),
        (
            MergeStackHandler(),
            _handler_cmd(scenario, "merge-stack", source_id=str(stack), target_id="entity_999"),
            "target stack does not exist",
        ),
        (
            MergeStackHandler(),
            _handler_cmd(
                scenario,
                "merge-stack",
                source_id=str(distant_stack.id),
                target_id=str(stack),
            ),
            "stacks are not reachable",
        ),
        (
            MergeStackHandler(),
            _handler_cmd(
                scenario,
                "merge-stack",
                source_id=str(non_stack.id),
                target_id=str(stack),
            ),
            "both targets must be resource stacks",
        ),
        (
            MergeStackHandler(),
            _handler_cmd(scenario, "merge-stack", source_id=str(stone), target_id=str(stack)),
            "resource types do not match",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_colonysim_stockpile_helpers_cover_filter_and_container_branches():
    scenario = build_scenario()
    _install(scenario.actor)
    colonysim.install_colonysim(scenario.actor)
    colonysim.install_colonysim(scenario.actor)
    assert len(
        list(scenario.actor.world.query().with_all([ColonySimComponent]).execute_entities())
    ) == 1

    stockpile = scenario.actor.world.get_entity(_stockpile(scenario, allowed_types=()))
    stack = scenario.actor.world.get_entity(_stack(scenario, "wood", 2))
    non_stack = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="chair", kind="prop")],
    )
    stockpile.add_relationship(Contains(mode=ContainmentMode.CONTAINER), non_stack.id)

    assert colonysim._parse_types(None) == ()
    assert colonysim._parse_types(7) == ("7",)
    assert colonysim._stockpile_load(scenario.actor.world, stockpile) == 1
    assert colonysim._stockpile_accepts(stockpile, non_stack) is True
    assert colonysim._stockpile_accepts(stockpile, stack) is True

    stockpile.remove_component(StorageFilterComponent)
    assert colonysim._stockpile_accepts(stockpile, stack) is True

    stockpile.add_component(StorageFilterComponent(allowed_types=("wood",)))
    assert colonysim._stockpile_accepts(stockpile, non_stack) is False

    orphan_container = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="crate", kind="container")],
    )
    colonysim._move_entity(scenario.actor.world, orphan_container.id, stockpile.id)
    assert container_of(orphan_container) == stockpile.id


async def test_stockpile_filter_forbid_haul_split_and_merge_loop():
    scenario = build_scenario()
    _install(scenario.actor)
    created: list[StockpileCreatedEvent] = []
    filtered: list[StorageFilterChangedEvent] = []
    forbidden: list[ItemForbiddenEvent] = []
    hauled: list[ItemHauledEvent] = []
    split: list[StackSplitEvent] = []
    merged: list[StackMergedEvent] = []
    scenario.actor.bus.subscribe(StockpileCreatedEvent, created.append)
    scenario.actor.bus.subscribe(StorageFilterChangedEvent, filtered.append)
    scenario.actor.bus.subscribe(ItemForbiddenEvent, forbidden.append)
    scenario.actor.bus.subscribe(ItemHauledEvent, hauled.append)
    scenario.actor.bus.subscribe(StackSplitEvent, split.append)
    scenario.actor.bus.subscribe(StackMergedEvent, merged.append)
    stack = _stack(scenario, "wood", 6)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "create-stockpile",
            name="wood stockpile",
            capacity=8,
            allowed_types="stone",
        )
    )
    await scenario.actor.tick(HOUR)
    stockpile_id = parse_entity_id(created[0].stockpile_id)
    stockpile = scenario.actor.world.get_entity(stockpile_id)
    assert stockpile.get_component(StorageFilterComponent).allowed_types == ("stone",)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "set-storage-filter",
            stockpile_id=str(stockpile_id),
            allowed_types=("wood", "plank"),
        )
    )
    await scenario.actor.tick(HOUR)
    assert filtered[0].allowed_types == ("plank", "wood")

    await scenario.actor.submit(_cmd(scenario, "forbid-item", item_id=str(stack)))
    await scenario.actor.tick(HOUR)
    assert scenario.actor.world.get_entity(stack).has_component(ForbiddenComponent)

    await scenario.actor.submit(_cmd(scenario, "allow-item", item_id=str(stack)))
    await scenario.actor.tick(HOUR)
    assert not scenario.actor.world.get_entity(stack).has_component(ForbiddenComponent)
    assert [event.forbidden for event in forbidden] == [True, False]

    await scenario.actor.submit(_cmd(scenario, "split-stack", item_id=str(stack), quantity=2))
    await scenario.actor.tick(HOUR)
    new_stack_id = parse_entity_id(split[0].new_stack_id)
    assert (
        scenario.actor.world.get_entity(stack).get_component(ResourceStackComponent).quantity == 4
    )
    assert scenario.actor.world.get_entity(new_stack_id).get_component(
        ResourceStackComponent
    ).quantity == 2

    await scenario.actor.submit(
        _cmd(
            scenario,
            "merge-stack",
            source_id=str(new_stack_id),
            target_id=str(stack),
        )
    )
    await scenario.actor.tick(HOUR)
    assert merged[0].quantity == 2
    assert (
        scenario.actor.world.get_entity(stack).get_component(ResourceStackComponent).quantity == 6
    )
    assert container_of(scenario.actor.world.get_entity(new_stack_id)) is None

    await scenario.actor.submit(
        _cmd(
            scenario,
            "haul-item",
            item_id=str(stack),
            target_container_id=str(stockpile_id),
        )
    )
    await scenario.actor.tick(HOUR)

    assert hauled[0].target_container_id == str(stockpile_id)
    assert container_of(scenario.actor.world.get_entity(stack)) == stockpile_id
    fragments = colonysim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )
    assert any("Nearby stockpile: 6/8 stored, accepts plank, wood." == line for line in fragments)


async def test_stockpile_creation_requires_room_and_haul_can_use_plain_container():
    scenario = build_scenario()
    _install(scenario.actor)
    stack = _stack(scenario, "wood", 1)
    crate = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="crate", kind="container")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), crate.id
    )
    rejected_events: list[CommandRejectedEvent] = []
    hauled: list[ItemHauledEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejected_events.append)
    scenario.actor.bus.subscribe(ItemHauledEvent, hauled.append)

    await scenario.actor.submit(
        _cmd(scenario, "haul-item", item_id=str(stack), target_container_id=str(crate.id))
    )
    await scenario.actor.tick(HOUR)

    assert hauled[0].target_container_id == str(crate.id)
    assert container_of(scenario.actor.world.get_entity(stack)) == crate.id

    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains, scenario.character
    )
    await scenario.actor.submit(_cmd(scenario, "create-stockpile", name="orphan stockpile"))
    await scenario.actor.tick(HOUR)

    assert rejected_events[-1].reason == "character is not in a room"


async def test_reservation_blocks_other_characters_until_released():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario)

    await scenario.actor.submit(_cmd(scenario, "reserve", target_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert scenario.actor.world.get_entity(node).has_relationship(ReservedBy, scenario.character)

    await scenario.actor.submit(_cmd(scenario, "release-reservation", target_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert not scenario.actor.world.get_entity(node).has_relationship(
        ReservedBy, scenario.character
    )


async def test_gather_resource_decrements_node_and_adds_inventory_stack():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario, current=4)
    gathered: list[ResourceGatheredEvent] = []
    scenario.actor.bus.subscribe(ResourceGatheredEvent, gathered.append)

    await scenario.actor.submit(
        _cmd(scenario, "gather-resource", node_id=str(node), quantity=2)
    )
    await scenario.actor.tick(HOUR)

    node_entity = scenario.actor.world.get_entity(node)
    assert node_entity.get_component(ResourceNodeComponent).current == 2
    stack = scenario.actor.world.get_entity(parse_entity_id(gathered[0].stack_id))
    assert stack.get_component(ResourceStackComponent).resource_type == "wood"
    assert stack.get_component(ResourceStackComponent).quantity == 2


async def test_gather_resource_merges_existing_inventory_stack():
    scenario = build_scenario()
    _install(scenario.actor)
    existing_stack = _stack(scenario, "wood", 1)
    node = _resource_node(scenario, current=4)
    gathered: list[ResourceGatheredEvent] = []
    scenario.actor.bus.subscribe(ResourceGatheredEvent, gathered.append)

    await scenario.actor.submit(
        _cmd(scenario, "gather-resource", node_id=str(node), quantity=2)
    )
    await scenario.actor.tick(HOUR)

    stack = scenario.actor.world.get_entity(existing_stack)
    assert gathered[0].stack_id == str(existing_stack)
    assert stack.get_component(ResourceStackComponent).quantity == 3
    assert stack.get_component(IdentityComponent).name == "wood x3"


async def test_resource_nodes_regenerate_to_maximum():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario, current=1)
    node_entity = scenario.actor.world.get_entity(node)
    replace_component(
        node_entity,
        ResourceNodeComponent(resource_type="wood", current=1, maximum=4, regen_per_day=2.0)
    )

    await scenario.actor.tick(24 * 60 * 60)
    await scenario.actor.tick(24 * 60 * 60)

    assert node_entity.get_component(ResourceNodeComponent).current == 4


async def test_gather_rejects_when_resource_reserved_by_someone_else():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario)
    other = spawn_entity(scenario.actor.world, [IdentityComponent(name="Other", kind="character")])
    scenario.actor.world.get_entity(node).add_relationship(ReservedBy(since_epoch=0), other.id)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "gather-resource", node_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert any("reserved" in event.reason for event in rejects)


async def test_craft_consumes_inputs_at_reachable_workstation_and_creates_outputs():
    scenario = build_scenario()
    _install(scenario.actor)
    input_stack = _stack(scenario, "wood", 2)
    recipe = spawn_entity(
        scenario.actor.world,
        [
            RecipeComponent(
                recipe_id="club",
                inputs={"wood": 2},
                outputs={"club": 1},
                required_station="bench",
            )
        ],
    )
    bench = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Workbench", kind="workstation"),
            WorkstationComponent(station_type="bench"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), bench.id
    )
    crafted: list[ItemCraftedEvent] = []
    scenario.actor.bus.subscribe(ItemCraftedEvent, crafted.append)

    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="club"))
    await scenario.actor.tick(HOUR)

    assert recipe.has_component(RecipeComponent)
    assert crafted[0].recipe_id == "club"
    output = scenario.actor.world.get_entity(parse_entity_id(crafted[0].output_ids[0]))
    assert output.get_component(ResourceStackComponent).resource_type == "club"
    assert output.get_component(ResourceStackComponent).quantity == 1
    assert container_of(scenario.actor.world.get_entity(input_stack)) is None


async def test_bake_recipe_creates_edible_output_entity():
    scenario = build_scenario()
    _install(scenario.actor)
    _stack(scenario, "flour", 1)
    _stack(scenario, "sugar", 1)
    spawn_entity(
        scenario.actor.world,
        [
            RecipeComponent(
                recipe_id="cookies",
                inputs={"flour": 1, "sugar": 1},
                outputs={"cookies": 4},
                required_station="oven",
                output_entities={
                    "cookies": {
                        "display_name": "cookies",
                        "entity_kind": "food",
                        "nutrition": 4.0,
                        "satiety": 18.0,
                        "uses": 4,
                    }
                },
            )
        ],
    )
    oven = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Oven", kind="workstation"),
            WorkstationComponent(station_type="oven"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), oven.id
    )
    crafted: list[ItemCraftedEvent] = []
    scenario.actor.bus.subscribe(ItemCraftedEvent, crafted.append)

    await scenario.actor.submit(_cmd(scenario, "bake", recipe_id="cookies"))
    await scenario.actor.tick(HOUR)

    output = scenario.actor.world.get_entity(parse_entity_id(crafted[0].output_ids[0]))
    assert output.get_component(ResourceStackComponent).resource_type == "cookies"
    assert output.get_component(ResourceStackComponent).quantity == 4
    assert output.get_component(FoodComponent).satiety == 18.0
    assert container_of(output) == scenario.character


async def test_craft_recipe_metadata_can_create_drinkable_nonportable_output():
    scenario = build_scenario()
    _install(scenario.actor)
    _stack(scenario, "water", 1)
    spawn_entity(
        scenario.actor.world,
        [
            RecipeComponent(
                recipe_id="tea",
                inputs={"water": 1},
                outputs={"tea": 1},
                output_entities={
                    "tea": {
                        "display_name": "camp tea",
                        "entity_kind": "drink",
                        "portable": False,
                        "hydration": 12.0,
                        "purity": 0.95,
                        "uses": 0,
                    }
                },
            )
        ],
    )
    crafted: list[ItemCraftedEvent] = []
    scenario.actor.bus.subscribe(ItemCraftedEvent, crafted.append)

    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="tea"))
    await scenario.actor.tick(HOUR)

    output = scenario.actor.world.get_entity(parse_entity_id(crafted[0].output_ids[0]))
    assert output.get_component(IdentityComponent).name == "camp tea"
    assert output.get_component(ResourceStackComponent).resource_type == "tea"
    assert output.get_component(DrinkableComponent).hydration == 12.0
    assert not output.has_component(PortableComponent)
    assert not output.has_component(ConsumableComponent)


async def test_work_priorities_allowed_areas_room_quality_and_wealth_fragments():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(RoomRoleComponent(role="dining room"))
    room.add_component(RoomStatComponent(beauty=2.0, cleanliness=1.0, comfort=3.0, wealth=100.0))
    _stack(scenario, "wood", 10)

    await scenario.actor.submit(_cmd(scenario, "set-work-priority", work_type="doctor", priority=1))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(
        _cmd(scenario, "set-allowed-area", room_ids=(str(scenario.room_a), str(scenario.room_b)))
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(WorkPriorityComponent).priorities == {"doctor": 1}
    assert character.get_component(AllowedAreaComponent).room_ids == (
        str(scenario.room_a),
        str(scenario.room_b),
    )
    assert room.get_component(RoomQualityComponent).impressiveness == 7.0
    marker = next(scenario.actor.world.query().with_all([ColonySimComponent]).execute_entities())
    assert marker.get_component(ColonyWealthComponent).wealth >= 110.0
    fragments = colonysim_fragments(scenario.actor.world, character)
    assert any("Work priorities" in line for line in fragments)
    assert any("Colony wealth" in line for line in fragments)


async def test_tend_wound_rescue_to_bed_and_medical_recovery():
    scenario = build_scenario()
    _install(scenario.actor)
    patient = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            HealthComponent(current=50.0, maximum=100.0),
            DownedComponent(downed_at_epoch=0, cause="injured"),
        ],
    )
    injury = spawn_entity(
        scenario.actor.world,
        [InjuryComponent(body_part="leg", severity=5.0, pain=8.0, bleeding_rate=4.0)],
    )
    patient.add_relationship(HasInjury(), injury.id)
    bed = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="clinic bed", kind="bed"), MedicalBedComponent(quality=2.0)],
    )
    medicine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="herbal medicine", kind="medicine"),
            MedicineComponent(quality=0.75, uses=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), patient.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), bed.id)
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), medicine.id
    )

    await scenario.actor.submit(
        _cmd(scenario, "rescue-to-bed", patient_id=str(patient.id), bed_id=str(bed.id))
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "tend-wound",
            patient_id=str(patient.id),
            injury_id=str(injury.id),
            medicine_id=str(medicine.id),
        )
    )
    await scenario.actor.tick(2 * HOUR)

    assert injury.get_component(InjuryComponent).treated is True
    assert not scenario.actor.world.has_entity(medicine.id)
    assert patient.get_component(BedRestComponent).bed_id == str(bed.id)
    assert patient.has_component(SleepingComponent)
    assert patient.get_component(HealthComponent).current > 50.0


async def test_mental_break_and_inspiration_trigger_from_needs_and_affect():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(FunNeedComponent(meter=Meter(value=95.0)))

    await scenario.actor.tick(0.0)

    assert character.get_component(MentalStateComponent).state == "mental_break"

    character.remove_component(FunNeedComponent)
    character.remove_component(MentalStateComponent)
    character.add_component(AffectComponent(current=AffectVector(valence=20.0)))

    await scenario.actor.tick(0.0)

    assert character.get_component(MentalStateComponent).state == "inspired"


def test_colony_work_medical_handlers_reject_invalid_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    character = scenario.actor.world.get_entity(scenario.character)
    patient = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Patient", kind="character"),
            CharacterComponent(),
            DownedComponent(downed_at_epoch=0, cause="injury"),
        ],
    )
    healthy_patient = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Healthy", kind="character"), CharacterComponent()],
    )
    injury = spawn_entity(
        scenario.actor.world,
        [InjuryComponent(body_part="arm", severity=3.0)],
    )
    wrong_kind = spawn_entity(scenario.actor.world, [IdentityComponent(name="crate", kind="prop")])
    bed = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="clinic bed", kind="bed"), MedicalBedComponent()],
    )
    medicine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="medicine", kind="medicine"),
            MedicineComponent(quality=0.5, uses=1),
            PortableComponent(can_pick_up=True),
        ],
    )
    non_room = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="zone marker", kind="zone")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), patient.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), healthy_patient.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), bed.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), non_room.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), medicine.id)
    patient.add_relationship(HasInjury(), injury.id)
    non_injury = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="bruise note", kind="note")],
    )
    patient.add_relationship(HasInjury(), non_injury.id)
    distant_medicine = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far medicine", kind="medicine"), MedicineComponent()],
    )
    distant_patient = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Far Patient", kind="character"), CharacterComponent()],
    )
    distant_bed = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far bed", kind="bed"), MedicalBedComponent()],
    )
    assert container_of(distant_patient) is None
    assert container_of(distant_bed) is None

    cases = [
        (
            SetWorkPriorityHandler(),
            _handler_cmd(scenario, "set-work-priority", character_id="bad", work_type="doctor"),
            "invalid character id",
        ),
        (
            SetWorkPriorityHandler(),
            _handler_cmd(scenario, "set-work-priority", work_type=" ", priority=1),
            "missing work type",
        ),
        (
            SetWorkPriorityHandler(),
            _handler_cmd(scenario, "set-work-priority", work_type="doctor", priority=5),
            "priority must be between 0 and 4",
        ),
        (
            SetAllowedAreaHandler(),
            _handler_cmd(scenario, "set-allowed-area", character_id="bad"),
            "invalid character id",
        ),
        (
            SetAllowedAreaHandler(),
            _handler_cmd(scenario, "set-allowed-area", room_ids=("entity_999",)),
            "room does not exist",
        ),
        (
            SetAllowedAreaHandler(),
            _handler_cmd(scenario, "set-allowed-area", room_ids=(str(non_room.id),)),
            "target is not a room",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                character_id="bad",
                patient_id=str(patient.id),
                injury_id=str(injury.id),
            ),
            "invalid doctor, patient, or injury id",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id="entity_999",
                injury_id=str(injury.id),
            ),
            "patient or injury does not exist",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id=str(distant_patient.id),
                injury_id=str(injury.id),
            ),
            "patient is not reachable",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id=str(healthy_patient.id),
                injury_id=str(injury.id),
            ),
            "injury does not belong to patient",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id=str(patient.id),
                injury_id=str(wrong_kind.id),
            ),
            "injury does not belong to patient",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id=str(patient.id),
                injury_id=str(non_injury.id),
            ),
            "target is not an injury",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id=str(patient.id),
                injury_id=str(injury.id),
                medicine_id="entity_999",
            ),
            "medicine does not exist",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id=str(patient.id),
                injury_id=str(injury.id),
                medicine_id=str(distant_medicine.id),
            ),
            "medicine is not reachable",
        ),
        (
            TendWoundHandler(),
            _handler_cmd(
                scenario,
                "tend-wound",
                patient_id=str(patient.id),
                injury_id=str(injury.id),
                medicine_id=str(wrong_kind.id),
            ),
            "target is not medicine",
        ),
        (
            RescueToBedHandler(),
            _handler_cmd(
                scenario,
                "rescue-to-bed",
                character_id="bad",
                patient_id=str(patient.id),
                bed_id=str(bed.id),
            ),
            "invalid rescuer, patient, or bed id",
        ),
        (
            RescueToBedHandler(),
            _handler_cmd(
                scenario,
                "rescue-to-bed",
                patient_id="entity_999",
                bed_id=str(bed.id),
            ),
            "patient or bed does not exist",
        ),
        (
            RescueToBedHandler(),
            _handler_cmd(
                scenario,
                "rescue-to-bed",
                patient_id=str(distant_patient.id),
                bed_id=str(bed.id),
            ),
            "patient is not reachable",
        ),
        (
            RescueToBedHandler(),
            _handler_cmd(
                scenario,
                "rescue-to-bed",
                patient_id=str(patient.id),
                bed_id=str(distant_bed.id),
            ),
            "bed is not reachable",
        ),
        (
            RescueToBedHandler(),
            _handler_cmd(
                scenario,
                "rescue-to-bed",
                patient_id=str(wrong_kind.id),
                bed_id=str(bed.id),
            ),
            "patient is not a character",
        ),
        (
            RescueToBedHandler(),
            _handler_cmd(
                scenario,
                "rescue-to-bed",
                patient_id=str(healthy_patient.id),
                bed_id=str(bed.id),
            ),
            "patient does not need rescue",
        ),
        (
            RescueToBedHandler(),
            _handler_cmd(
                scenario,
                "rescue-to-bed",
                patient_id=str(patient.id),
                bed_id=str(wrong_kind.id),
            ),
            "target is not a medical bed",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


async def test_colony_quality_medicine_infection_and_state_expiry_edges():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(RoomRoleComponent(role="clinic"))
    room.add_component(RoomStatComponent(beauty=1.0, cleanliness=2.0, comfort=3.0, wealth=50.0))
    art = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="sculpture", kind="decor"),
            RoomStatComponent(beauty=4.0, wealth=250.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), art.id)
    patient = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            HealthComponent(current=90.0, maximum=100.0),
            BleedingComponent(rate=3.0, last_updated_epoch=0),
            BedRestComponent(started_at_epoch=0, bed_id="entity_999"),
            InfectionComponent(severity=0.4, immunity=0.1, last_updated_epoch=0),
            MentalStateComponent(
                state="inspired",
                reason="old high mood",
                expires_at_epoch=HOUR,
            ),
        ],
    )
    injury = spawn_entity(
        scenario.actor.world,
        [InjuryComponent(body_part="arm", severity=4.0, pain=10.0, bleeding_rate=6.0)],
    )
    medicine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="industrial medicine", kind="medicine"),
            MedicineComponent(quality=0.5, uses=2),
            PortableComponent(can_pick_up=True),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), patient.id)
    patient.add_relationship(HasInjury(), injury.id)
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), medicine.id
    )

    await scenario.actor.submit(
        _cmd(
            scenario,
            "tend-wound",
            patient_id=str(patient.id),
            injury_id=str(injury.id),
            medicine_id=str(medicine.id),
        )
    )
    await scenario.actor.tick(2 * HOUR)

    quality = room.get_component(RoomQualityComponent)
    marker = next(scenario.actor.world.query().with_all([ColonySimComponent]).execute_entities())
    wealth = marker.get_component(ColonyWealthComponent)
    medicine_component = medicine.get_component(MedicineComponent)
    assert quality.role == "clinic"
    assert quality.beauty == 5.0
    assert quality.impressiveness == 13.0
    assert wealth.expectations == "high"
    assert medicine_component.uses == 1
    assert injury.get_component(InjuryComponent).pain == 5.0
    assert patient.get_component(BleedingComponent).rate == 0.0
    assert patient.get_component(HealthComponent).current > 90.0
    infection = patient.get_component(InfectionComponent)
    assert infection.immunity > 0.1
    assert patient.get_component(MentalStateComponent).state == "stable"


def test_tend_self_without_medicine_and_orphan_medicine_use_edges():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    injury = spawn_entity(
        scenario.actor.world,
        [InjuryComponent(body_part="hand", severity=1.0, pain=2.0, bleeding_rate=1.0)],
    )
    character.add_relationship(HasInjury(), injury.id)

    result = TendWoundHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "tend-wound",
            patient_id=str(scenario.character),
            injury_id=str(injury.id),
        ),
    )
    assert result.ok is True
    assert injury.get_component(InjuryComponent).treated is True

    medicine = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="orphan medicine", kind="medicine"), MedicineComponent(uses=1)],
    )
    colonysim._consume_medicine_use(ctx, medicine.id)
    assert not scenario.actor.world.has_entity(medicine.id)


async def test_work_priority_zero_removes_priority():
    scenario = build_scenario()
    _install(scenario.actor)

    await scenario.actor.submit(_cmd(scenario, "set-work-priority", work_type="cook", priority=2))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(_cmd(scenario, "set-work-priority", work_type="cook", priority=0))
    await scenario.actor.tick(0.0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(WorkPriorityComponent).priorities == {}


async def test_craft_consumes_partial_stack_and_merges_output_stack():
    scenario = build_scenario()
    _install(scenario.actor)
    input_stack = _stack(scenario, "wood", 3)
    output_stack = _stack(scenario, "plank", 1)
    spawn_entity(
        scenario.actor.world,
        [
            RecipeComponent(
                recipe_id="planks",
                inputs={"wood": 2},
                outputs={"plank": 2},
            )
        ],
    )
    crafted: list[ItemCraftedEvent] = []
    scenario.actor.bus.subscribe(ItemCraftedEvent, crafted.append)

    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="planks"))
    await scenario.actor.tick(HOUR)

    input_entity = scenario.actor.world.get_entity(input_stack)
    output_entity = scenario.actor.world.get_entity(output_stack)
    assert input_entity.get_component(ResourceStackComponent).quantity == 1
    assert input_entity.get_component(IdentityComponent).name == "wood x1"
    assert crafted[0].output_ids == (str(output_stack),)
    assert output_entity.get_component(ResourceStackComponent).quantity == 3
    assert output_entity.get_component(IdentityComponent).name == "plank x3"


async def test_craft_rejects_missing_recipe_and_unreachable_workstation():
    scenario = build_scenario()
    _install(scenario.actor)
    _stack(scenario, "wood", 2)
    spawn_entity(
        scenario.actor.world,
        [RecipeComponent(recipe_id="known", inputs={"wood": 1}, outputs={"club": 1})],
    )
    bench_recipe = spawn_entity(
        scenario.actor.world,
        [
            RecipeComponent(
                recipe_id="bench-work",
                inputs={"wood": 1},
                outputs={"club": 1},
                required_station="bench",
            )
        ],
    )
    wrong_station = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Loom", kind="workstation"),
            WorkstationComponent(station_type="loom"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_station.id
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="missing"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="bench-work"))
    await scenario.actor.tick(HOUR)

    assert bench_recipe.has_component(RecipeComponent)
    assert [event.reason for event in rejects] == [
        "recipe does not exist",
        "required workstation is not reachable",
    ]


async def test_craft_rejects_missing_or_short_input_stacks():
    scenario = build_scenario()
    _install(scenario.actor)
    _stack(scenario, "wood", 1)
    spawn_entity(
        scenario.actor.world,
        [RecipeComponent(recipe_id="stone-tool", inputs={"stone": 1}, outputs={"tool": 1})],
    )
    spawn_entity(
        scenario.actor.world,
        [RecipeComponent(recipe_id="wood-tool", inputs={"wood": 2}, outputs={"tool": 1})],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="stone-tool"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "craft", recipe_id="wood-tool"))
    await scenario.actor.tick(HOUR)

    assert [event.reason for event in rejects] == [
        "missing recipe inputs",
        "missing recipe inputs",
    ]


def test_consume_resource_stack_returns_false_for_missing_or_short_stacks():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    _stack(scenario, "wood", 1)

    assert colonysim._consume_resource_stack(character, scenario.actor.world, "stone", 1) is False
    assert colonysim._consume_resource_stack(character, scenario.actor.world, "wood", 2) is False


async def test_assign_and_complete_job_updates_assignment_state():
    scenario = build_scenario()
    _install(scenario.actor)
    job = _job(scenario)
    assigned: list[JobAssignedEvent] = []
    completed: list[JobCompletedEvent] = []
    scenario.actor.bus.subscribe(JobAssignedEvent, assigned.append)
    scenario.actor.bus.subscribe(JobCompletedEvent, completed.append)

    await scenario.actor.submit(_cmd(scenario, "assign-job", job_id=str(job)))
    await scenario.actor.tick(HOUR)

    job_entity = scenario.actor.world.get_entity(job)
    assert job_entity.has_relationship(AssignedTo, scenario.character)
    assert job_entity.get_component(JobComponent).assigned is True
    assert assigned[0].job_id == str(job)

    await scenario.actor.submit(_cmd(scenario, "complete-job", job_id=str(job)))
    await scenario.actor.tick(HOUR)

    assert not job_entity.has_relationship(AssignedTo, scenario.character)
    assert job_entity.get_component(JobComponent).assigned is False
    assert job_entity.get_component(JobComponent).completed is True
    assert completed[0].job_id == str(job)


async def test_assign_job_rejects_when_assigned_to_someone_else():
    scenario = build_scenario()
    _install(scenario.actor)
    job = _job(scenario)
    other = spawn_entity(scenario.actor.world, [IdentityComponent(name="Other", kind="character")])
    job_entity = scenario.actor.world.get_entity(job)
    job_entity.add_relationship(AssignedTo(since_epoch=0), other.id)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "assign-job", job_id=str(job)))
    await scenario.actor.tick(HOUR)

    assert any("assigned" in event.reason for event in rejects)


async def test_claim_and_release_ownership_on_reachable_target():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario)
    claimed: list[OwnershipClaimedEvent] = []
    released: list[OwnershipReleasedEvent] = []
    scenario.actor.bus.subscribe(OwnershipClaimedEvent, claimed.append)
    scenario.actor.bus.subscribe(OwnershipReleasedEvent, released.append)

    await scenario.actor.submit(_cmd(scenario, "claim-ownership", target_id=str(node)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(Owns, node)
    assert claimed[0].target_id == str(node)

    await scenario.actor.submit(_cmd(scenario, "release-ownership", target_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert not character.has_relationship(Owns, node)
    assert released[0].target_id == str(node)


async def test_claim_ownership_rejects_target_owned_by_someone_else():
    scenario = build_scenario()
    _install(scenario.actor)
    node = _resource_node(scenario)
    other = spawn_entity(scenario.actor.world, [IdentityComponent(name="Other", kind="character")])
    other.add_relationship(Owns(since_epoch=0), node)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "claim-ownership", target_id=str(node)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "target is already owned" for event in rejects)


def test_colonysim_fragments_show_nearby_resources_and_recipes():
    scenario = build_scenario()
    node = _resource_node(scenario, "berries", current=5)
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Owns(since_epoch=0), node
    )
    _job(scenario, "haul", priority=2)
    spawn_entity(
        scenario.actor.world,
        [RecipeComponent(recipe_id="snack", inputs={"berries": 1}, outputs={"snack": 1})],
    )

    fragments = colonysim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("berries" in line for line in fragments)
    assert any("snack recipe" in line for line in fragments)
    assert any("Nearby job: haul priority 2" in line for line in fragments)
    assert any("You own berries patch" in line for line in fragments)


def test_colonysim_fragments_show_health_room_and_work_context():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(WorkPriorityComponent(priorities={"doctor": 1}))
    character.add_component(AllowedAreaComponent(room_ids=(str(scenario.room_a),)))
    character.add_component(BedRestComponent(started_at_epoch=0, bed_id="entity_999"))
    character.add_component(InfectionComponent(severity=0.35, immunity=0.45))
    character.add_component(MentalStateComponent(state="mental_break", reason="low fun"))
    marker = spawn_entity(
        scenario.actor.world,
        [ColonySimComponent(), ColonyWealthComponent(wealth=250.0, expectations="high")],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(RoomQualityComponent(role="barracks", impressiveness=8.5))
    bed = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="clinic bed", kind="bed"), MedicalBedComponent()],
    )
    medicine = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="glitter medicine", kind="medicine"),
            MedicineComponent(quality=0.9, uses=2),
        ],
    )
    station = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="stove", kind="workstation"),
            WorkstationComponent(station_type="stove"),
        ],
    )
    forbidden = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="forbidden wood", kind="resource"),
            ResourceStackComponent(resource_type="wood", quantity=1),
            ForbiddenComponent(),
        ],
    )
    assigned_job = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="cook job", kind="job"),
            JobComponent(job_type="cook", priority=3, assigned=True),
        ],
    )
    completed_job = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="done job", kind="job"),
            JobComponent(job_type="haul", priority=1, completed=True),
        ],
    )
    for entity in (bed, medicine, station, forbidden, assigned_job, completed_job, marker):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    fragments = colonysim_fragments(scenario.actor.world, character)

    expected = (
        "Work priorities: doctor:1.",
        f"Allowed work area rooms: {scenario.room_a}.",
        "You are on medical bed rest.",
        "Infection: severity 0.35, immunity 0.45.",
        "Mental state: mental_break (low fun).",
        "Colony wealth is 250; expectations are high.",
        "Room quality: barracks, impressiveness 8.5.",
        "Nearby medical bed is available.",
        "Nearby medicine: quality 0.90, uses 2.",
        "Nearby workstation: stove.",
        "forbidden wood is forbidden for hauling.",
        "Nearby job: cook priority 3 (assigned).",
    )
    for line in expected:
        assert line in fragments

    character.remove_component(WorkPriorityComponent)
    character.remove_component(AllowedAreaComponent)
    character.remove_component(MentalStateComponent)
    character.add_component(WorkPriorityComponent())
    character.add_component(AllowedAreaComponent())
    character.add_component(MentalStateComponent())
    sparse_fragments = colonysim_fragments(scenario.actor.world, character)
    assert "Nearby job: haul priority 1 (available)." not in sparse_fragments
    assert not any(line.startswith("Work priorities:") for line in sparse_fragments)
    assert not any(line.startswith("Allowed work area rooms:") for line in sparse_fragments)
    assert not any(line.startswith("Mental state:") for line in sparse_fragments)


def test_colonysim_component_prompt_fragments_cover_self_and_nearby_state():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    viewer = spawn_entity(world, [CharacterComponent()])
    node = spawn_entity(
        world,
        [
            IdentityComponent(name="berry patch", kind="resource"),
            ResourceNodeComponent(resource_type="berries", current=3, maximum=5),
        ],
    )
    self_ctx = ComponentPromptContext.for_entity(world, character)
    external_ctx = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=viewer),
    )
    node_ctx = ComponentPromptContext.for_entity(world, node, perspective=self_ctx.perspective)

    assert WorkPriorityComponent(priorities={"doctor": 1}).prompt_fragments(self_ctx) == (
        "Work priorities: doctor:1.",
    )
    assert WorkPriorityComponent(priorities={"doctor": 1}).prompt_fragments(external_ctx) == ()
    assert node.get_component(ResourceNodeComponent).prompt_fragments(node_ctx) == (
        "Nearby resource: berries (3 available).",
    )
    assert JobComponent(job_type="haul", priority=2).prompt_fragments(node_ctx) == (
        "Nearby job: haul priority 2 (available).",
    )


async def test_colonysim_catalogue_profile_jobs_prisoners_research_trade_and_surgery():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    prisoner = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Pip", kind="character"),
            CharacterComponent(),
            PrisonerComponent(recruitment_difficulty=3.0),
        ],
    )
    bill = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="stone blocks bill", kind="job"),
            JobComponent(job_type="craft", priority=2),
            JobBillComponent(recipe_id="stone-blocks", work_required=2.0),
        ],
    )
    project = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="battery research", kind="research"),
            ResearchProjectComponent(project_id="battery", work_required=2.0),
        ],
    )
    incident = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="mad hare", kind="incident"),
            ColonyIncidentComponent(incident_type="raid", severity=2),
        ],
    )
    offer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hill clan trade", kind="trade"),
            TradeOfferComponent(
                faction_id="hill-clan",
                wants={"wood": 1},
                gives={"medicine": 2},
                goodwill_delta=3.0,
            ),
        ],
    )
    surgery = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="left paw surgery", kind="surgery"),
            SurgeryBillComponent(part="left paw", operation="amputate"),
        ],
    )
    for entity in (prisoner, bill, project, incident, offer, surgery):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    _stack(scenario, "wood", 3)

    profiles: list[PawnProfileUpdatedEvent] = []
    bills: list[JobBillProgressedEvent] = []
    policies: list[PrisonerPolicySetEvent] = []
    recruitments: list[RecruitmentProgressedEvent] = []
    research: list[ResearchProgressedEvent] = []
    techs: list[TechUnlockedEvent] = []
    incidents: list[ColonyIncidentResolvedEvent] = []
    trades: list[TradeCompletedEvent] = []
    caravans: list[CaravanFormedEvent] = []
    surgeries: list[SurgeryPerformedEvent] = []
    scenario.actor.bus.subscribe(PawnProfileUpdatedEvent, profiles.append)
    scenario.actor.bus.subscribe(JobBillProgressedEvent, bills.append)
    scenario.actor.bus.subscribe(PrisonerPolicySetEvent, policies.append)
    scenario.actor.bus.subscribe(RecruitmentProgressedEvent, recruitments.append)
    scenario.actor.bus.subscribe(ResearchProgressedEvent, research.append)
    scenario.actor.bus.subscribe(TechUnlockedEvent, techs.append)
    scenario.actor.bus.subscribe(ColonyIncidentResolvedEvent, incidents.append)
    scenario.actor.bus.subscribe(TradeCompletedEvent, trades.append)
    scenario.actor.bus.subscribe(CaravanFormedEvent, caravans.append)
    scenario.actor.bus.subscribe(SurgeryPerformedEvent, surgeries.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "update-pawn-profile",
            backstory="field medic",
            passions={"doctor": 2},
            expectations="moderate",
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "progress-job-bill", bill_id=str(bill.id), work=2))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "set-prisoner-policy", prisoner_id=str(prisoner.id), policy="recruit")
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "recruit-prisoner", prisoner_id=str(prisoner.id), progress=3)
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "research-project", project_id=str(project.id), work=2)
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "resolve-colony-incident", incident_id=str(incident.id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "complete-trade", offer_id=str(offer.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "form-caravan", destination="hill market", cargo={"wood": 1})
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "perform-surgery",
            patient_id=str(scenario.character),
            surgery_id=str(surgery.id),
        )
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert profiles[0].expectations == "moderate"
    assert character.get_component(PawnProfileComponent).passions == {"doctor": 2}
    assert bills[0].completed is True
    assert bill.get_component(JobComponent).completed is True
    assert policies[0].policy == "recruit"
    assert recruitments[0].recruited is True
    assert not prisoner.has_component(PrisonerComponent)
    assert research[0].unlocked is True
    assert project.get_component(TechUnlockComponent).tech_id == "battery"
    assert techs[0].tech_id == "battery"
    assert incidents[0].incident_type == "raid"
    assert incident.get_component(ColonyIncidentComponent).resolved is True
    assert trades[0].goodwill == 3.0
    relation = next(
        entity
        for entity in scenario.actor.world.query()
        .with_all([FactionRelationComponent])
        .execute_entities()
        if entity.get_component(FactionRelationComponent).faction_id == "hill-clan"
    )
    assert relation.get_component(FactionRelationComponent).goodwill == 3.0
    caravan_id = parse_entity_id(caravans[0].caravan_id)
    assert scenario.actor.world.get_entity(caravan_id).get_component(
        CaravanComponent
    ).destination == "hill market"
    assert surgeries[0].part == "left paw"
    body_part_id = character.get_relationships(HasBodyPart)[0][1]
    assert scenario.actor.world.get_entity(body_part_id).get_component(
        BodyPartHealthComponent
    ).missing is True
    assert surgery.get_component(SurgeryBillComponent).completed is True
    fragments = colonysim_fragments(scenario.actor.world, character)
    assert "Backstory: field medic." in fragments


def test_colonysim_catalogue_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    other_room = scenario.actor.world.get_entity(scenario.room_b)
    character = scenario.actor.world.get_entity(scenario.character)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain crate", kind="prop")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    suspended_bill = spawn_entity(
        scenario.actor.world,
        [JobBillComponent(recipe_id="plank", work_required=5, suspended=True)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), suspended_bill.id)
    complete_bill = spawn_entity(
        scenario.actor.world,
        [JobBillComponent(recipe_id="plank", work_required=5, work_done=5)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), complete_bill.id)
    unreachable_bill = spawn_entity(
        scenario.actor.world,
        [JobBillComponent(recipe_id="plank", work_required=5)],
    )
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unreachable_bill.id)
    prisoner = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="prisoner", kind="character"),
            PrisonerComponent(policy="hold"),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), prisoner.id)
    distant_prisoner = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant prisoner", kind="character"),
            PrisonerComponent(policy="recruit"),
        ],
    )
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_prisoner.id)
    unlocked_project = spawn_entity(
        scenario.actor.world,
        [ResearchProjectComponent(project_id="done", work_required=1, unlocked=True)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unlocked_project.id)
    resolved_incident = spawn_entity(
        scenario.actor.world,
        [ColonyIncidentComponent(incident_type="raid", resolved=True)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), resolved_incident.id)
    trade_offer = spawn_entity(
        scenario.actor.world,
        [TradeOfferComponent(faction_id="traders", wants={"wood": 1})],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), trade_offer.id)
    completed_surgery = spawn_entity(
        scenario.actor.world,
        [SurgeryBillComponent(part="arm", operation="repair", completed=True)],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), completed_surgery.id)
    surgery = spawn_entity(
        scenario.actor.world,
        [SurgeryBillComponent(part="arm", operation="repair", prosthetic_item_id="entity_999")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), surgery.id)
    wrong_prosthetic = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="stick", kind="prop")],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), wrong_prosthetic.id)
    surgery_with_wrong_prosthetic = spawn_entity(
        scenario.actor.world,
        [
            SurgeryBillComponent(
                part="arm",
                operation="install-prosthetic",
                prosthetic_item_id=str(wrong_prosthetic.id),
            )
        ],
    )
    room.add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), surgery_with_wrong_prosthetic.id
    )

    cases = [
        (
            UpdatePawnProfileHandler(),
            "update-pawn-profile",
            {"passions": ()},
            "passions must be a mapping",
            None,
        ),
        (
            ProgressJobBillHandler(),
            "progress-job-bill",
            {"bill_id": "not-an-id"},
            "invalid character or bill id",
            None,
        ),
        (
            ProgressJobBillHandler(),
            "progress-job-bill",
            {"bill_id": str(suspended_bill.id), "work": 0},
            "work must be positive",
            None,
        ),
        (
            ProgressJobBillHandler(),
            "progress-job-bill",
            {"bill_id": "entity_999"},
            "job bill does not exist",
            None,
        ),
        (
            ProgressJobBillHandler(),
            "progress-job-bill",
            {"bill_id": str(unreachable_bill.id)},
            "job bill is not reachable",
            None,
        ),
        (
            ProgressJobBillHandler(),
            "progress-job-bill",
            {"bill_id": str(wrong_kind.id)},
            "target is not a job bill",
            None,
        ),
        (
            ProgressJobBillHandler(),
            "progress-job-bill",
            {"bill_id": str(suspended_bill.id)},
            "job bill is suspended",
            None,
        ),
        (
            ProgressJobBillHandler(),
            "progress-job-bill",
            {"bill_id": str(complete_bill.id)},
            "job bill is already complete",
            None,
        ),
        (
            SetPrisonerPolicyHandler(),
            "set-prisoner-policy",
            {"prisoner_id": str(prisoner.id), "policy": "visit"},
            "prisoner policy is required",
            None,
        ),
        (
            SetPrisonerPolicyHandler(),
            "set-prisoner-policy",
            {"prisoner_id": "entity_999", "policy": "hold"},
            "prisoner does not exist",
            None,
        ),
        (
            SetPrisonerPolicyHandler(),
            "set-prisoner-policy",
            {"prisoner_id": str(wrong_kind.id), "policy": "hold"},
            "target is not a prisoner",
            None,
        ),
        (
            RecruitPrisonerHandler(),
            "recruit-prisoner",
            {"prisoner_id": str(prisoner.id), "progress": 0},
            "progress must be positive",
            None,
        ),
        (
            RecruitPrisonerHandler(),
            "recruit-prisoner",
            {"prisoner_id": "entity_999"},
            "prisoner does not exist",
            None,
        ),
        (
            RecruitPrisonerHandler(),
            "recruit-prisoner",
            {"prisoner_id": str(distant_prisoner.id)},
            "prisoner is not present",
            None,
        ),
        (
            RecruitPrisonerHandler(),
            "recruit-prisoner",
            {"prisoner_id": str(wrong_kind.id)},
            "target is not a prisoner",
            None,
        ),
        (
            RecruitPrisonerHandler(),
            "recruit-prisoner",
            {"prisoner_id": str(prisoner.id)},
            "prisoner is not set for recruitment",
            None,
        ),
        (
            ResearchProjectHandler(),
            "research-project",
            {"project_id": "not-an-id"},
            "invalid character or research project id",
            None,
        ),
        (
            ResearchProjectHandler(),
            "research-project",
            {"project_id": str(unlocked_project.id), "work": 0},
            "work must be positive",
            None,
        ),
        (
            ResearchProjectHandler(),
            "research-project",
            {"project_id": "entity_999"},
            "research project does not exist",
            None,
        ),
        (
            ResearchProjectHandler(),
            "research-project",
            {"project_id": str(wrong_kind.id)},
            "target is not a research project",
            None,
        ),
        (
            ResearchProjectHandler(),
            "research-project",
            {"project_id": str(unlocked_project.id)},
            "research project is already unlocked",
            None,
        ),
        (
            ResolveColonyIncidentHandler(),
            "resolve-colony-incident",
            {"incident_id": "not-an-id"},
            "invalid character or incident id",
            None,
        ),
        (
            ResolveColonyIncidentHandler(),
            "resolve-colony-incident",
            {"incident_id": "entity_999"},
            "incident does not exist",
            None,
        ),
        (
            ResolveColonyIncidentHandler(),
            "resolve-colony-incident",
            {"incident_id": str(wrong_kind.id)},
            "target is not an incident",
            None,
        ),
        (
            ResolveColonyIncidentHandler(),
            "resolve-colony-incident",
            {"incident_id": str(resolved_incident.id)},
            "incident is already resolved",
            None,
        ),
        (
            CompleteTradeHandler(),
            "complete-trade",
            {"offer_id": "not-an-id"},
            "invalid character or trade offer id",
            None,
        ),
        (
            CompleteTradeHandler(),
            "complete-trade",
            {"offer_id": "entity_999"},
            "trade offer does not exist",
            None,
        ),
        (
            CompleteTradeHandler(),
            "complete-trade",
            {"offer_id": str(wrong_kind.id)},
            "target is not a trade offer",
            None,
        ),
        (
            CompleteTradeHandler(),
            "complete-trade",
            {"offer_id": str(trade_offer.id)},
            "missing trade goods",
            None,
        ),
        (
            FormCaravanHandler(),
            "form-caravan",
            {},
            "destination is required",
            None,
        ),
        (
            FormCaravanHandler(),
            "form-caravan",
            {"destination": "town", "cargo": ()},
            "cargo must be a mapping",
            None,
        ),
        (
            FormCaravanHandler(),
            "form-caravan",
            {"destination": "town", "cargo": {"wood": -1}},
            "cargo quantities must not be negative",
            None,
        ),
        (
            FormCaravanHandler(),
            "form-caravan",
            {"destination": "town", "cargo": {"wood": 1}},
            "missing caravan cargo",
            None,
        ),
        (
            PerformSurgeryHandler(),
            "perform-surgery",
            {"patient_id": "not-an-id", "surgery_id": str(surgery.id)},
            "invalid doctor, patient, or surgery id",
            None,
        ),
        (
            PerformSurgeryHandler(),
            "perform-surgery",
            {"patient_id": str(scenario.character), "surgery_id": "entity_999"},
            "patient or surgery does not exist",
            None,
        ),
        (
            PerformSurgeryHandler(),
            "perform-surgery",
            {"patient_id": str(distant_prisoner.id), "surgery_id": str(surgery.id)},
            "patient is not reachable",
            None,
        ),
        (
            PerformSurgeryHandler(),
            "perform-surgery",
            {"patient_id": str(scenario.character), "surgery_id": str(wrong_kind.id)},
            "target is not a surgery bill",
            None,
        ),
        (
            PerformSurgeryHandler(),
            "perform-surgery",
            {"patient_id": str(scenario.character), "surgery_id": str(completed_surgery.id)},
            "surgery is already complete",
            None,
        ),
        (
            PerformSurgeryHandler(),
            "perform-surgery",
            {"patient_id": str(scenario.character), "surgery_id": str(surgery.id)},
            "prosthetic does not exist",
            None,
        ),
        (
            PerformSurgeryHandler(),
            "perform-surgery",
            {
                "patient_id": str(scenario.character),
                "surgery_id": str(surgery_with_wrong_prosthetic.id),
            },
            "target prosthetic is not usable",
            None,
        ),
    ]
    for handler, command_type, payload, reason, character_id in cases:
        result = handler.execute(
            ctx,
            _handler_cmd(scenario, command_type, character_id=character_id, **payload),
        )
        assert result.ok is False
        assert result.reason == reason


def test_colonysim_fragments_cover_catalogue_state_variants():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    room = scenario.actor.world.get_entity(scenario.room_a)
    replace_component(character, WorkPriorityComponent(priorities={"doctor": 1}))
    replace_component(character, PawnProfileComponent(expectations="moderate"))
    replace_component(character, AllowedAreaComponent(room_ids=(str(scenario.room_a),)))
    replace_component(
        character,
        PrisonerComponent(recruitment_progress=2, recruitment_difficulty=5),
    )
    replace_component(character, BedRestComponent(started_at_epoch=0))
    replace_component(character, InfectionComponent(severity=0.3, immunity=0.2))
    replace_component(character, MentalStateComponent(state="sad", reason="rain"))
    part = spawn_entity(
        scenario.actor.world,
        [BodyPartHealthComponent(part="left paw", health=1.0, prosthetic="wooden paw")],
    )
    character.add_relationship(HasBodyPart(), part.id)
    missing_part = spawn_entity(scenario.actor.world, [])
    character.add_relationship(HasBodyPart(), missing_part.id)
    fixtures = [
        [JobComponent(job_type="haul", priority=1, completed=True)],
        [JobBillComponent(recipe_id="plank", work_required=5, work_done=1)],
        [ResearchProjectComponent(project_id="battery", work_required=5, unlocked=True)],
        [ColonyIncidentComponent(incident_type="raid", resolved=True)],
        [TradeOfferComponent(faction_id="traders", gives={"medicine": 1}, wants={"wood": 2})],
        [SurgeryBillComponent(part="left paw", operation="install-prosthetic", completed=True)],
        [CaravanComponent(destination="town", returned=True)],
        [ColonySimComponent(), ColonyWealthComponent(wealth=12, expectations="low")],
    ]
    for components in fixtures:
        entity = spawn_entity(scenario.actor.world, components)
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    fragments = colonysim_fragments(scenario.actor.world, character)

    assert "Work priorities: doctor:1." in fragments
    assert "Pawn expectations: moderate." in fragments
    assert f"Allowed work area rooms: {scenario.room_a}." in fragments
    assert "Prisoner policy: hold, recruitment 2.0/5.0." in fragments
    assert "You are on medical bed rest." in fragments
    assert "Infection: severity 0.30, immunity 0.20." in fragments
    assert "Mental state: sad (rain)." in fragments
    assert "Nearby job bill: plank 1.0/5.0 work." in fragments
    assert "Research project: battery (unlocked)." in fragments
    assert "Trade offer from traders: gives 1 medicine; wants 2 wood." in fragments
    assert "Body part left paw: health 1.0, prosthetic wooden paw." in fragments
    assert "Colony wealth is 12; expectations are low." in fragments
    assert not any("Colony incident: raid" in line for line in fragments)
    assert not any("Surgery bill: install-prosthetic" in line for line in fragments)
    assert not any("Caravan bound for town" in line for line in fragments)


def test_colonysim_surgery_can_install_reachable_prosthetic_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    room = scenario.actor.world.get_entity(scenario.room_a)
    prosthetic = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="wooden paw", kind="prosthetic"),
            ProstheticComponent(part="wooden paw"),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), prosthetic.id)
    surgery = spawn_entity(
        scenario.actor.world,
        [
            SurgeryBillComponent(
                part="left paw",
                operation="install-prosthetic",
                prosthetic_item_id=str(prosthetic.id),
            )
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), surgery.id)

    result = PerformSurgeryHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "perform-surgery",
            patient_id=str(scenario.character),
            surgery_id=str(surgery.id),
        ),
    )

    assert result.ok is True
    body_part_id = character.get_relationships(HasBodyPart)[0][1]
    body_part = scenario.actor.world.get_entity(body_part_id)
    assert body_part.get_component(BodyPartHealthComponent).prosthetic == "wooden paw"
    assert surgery.get_component(SurgeryBillComponent).completed is True
