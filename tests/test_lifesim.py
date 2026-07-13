"""Tests for life-sim romance, pregnancy, and family mechanics (spec 20.5-20.6)."""

from __future__ import annotations

from conftest import build_scenario, execute_handler

from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    ControlledBy,
    DeadComponent,
    DownedComponent,
    HealthComponent,
    IdentityComponent,
    Lane,
    LLMControllerComponent,
    SleepHandler,
    SleepingComponent,
    SuspendedComponent,
    WakeHandler,
    WorldClockComponent,
    build_submitted_command,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import (
    AdoptionCompletedEvent,
    BirthDueEvent,
    BirthResolvedEvent,
    CharacterDiedEvent,
    CommandRejectedEvent,
    PartnershipEndedEvent,
    PartnershipStartedEvent,
    event_base,
)
from bunnyland.core.handlers import HandlerContext
from bunnyland.foundation.policy.mechanics import (
    BoundaryTag,
    CharacterBoundaryComponent,
    install_policy,
)
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.prompts import ComponentPromptContext, PromptPerspective
from bunnyland.simpacks.colonysim.mechanics import Owns
from bunnyland.simpacks.daggersim.mechanics import OwnsProperty, PropertyDeedComponent
from bunnyland.simpacks.lifesim.mechanics import (
    AddWhimHandler,
    AdoptChildHandler,
    AgeComponent,
    AgingConsequence,
    AspirationComponent,
    AssessTaxHandler,
    BillComponent,
    BillPaidEvent,
    BirthDueComponent,
    BusinessOwnerComponent,
    BusinessPromotedEvent,
    BusinessPurchaseEvent,
    BusinessSaleEvent,
    BuyItemHandler,
    CareerComponent,
    CharacterProfileComponent,
    ChargeRentHandler,
    ChooseAspirationHandler,
    ClaimHomeHandler,
    ClaimRoomHandler,
    CompleteMilestoneHandler,
    CompleteWhimHandler,
    ConfigureAgingHandler,
    CustomerComponent,
    EndPartnershipHandler,
    FindJobHandler,
    GossipSpreadEvent,
    GoToWorkHandler,
    HasBill,
    HasRoutine,
    HasWhim,
    HomeComponent,
    HomeObjectComponent,
    HomeObjectMaintainedEvent,
    HomeObjectUsedEvent,
    HomeRestComponent,
    HouseholdComponent,
    HouseholdFundsComponent,
    HouseholdJoinedEvent,
    InheritanceRecordComponent,
    InheritedFrom,
    InvitationSentEvent,
    InviteOverHandler,
    JealousOf,
    JealousyTriggeredEvent,
    JobScheduleComponent,
    JoinHouseholdHandler,
    LifesimAgingPolicyChangedEvent,
    LifesimAgingPolicyComponent,
    LifeStageComponent,
    MaintainHomeObjectHandler,
    MentorshipCompletedEvent,
    MentorSkillHandler,
    MilestoneCompletedEvent,
    OpenBusinessHandler,
    OwnsBusiness,
    ParentOf,
    PartnerOf,
    PayBillHandler,
    PayWageHandler,
    PracticeSkillHandler,
    PregnancyComponent,
    ProfileUpdatedEvent,
    PromoteBusinessHandler,
    PromotionEarnedEvent,
    QuitJobHandler,
    RelationshipStatus,
    ReproductiveComponent,
    ReputationComponent,
    ResolveBirthHandler,
    RestfulSleepConsequence,
    RoomClaimComponent,
    RoutineComponent,
    RoutineDueConsequence,
    RoutineDueEvent,
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
    TaxAssessedEvent,
    UpdateProfileHandler,
    UseHomeObjectHandler,
    WagePaidEvent,
    WellRestedComponent,
    WellRestedEvent,
    WhimAddedEvent,
    WhimCompletedEvent,
    WhimComponent,
    WitnessRomanceHandler,
    WorkShiftCompletedEvent,
    _first_business,
    _lifesim_aging_policy,
    _living_character,
    _optional_bool,
    _optional_int,
    _parse_text_tuple,
    _participant_ids,
    _partner_edge,
    _routine_for_activity,
    _status_edge,
    _transfer_colony_ownership,
    _transfer_property_deeds,
    children_of,
    configure_lifesim_aging,
    inheritance_record_for_event,
    install_lifesim,
    kinship_label,
    lifesim_fragments,
    project_inheritance_for_death,
)

HOUR = 3600.0
LIFE_TAGS = frozenset({BoundaryTag.ROMANCE, BoundaryTag.ADULT, BoundaryTag.PREGNANCY})


def _install(actor):
    install_policy(actor, enabled=LIFE_TAGS)
    install_lifesim(actor)
    actor.register_handler(StartPartnershipHandler())
    actor.register_handler(StartPregnancyHandler())
    actor.register_handler(ResolveBirthHandler())
    actor.register_handler(AdoptChildHandler())
    actor.register_handler(ChooseAspirationHandler())
    actor.register_handler(CompleteMilestoneHandler())
    actor.register_handler(PracticeSkillHandler())
    actor.register_handler(StudySkillHandler())
    actor.register_handler(MentorSkillHandler())
    actor.register_handler(UpdateProfileHandler())
    actor.register_handler(AddWhimHandler())
    actor.register_handler(CompleteWhimHandler())
    actor.register_handler(UseHomeObjectHandler())
    actor.register_handler(MaintainHomeObjectHandler())
    actor.register_handler(InviteOverHandler())
    actor.register_handler(ConfigureAgingHandler())
    actor.register_handler(FindJobHandler())
    actor.register_handler(GoToWorkHandler())
    actor.register_handler(QuitJobHandler())
    actor.register_handler(PayWageHandler())
    actor.register_handler(AssessTaxHandler())
    actor.register_handler(ChargeRentHandler())
    actor.register_handler(PayBillHandler())
    actor.register_handler(OpenBusinessHandler())
    actor.register_handler(SellItemHandler())
    actor.register_handler(BuyItemHandler())
    actor.register_handler(PromoteBusinessHandler())
    actor.register_handler(JoinHouseholdHandler())
    actor.register_handler(ClaimHomeHandler())
    actor.register_handler(ClaimRoomHandler())
    actor.register_handler(SetRoutineHandler())
    actor.register_handler(SetRelationshipStatusHandler())
    actor.register_handler(SpreadGossipHandler())
    actor.register_handler(WitnessRomanceHandler())
    actor.register_handler(EndPartnershipHandler())


def _co_parent(scenario, *, boundary=None):
    components = [
        IdentityComponent(name="Hazel", kind="character"),
        CharacterComponent(species="bunny"),
        ReproductiveComponent(can_cause_pregnancy=True, species_group="bunny"),
    ]
    if boundary is not None:
        components.append(boundary)
    entity = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _child(scenario, *, name="Clover"):
    entity = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


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


def _cmd_for(scenario, character_id, command_type, **payload):
    generation = scenario.actor.current_generation(character_id, scenario.controller)
    assert generation is not None
    return build_submitted_command(
        character_id=str(character_id),
        controller_id=str(scenario.controller),
        controller_generation=generation,
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


async def test_aspiration_milestone_completion_can_reward_inventory_item():
    scenario = build_scenario()
    _install(scenario.actor)
    completed: list[MilestoneCompletedEvent] = []
    scenario.actor.bus.subscribe(MilestoneCompletedEvent, completed.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "choose-aspiration",
            name="Cozy Homemaker",
            milestones=("meet a friend",),
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "complete-milestone",
            milestone="meet a friend",
            reward_name="woven keepsake",
        )
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    aspiration = character.get_component(AspirationComponent)
    assert aspiration.name == "Cozy Homemaker"
    assert aspiration.completed == ("meet a friend",)
    reward_id = completed[0].reward_item_id
    assert reward_id is not None
    inventory_ids = {str(target_id) for _edge, target_id in character.get_relationships(Contains)}
    assert reward_id in inventory_ids


def test_complete_milestone_succeeds_without_reward_item():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AspirationComponent(name="Quiet Life", milestones=("rest",)))

    result = execute_handler(
        CompleteMilestoneHandler(),
        ctx,
        _handler_cmd(scenario, "complete-milestone", milestone="rest"),
    )

    assert result.ok is True
    event = result.events[0]
    assert isinstance(event, MilestoneCompletedEvent)
    assert event.reward_item_id is None
    assert character.get_component(AspirationComponent).completed == ("rest",)


def test_aspiration_and_milestone_handlers_reject_invalid_commands():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    choose = ChooseAspirationHandler()
    complete = CompleteMilestoneHandler()

    cases = [
        (
            choose,
            _handler_cmd(
                scenario,
                "choose-aspiration",
                character_id="not-an-id",
                name="Cozy Homemaker",
            ),
            "invalid character id",
        ),
        (
            choose,
            _handler_cmd(scenario, "choose-aspiration", name=" "),
            "aspiration name is required",
        ),
        (
            complete,
            _handler_cmd(scenario, "complete-milestone", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            complete,
            _handler_cmd(scenario, "complete-milestone", milestone="meet a friend"),
            "no aspiration selected",
        ),
    ]
    for handler, command, reason in cases:
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        AspirationComponent(
            name="Cozy Homemaker",
            milestones=("meet a friend",),
            completed=("meet a friend",),
        )
    )
    for command, reason in (
        (
            _handler_cmd(scenario, "complete-milestone", milestone=" "),
            "milestone is required",
        ),
        (
            _handler_cmd(scenario, "complete-milestone", milestone="cook dinner"),
            "milestone is not part of aspiration",
        ),
        (
            _handler_cmd(scenario, "complete-milestone", milestone="meet a friend"),
            "milestone already completed",
        ),
    ):
        result = execute_handler(complete, ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_lifesim_economy_and_skill_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)
    worker_id = _co_parent(scenario)
    distant_worker_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Distant Worker", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    ).id

    cases = [
        (
            PracticeSkillHandler(),
            _handler_cmd(scenario, "practice-skill", skill=" "),
            "skill is required",
        ),
        (
            PracticeSkillHandler(),
            _handler_cmd(scenario, "practice-skill", skill="cooking", xp=0),
            "xp must be positive",
        ),
        (
            StudySkillHandler(),
            _handler_cmd(scenario, "study-skill", skill=" "),
            "skill is required",
        ),
        (
            StudySkillHandler(),
            _handler_cmd(scenario, "study-skill", skill="logic", xp=-1),
            "xp must be positive",
        ),
        (
            MentorSkillHandler(),
            _handler_cmd(scenario, "mentor-skill", student_id="not-an-id"),
            "invalid mentor or student id",
        ),
        (
            MentorSkillHandler(),
            _handler_cmd(scenario, "mentor-skill", student_id="entity_999"),
            "student does not exist",
        ),
        (
            MentorSkillHandler(),
            _handler_cmd(
                scenario,
                "mentor-skill",
                student_id=str(distant_worker_id),
                skill="logic",
            ),
            "student is not present",
        ),
        (
            MentorSkillHandler(),
            _handler_cmd(scenario, "mentor-skill", student_id=str(worker_id), skill=" "),
            "skill is required",
        ),
        (
            MentorSkillHandler(),
            _handler_cmd(
                scenario,
                "mentor-skill",
                student_id=str(worker_id),
                skill="logic",
                xp=-1,
            ),
            "xp must be positive",
        ),
        (
            FindJobHandler(),
            _handler_cmd(scenario, "find-job", title=" "),
            "job title is required",
        ),
        (
            FindJobHandler(),
            _handler_cmd(scenario, "find-job", title="Archivist", hourly_pay=0),
            "hourly pay must be positive",
        ),
        (
            GoToWorkHandler(),
            _handler_cmd(scenario, "go-to-work"),
            "character has no job",
        ),
        (
            QuitJobHandler(),
            _handler_cmd(scenario, "quit-job"),
            "character has no job",
        ),
        (
            PayWageHandler(),
            _handler_cmd(scenario, "pay-wage", worker_id="not-an-id", amount=1),
            "invalid payer or worker id",
        ),
        (
            PayWageHandler(),
            _handler_cmd(scenario, "pay-wage", worker_id="entity_999", amount=1),
            "worker does not exist",
        ),
        (
            PayWageHandler(),
            _handler_cmd(
                scenario,
                "pay-wage",
                worker_id=str(distant_worker_id),
                amount=1,
            ),
            "worker is not present",
        ),
        (
            PayWageHandler(),
            _handler_cmd(scenario, "pay-wage", worker_id=str(worker_id), amount=0),
            "wage amount must be positive",
        ),
        (
            PayWageHandler(),
            _handler_cmd(scenario, "pay-wage", worker_id=str(worker_id), amount=1),
            "insufficient household funds",
        ),
        (
            AssessTaxHandler(),
            _handler_cmd(scenario, "assess-tax", amount=0),
            "tax amount must be positive",
        ),
        (
            ChargeRentHandler(),
            _handler_cmd(scenario, "charge-rent", tenant_id="not-an-id", amount=1),
            "invalid landlord or tenant id",
        ),
        (
            ChargeRentHandler(),
            _handler_cmd(scenario, "charge-rent", tenant_id="entity_999", amount=1),
            "tenant does not exist",
        ),
        (
            ChargeRentHandler(),
            _handler_cmd(
                scenario,
                "charge-rent",
                tenant_id=str(distant_worker_id),
                amount=1,
            ),
            "tenant is not present",
        ),
        (
            ChargeRentHandler(),
            _handler_cmd(scenario, "charge-rent", tenant_id=str(worker_id), amount=0),
            "rent amount must be positive",
        ),
        (
            OpenBusinessHandler(),
            _handler_cmd(scenario, "open-business", name=" "),
            "business name is required",
        ),
        (
            OpenBusinessHandler(),
            _handler_cmd(scenario, "open-business", name="Market", default_price=0),
            "default price must be positive",
        ),
    ]

    for handler, command, reason in cases:
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    actor.add_component(CareerComponent(title="Archivist", active=False))
    actor.add_component(JobScheduleComponent(next_shift_epoch=scenario.actor.epoch))
    result = execute_handler(GoToWorkHandler(), ctx, _handler_cmd(scenario, "go-to-work"))
    assert result.ok is False
    assert result.reason == "career is inactive"

    replace_component(actor, CareerComponent(title="Archivist", active=True))
    replace_component(actor, JobScheduleComponent(next_shift_epoch=scenario.actor.epoch + HOUR))
    result = execute_handler(GoToWorkHandler(), ctx, _handler_cmd(scenario, "go-to-work"))
    assert result.ok is False
    assert result.reason == "shift is not scheduled yet"


def test_lifesim_job_handlers_cover_existing_funds_no_promotion_and_quit_success():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)
    actor.add_component(HouseholdFundsComponent(balance=3))

    result = execute_handler(
        FindJobHandler(),
        ctx,
        _handler_cmd(scenario, "find-job", title="Archivist", hourly_pay=4),
    )

    assert result.ok is True
    assert actor.get_component(HouseholdFundsComponent).balance == 3

    replace_component(
        actor,
        CareerComponent(title="Archivist", hourly_pay=4, performance=0.0, active=True),
    )
    replace_component(
        actor,
        JobScheduleComponent(
            next_shift_epoch=scenario.actor.epoch,
            shift_duration_seconds=HOUR,
            shift_interval_seconds=2 * HOUR,
        ),
    )
    result = execute_handler(
        GoToWorkHandler(),
        ctx,
        _handler_cmd(scenario, "go-to-work", performance_gain=0.25),
    )

    assert result.ok is True
    assert [type(event) for event in result.events] == [WorkShiftCompletedEvent]
    assert actor.get_component(CareerComponent).performance == 0.25

    result = execute_handler(QuitJobHandler(), ctx, _handler_cmd(scenario, "quit-job"))

    assert result.ok is True
    assert actor.get_component(CareerComponent).active is False


def test_lifesim_pay_bill_handler_rejects_invalid_bills_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)

    result = execute_handler(PayBillHandler(), ctx, _handler_cmd(scenario, "pay-bill"))
    assert result.ok is False
    assert result.reason == "no unpaid bills"

    cases = [
        (
            _handler_cmd(scenario, "pay-bill", bill_id="entity_999"),
            "bill does not exist",
        ),
    ]

    other_bill = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=5, reason="not yours")],
    )
    cases.append(
        (
            _handler_cmd(scenario, "pay-bill", bill_id=str(other_bill.id)),
            "bill does not belong to character",
        )
    )

    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="paper scrap", kind="prop")],
    )
    actor.add_relationship(HasBill(), wrong_kind.id)
    cases.append(
        (
            _handler_cmd(scenario, "pay-bill", bill_id=str(wrong_kind.id)),
            "target is not a bill",
        )
    )

    paid_bill = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=5, reason="paid", paid_at_epoch=scenario.actor.epoch)],
    )
    actor.add_relationship(HasBill(), paid_bill.id)
    cases.append(
        (
            _handler_cmd(scenario, "pay-bill", bill_id=str(paid_bill.id)),
            "bill is already paid",
        )
    )

    unpaid_bill = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=5, reason="due")],
    )
    actor.add_relationship(HasBill(), unpaid_bill.id)
    cases.append(
        (
            _handler_cmd(scenario, "pay-bill", bill_id=str(unpaid_bill.id)),
            "insufficient household funds",
        )
    )

    for command, reason in cases:
        result = execute_handler(PayBillHandler(), ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_lifesim_business_household_and_social_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)
    worker_id = _co_parent(scenario)
    distant_worker_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Distant Worker", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    ).id
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="jam jar", kind="item")],
    )
    customer_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="shopper", kind="customer"),
            CustomerComponent(budget=0),
        ],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), customer_id
    )
    non_customer_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="display rack", kind="prop")],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), non_customer_id
    )
    unplaced_actor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="No Room", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )

    cases = [
        (
            SellItemHandler(),
            _handler_cmd(
                scenario,
                "sell-item",
                item_id="not-an-id",
                customer_id=str(customer_id),
            ),
            "invalid seller, item, or customer id",
        ),
        (
            SellItemHandler(),
            _handler_cmd(
                scenario,
                "sell-item",
                item_id=str(item.id),
                customer_id="entity_999",
            ),
            "item or customer does not exist",
        ),
        (
            SellItemHandler(),
            _handler_cmd(
                scenario,
                "sell-item",
                item_id=str(item.id),
                customer_id=str(customer_id),
            ),
            "character has no business",
        ),
        (
            BuyItemHandler(),
            _handler_cmd(
                scenario,
                "buy-item",
                seller_id="not-an-id",
                item_id=str(item.id),
            ),
            "invalid buyer, seller, or item id",
        ),
        (
            BuyItemHandler(),
            _handler_cmd(
                scenario,
                "buy-item",
                seller_id="entity_999",
                item_id=str(item.id),
            ),
            "seller or item does not exist",
        ),
        (
            BuyItemHandler(),
            _handler_cmd(
                scenario,
                "buy-item",
                seller_id=str(distant_worker_id),
                item_id=str(item.id),
            ),
            "seller is not reachable",
        ),
        (
            PromoteBusinessHandler(),
            _handler_cmd(scenario, "promote-business"),
            "character has no business",
        ),
        (
            JoinHouseholdHandler(),
            _handler_cmd(scenario, "join-household", household_id=" "),
            "household id is required",
        ),
        (
            ClaimHomeHandler(),
            _handler_cmd(scenario, "claim-home", room_id="entity_999"),
            "room does not exist",
        ),
        (
            ClaimHomeHandler(),
            _handler_cmd(
                scenario,
                "claim-home",
                character_id=str(unplaced_actor.id),
            ),
            "room does not exist",
        ),
        (
            ClaimRoomHandler(),
            _handler_cmd(scenario, "claim-room", room_id="entity_999"),
            "room does not exist",
        ),
        (
            ClaimRoomHandler(),
            _handler_cmd(
                scenario,
                "claim-room",
                character_id=str(unplaced_actor.id),
            ),
            "room does not exist",
        ),
        (
            SetRoutineHandler(),
            _handler_cmd(scenario, "set-routine", activity=" "),
            "activity is required",
        ),
        (
            SetRoutineHandler(),
            _handler_cmd(scenario, "set-routine", activity="water herbs", interval_seconds=0),
            "routine interval must be positive",
        ),
        (
            SetRelationshipStatusHandler(),
            _handler_cmd(
                scenario,
                "set-relationship-status",
                target_id="entity_999",
                status="friend",
            ),
            "target does not exist",
        ),
        (
            SetRelationshipStatusHandler(),
            _handler_cmd(
                scenario,
                "set-relationship-status",
                target_id=str(worker_id),
                status="enemy",
            ),
            "unsupported relationship status",
        ),
        (
            SetRelationshipStatusHandler(),
            _handler_cmd(
                scenario,
                "set-relationship-status",
                target_id=str(non_customer_id),
                status="friend",
            ),
            "target cannot participate",
        ),
        (
            SetRelationshipStatusHandler(),
            _handler_cmd(
                scenario,
                "set-relationship-status",
                target_id=str(distant_worker_id),
                status="friend",
            ),
            "target is not present",
        ),
        (
            SpreadGossipHandler(),
            _handler_cmd(scenario, "spread-gossip", target_id="entity_999", text="news"),
            "target does not exist",
        ),
        (
            SpreadGossipHandler(),
            _handler_cmd(
                scenario,
                "spread-gossip",
                target_id=str(distant_worker_id),
                text="news",
            ),
            "target is not present",
        ),
        (
            SpreadGossipHandler(),
            _handler_cmd(scenario, "spread-gossip", target_id=str(worker_id), text=" "),
            "gossip text is required",
        ),
    ]

    for handler, command, reason in cases:
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    result = execute_handler(
        SetRelationshipStatusHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "set-relationship-status",
            target_id=str(worker_id),
            status="friend",
        ),
    )
    assert result.ok is True
    result = execute_handler(
        SetRelationshipStatusHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "set-relationship-status",
            target_id=str(worker_id),
            status="rival",
        ),
    )
    assert result.ok is True
    assert _status_edge(actor, worker_id).status == "rival"

    target = scenario.actor.world.get_entity(worker_id)
    target.add_component(ReputationComponent(score=0, known_for=("news",)))
    result = execute_handler(
        SpreadGossipHandler(),
        ctx,
        _handler_cmd(scenario, "spread-gossip", target_id=str(worker_id), text="news"),
    )
    assert result.ok is True
    assert isinstance(result.events[0], GossipSpreadEvent)
    assert target.get_component(ReputationComponent).known_for == ("news",)

    business = spawn_entity(
        scenario.actor.world,
        [BusinessOwnerComponent(name="Jam Stand", default_price=2)],
    )
    actor.add_relationship(OwnsBusiness(), business.id)
    for command, reason in (
        (
            _handler_cmd(
                scenario,
                "sell-item",
                item_id=str(item.id),
                customer_id=str(customer_id),
            ),
            "item is not in inventory",
        ),
        (
            _handler_cmd(
                scenario,
                "sell-item",
                item_id=str(item.id),
                customer_id=str(non_customer_id),
            ),
            "item is not in inventory",
        ),
    ):
        result = execute_handler(SellItemHandler(), ctx, command)
        assert result.ok is False
        assert result.reason == reason

    actor.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    for command, reason in (
        (
            _handler_cmd(
                scenario,
                "sell-item",
                item_id=str(item.id),
                customer_id=str(non_customer_id),
            ),
            "target is not a customer",
        ),
        (
            _handler_cmd(
                scenario,
                "sell-item",
                item_id=str(item.id),
                customer_id=str(customer_id),
                price=0,
            ),
            "price must be positive",
        ),
        (
            _handler_cmd(
                scenario,
                "sell-item",
                item_id=str(item.id),
                customer_id=str(customer_id),
                price=2,
            ),
            "customer cannot afford item",
        ),
    ):
        result = execute_handler(SellItemHandler(), ctx, command)
        assert result.ok is False
        assert result.reason == reason

    seller = scenario.actor.world.get_entity(worker_id)
    seller_item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="muffin", kind="item")],
    )
    for command, reason in (
        (
            _handler_cmd(
                scenario,
                "buy-item",
                seller_id=str(worker_id),
                item_id=str(seller_item.id),
            ),
            "item is not for sale",
        ),
    ):
        result = execute_handler(BuyItemHandler(), ctx, command)
        assert result.ok is False
        assert result.reason == reason

    seller.add_relationship(Contains(mode=ContainmentMode.INVENTORY), seller_item.id)
    for command, reason in (
        (
            _handler_cmd(
                scenario,
                "buy-item",
                seller_id=str(worker_id),
                item_id=str(seller_item.id),
            ),
            "price must be positive",
        ),
        (
            _handler_cmd(
                scenario,
                "buy-item",
                seller_id=str(worker_id),
                item_id=str(seller_item.id),
                price=1,
            ),
            "insufficient household funds",
        ),
    ):
        result = execute_handler(BuyItemHandler(), ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_lifesim_family_and_relationship_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)
    partner_id = _co_parent(scenario)
    rival_id = _co_parent(scenario)
    distant_partner_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Distant Partner", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    ).id
    prop_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="stone marker", kind="prop")],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), prop_id
    )
    child_id = _child(scenario)
    adult_id = _co_parent(scenario)

    cases = [
        (
            WitnessRomanceHandler(),
            _handler_cmd(
                scenario,
                "witness-romance",
                partner_id="not-an-id",
                rival_id=str(rival_id),
            ),
            "invalid witness, partner, or rival id",
        ),
        (
            WitnessRomanceHandler(),
            _handler_cmd(
                scenario,
                "witness-romance",
                partner_id="entity_999",
                rival_id=str(rival_id),
            ),
            "partner or rival does not exist",
        ),
        (
            WitnessRomanceHandler(),
            _handler_cmd(
                scenario,
                "witness-romance",
                partner_id=str(partner_id),
                rival_id=str(rival_id),
            ),
            "witness is not partners with partner",
        ),
        (
            StartPartnershipHandler(),
            _handler_cmd(scenario, "start-partnership", target_id="entity_999"),
            "target does not exist",
        ),
        (
            StartPartnershipHandler(),
            _handler_cmd(scenario, "start-partnership", target_id=str(prop_id)),
            "target cannot participate",
        ),
        (
            StartPartnershipHandler(),
            _handler_cmd(
                scenario,
                "start-partnership",
                target_id=str(distant_partner_id),
            ),
            "target is not present",
        ),
        (
            EndPartnershipHandler(),
            _handler_cmd(scenario, "end-partnership", target_id="entity_999"),
            "target does not exist",
        ),
        (
            EndPartnershipHandler(),
            _handler_cmd(scenario, "end-partnership", target_id=str(partner_id)),
            "not partners",
        ),
        (
            StartPregnancyHandler(),
            _handler_cmd(scenario, "start-pregnancy", co_parent_id="entity_999"),
            "co-parent does not exist",
        ),
        (
            StartPregnancyHandler(),
            _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(prop_id)),
            "participant cannot participate",
        ),
        (
            StartPregnancyHandler(),
            _handler_cmd(
                scenario,
                "start-pregnancy",
                co_parent_id=str(distant_partner_id),
            ),
            "co-parent is not present",
        ),
        (
            ResolveBirthHandler(),
            _handler_cmd(scenario, "resolve-birth"),
            "birth is not due",
        ),
        (
            AdoptChildHandler(),
            _handler_cmd(scenario, "adopt-child", child_id="not-an-id"),
            "invalid parent or child id",
        ),
        (
            AdoptChildHandler(),
            _handler_cmd(scenario, "adopt-child", child_id="entity_999"),
            "child does not exist",
        ),
        (
            AdoptChildHandler(),
            _handler_cmd(scenario, "adopt-child", child_id=str(prop_id)),
            "participant cannot participate",
        ),
        (
            AdoptChildHandler(),
            _handler_cmd(scenario, "adopt-child", child_id=str(distant_partner_id)),
            "child is not present",
        ),
        (
            AdoptChildHandler(),
            _handler_cmd(scenario, "adopt-child", child_id=str(adult_id)),
            "target is not a child",
        ),
    ]

    for handler, command, reason in cases:
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    actor.add_relationship(PartnerOf(since_epoch=scenario.actor.epoch), partner_id)
    scenario.actor.world.get_entity(partner_id).add_relationship(
        PartnerOf(since_epoch=scenario.actor.epoch), scenario.character
    )
    result = execute_handler(
        StartPartnershipHandler(),
        ctx,
        _handler_cmd(scenario, "start-partnership", target_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "already partners"

    far_rival_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Rival", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    ).id
    result = execute_handler(
        WitnessRomanceHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "witness-romance",
            partner_id=str(partner_id),
            rival_id=str(far_rival_id),
        ),
    )
    assert result.ok is False
    assert result.reason == "participants are not present"

    actor.add_relationship(PartnerOf(since_epoch=0), partner_id)
    result = execute_handler(
        EndPartnershipHandler(),
        ctx,
        _handler_cmd(scenario, "end-partnership", target_id=str(partner_id)),
    )
    assert result.ok is True
    assert isinstance(result.events[0], PartnershipEndedEvent)
    assert not actor.has_relationship(PartnerOf, partner_id)

    actor.add_component(ReproductiveComponent(can_be_pregnant=True, species_group="bunny"))
    actor.add_component(
        PregnancyComponent(
            started_at_epoch=scenario.actor.epoch,
            due_at_epoch=scenario.actor.epoch + HOUR,
            co_parent_ids=(str(partner_id),),
        )
    )
    result = execute_handler(
        StartPregnancyHandler(),
        ctx,
        _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "already pregnant"
    actor.remove_component(PregnancyComponent)

    replace_component(
        actor,
        ReproductiveComponent(can_be_pregnant=False, species_group="bunny"),
    )
    result = execute_handler(
        StartPregnancyHandler(),
        ctx,
        _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "character cannot become pregnant"

    replace_component(
        actor,
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny"),
    )
    co_parent = scenario.actor.world.get_entity(partner_id)
    replace_component(
        co_parent,
        ReproductiveComponent(can_cause_pregnancy=False, species_group="bunny"),
    )
    result = execute_handler(
        StartPregnancyHandler(),
        ctx,
        _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "co-parent cannot cause pregnancy"

    replace_component(
        co_parent,
        ReproductiveComponent(can_cause_pregnancy=True, species_group="hare"),
    )
    result = execute_handler(
        StartPregnancyHandler(),
        ctx,
        _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "participants are not reproductively compatible"

    replace_component(
        co_parent,
        ReproductiveComponent(
            can_cause_pregnancy=True,
            species_group="bunny",
            fertility=0.0,
        ),
    )
    result = execute_handler(
        StartPregnancyHandler(),
        ctx,
        _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "fertility prevents pregnancy"

    replace_component(
        co_parent,
        ReproductiveComponent(can_cause_pregnancy=True, species_group="bunny"),
    )
    result = execute_handler(
        StartPregnancyHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "start-pregnancy",
            co_parent_id=str(partner_id),
            due_in_seconds=0,
        ),
    )
    assert result.ok is False
    assert result.reason == "due time must be in the future"

    actor.add_relationship(ParentOf(), child_id)
    result = execute_handler(
        AdoptChildHandler(),
        ctx,
        _handler_cmd(scenario, "adopt-child", child_id=str(child_id)),
    )
    assert result.ok is False
    assert result.reason == "already parent of child"


async def test_death_projects_inheritance_to_child_with_assets_and_persistence(tmp_path):
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    decedent = world.get_entity(scenario.character)
    heir_id = _child(scenario)
    heir = world.get_entity(heir_id)
    decedent.add_relationship(ParentOf(), heir_id)
    decedent.add_component(HouseholdFundsComponent(balance=17))
    heir.add_component(HouseholdFundsComponent(balance=5))

    keepsake = spawn_entity(world, [IdentityComponent(name="silver thimble", kind="item")])
    decedent.add_relationship(Contains(mode=ContainmentMode.INVENTORY), keepsake.id)
    business = spawn_entity(world, [BusinessOwnerComponent(name="Jam Stand")])
    decedent.add_relationship(OwnsBusiness(), business.id)
    world.get_entity(scenario.room_a).add_component(
        HomeComponent(owner_id=str(decedent.id), household_id="moss")
    )
    world.get_entity(scenario.room_b).add_component(
        RoomClaimComponent(claimed_by_id=str(decedent.id), claimed_at_epoch=1)
    )
    deed = spawn_entity(
        world,
        [
            IdentityComponent(name="Moss Road Cottage", kind="property"),
            PropertyDeedComponent(owner_id=str(decedent.id), purchased_at_epoch=2),
        ],
    )
    decedent.add_relationship(OwnsProperty(deed_id=str(deed.id), purchased_at_epoch=2), deed.id)
    workbench = spawn_entity(world, [IdentityComponent(name="family workbench", kind="station")])
    decedent.add_relationship(Owns(since_epoch=3), workbench.id)

    event = CharacterDiedEvent(
        **event_base(
            42,
            actor_id=str(decedent.id),
            target_ids=(str(decedent.id),),
            cause="old age",
        )
    )
    await scenario.actor.bus.publish(event)

    record_entity = inheritance_record_for_event(world, event.event_id)
    assert record_entity is not None
    record = record_entity.get_component(InheritanceRecordComponent)
    assert record.decedent_id == str(decedent.id)
    assert record.heir_id == str(heir.id)
    assert record.relationship == "child"
    assert record.inherited_item_ids == (str(keepsake.id),)
    assert record.inherited_business_ids == (str(business.id),)
    assert record.inherited_home_ids == (str(scenario.room_a),)
    assert record.inherited_room_claim_ids == (str(scenario.room_b),)
    assert record.inherited_property_ids == (str(deed.id),)
    assert record.inherited_ownership_ids == (str(workbench.id),)
    assert record.inherited_funds == 17
    assert heir.has_relationship(Contains, keepsake.id)
    assert not decedent.has_relationship(Contains, keepsake.id)
    assert heir.has_relationship(OwnsBusiness, business.id)
    assert heir.has_relationship(OwnsProperty, deed.id)
    assert heir.has_relationship(Owns, workbench.id)
    assert heir.get_component(HouseholdFundsComponent).balance == 22
    assert decedent.get_component(HouseholdFundsComponent).balance == 0
    assert world.get_entity(scenario.room_a).get_component(HomeComponent).owner_id == str(heir.id)
    assert world.get_entity(scenario.room_b).get_component(RoomClaimComponent).claimed_by_id == str(
        heir.id
    )
    assert world.get_entity(deed.id).get_component(PropertyDeedComponent).owner_id == str(heir.id)
    inherited_edge = heir.get_relationships(InheritedFrom)[0][0]
    assert inherited_edge.source_event_id == event.event_id
    assert inherited_edge.record_id == str(record_entity.id)
    assert any(
        "inherited child legacy from Juniper" in line for line in lifesim_fragments(world, heir)
    )

    path = tmp_path / "world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="inheritance"))
    loaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    loaded_record = inheritance_record_for_event(loaded.world, event.event_id)
    assert loaded_record is not None
    assert loaded_record.get_component(InheritanceRecordComponent).inherited_funds == 17
    loaded_heir = loaded.world.get_entity(heir.id)
    assert loaded_heir.has_relationship(InheritedFrom, decedent.id)
    assert any(
        "inherited child legacy from Juniper" in line
        for line in lifesim_fragments(loaded.world, loaded_heir)
    )


def test_inheritance_is_idempotent_and_falls_back_to_household_member():
    scenario = build_scenario()
    world = scenario.actor.world
    decedent = world.get_entity(scenario.character)
    decedent.add_component(HouseholdComponent(household_id="moss", name="Moss Burrow"))
    dead_child_id = _child(scenario, name="Bramble")
    world.get_entity(dead_child_id).add_component(DeadComponent(died_at_epoch=1, cause="past loss"))
    decedent.add_relationship(ParentOf(), dead_child_id)
    housemate_id = _co_parent(scenario)
    housemate = world.get_entity(housemate_id)
    housemate.add_component(HouseholdComponent(household_id="moss", name="Moss Burrow"))
    charm = spawn_entity(world, [IdentityComponent(name="house charm", kind="item")])
    decedent.add_relationship(Contains(mode=ContainmentMode.INVENTORY), charm.id)
    event = CharacterDiedEvent(
        **event_base(
            50,
            actor_id=str(decedent.id),
            target_ids=(str(decedent.id),),
            cause="winter fever",
        )
    )

    first = project_inheritance_for_death(world, event)
    duplicate = project_inheritance_for_death(world, event)

    assert first is not None
    assert duplicate is None
    record = first.get_component(InheritanceRecordComponent)
    assert record.heir_id == str(housemate.id)
    assert record.relationship == "household"
    assert housemate.has_relationship(Contains, charm.id)


def test_inheritance_skips_deaths_without_living_heirs():
    scenario = build_scenario()
    event = CharacterDiedEvent(
        **event_base(
            50,
            actor_id=str(scenario.character),
            target_ids=(str(scenario.character),),
            cause="winter fever",
        )
    )

    assert project_inheritance_for_death(scenario.actor.world, event) is None


def test_inheritance_covers_partner_existing_links_and_prompt_fallback():
    scenario = build_scenario()
    world = scenario.actor.world
    decedent = world.get_entity(scenario.character)
    partner_id = _co_parent(scenario)
    partner = world.get_entity(partner_id)
    decedent.add_relationship(PartnerOf(since_epoch=1), partner.id)
    partner.add_relationship(PartnerOf(since_epoch=1), decedent.id)
    decedent.add_component(HouseholdFundsComponent(balance=0))

    shared_keepsake = spawn_entity(world, [IdentityComponent(name="shared pin", kind="item")])
    decedent.add_relationship(Contains(mode=ContainmentMode.INVENTORY), shared_keepsake.id)
    partner.add_relationship(Contains(mode=ContainmentMode.INVENTORY), shared_keepsake.id)
    container = spawn_entity(world, [IdentityComponent(name="locked box", kind="container")])
    decedent.add_relationship(Contains(mode=ContainmentMode.CONTAINER), container.id)

    business = spawn_entity(world, [BusinessOwnerComponent(name="Soup Cart")])
    decedent.add_relationship(OwnsBusiness(), business.id)
    partner.add_relationship(OwnsBusiness(), business.id)
    world.get_entity(scenario.room_a).add_component(HomeComponent(owner_id="someone-else"))
    world.get_entity(scenario.room_b).add_component(
        RoomClaimComponent(claimed_by_id="someone-else", claimed_at_epoch=3)
    )

    undecorated_property = spawn_entity(
        world, [IdentityComponent(name="paper deed", kind="property")]
    )
    decedent.add_relationship(
        OwnsProperty(deed_id=str(undecorated_property.id), purchased_at_epoch=2),
        undecorated_property.id,
    )
    shared_property = spawn_entity(
        world,
        [
            IdentityComponent(name="Shared Cottage", kind="property"),
            PropertyDeedComponent(owner_id=str(decedent.id), purchased_at_epoch=4),
        ],
    )
    decedent.add_relationship(
        OwnsProperty(deed_id=str(shared_property.id), purchased_at_epoch=4),
        shared_property.id,
    )
    partner.add_relationship(
        OwnsProperty(deed_id=str(shared_property.id), purchased_at_epoch=4),
        shared_property.id,
    )
    shared_station = spawn_entity(world, [IdentityComponent(name="shared bench", kind="station")])
    decedent.add_relationship(Owns(since_epoch=5), shared_station.id)
    partner.add_relationship(Owns(since_epoch=5), shared_station.id)
    event = CharacterDiedEvent(
        **event_base(
            60,
            actor_id=str(decedent.id),
            target_ids=(str(decedent.id),),
            cause="winter fever",
        )
    )

    record_entity = project_inheritance_for_death(world, event)

    assert record_entity is not None
    record = record_entity.get_component(InheritanceRecordComponent)
    assert record.relationship == "partner"
    assert record.inherited_item_ids == (str(shared_keepsake.id),)
    assert record.inherited_business_ids == (str(business.id),)
    assert record.inherited_home_ids == ()
    assert record.inherited_room_claim_ids == ()
    assert record.inherited_funds == 0
    assert record.inherited_property_ids == tuple(
        sorted((str(shared_property.id), str(undecorated_property.id)))
    )
    assert record.inherited_ownership_ids == (str(shared_station.id),)
    assert partner.has_relationship(Contains, shared_keepsake.id)
    assert decedent.has_relationship(Contains, container.id)
    assert partner.has_relationship(OwnsBusiness, business.id)
    assert partner.has_relationship(OwnsProperty, shared_property.id)
    assert partner.has_relationship(Owns, shared_station.id)

    fallback_record_id = parse_entity_id("entity_998")
    assert fallback_record_id is not None
    lost_ancestor = spawn_entity(world, [IdentityComponent(name="Lost Ancestor", kind="character")])
    partner.add_relationship(
        InheritedFrom(
            source_event_id="fallback",
            inherited_at_epoch=61,
            relationship="household",
            record_id=str(fallback_record_id),
        ),
        lost_ancestor.id,
    )

    fragments = lifesim_fragments(world, partner)

    assert any("inherited partner legacy from Juniper" in line for line in fragments)
    assert any("You inherited household legacy from Lost Ancestor." in line for line in fragments)


def test_inheritance_skips_invalid_death_events():
    scenario = build_scenario()
    world = scenario.actor.world
    missing_event = CharacterDiedEvent(
        **event_base(
            70,
            actor_id="entity_999",
            target_ids=("entity_999",),
            cause="winter fever",
        )
    )
    anonymous_event = CharacterDiedEvent(
        **event_base(
            71,
            actor_id=None,
            target_ids=(),
            cause="winter fever",
        )
    )

    assert project_inheritance_for_death(world, missing_event) is None
    assert project_inheritance_for_death(world, anonymous_event) is None
    assert inheritance_record_for_event(world, "missing") is None


def test_lifesim_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cases = [
        (
            ChooseAspirationHandler(),
            "choose-aspiration",
            {"name": "Cozy Homemaker"},
            "invalid character id",
        ),
        (
            CompleteMilestoneHandler(),
            "complete-milestone",
            {"milestone": "meet a friend"},
            "invalid character id",
        ),
        (PracticeSkillHandler(), "practice-skill", {"skill": "cooking"}, "invalid character id"),
        (StudySkillHandler(), "study-skill", {"skill": "cooking"}, "invalid character id"),
        (
            MentorSkillHandler(),
            "mentor-skill",
            {"student_id": str(scenario.character), "skill": "logic"},
            "invalid mentor or student id",
        ),
        (FindJobHandler(), "find-job", {"title": "Archivist"}, "invalid character id"),
        (GoToWorkHandler(), "go-to-work", {}, "invalid character id"),
        (QuitJobHandler(), "quit-job", {}, "invalid character id"),
        (
            PayWageHandler(),
            "pay-wage",
            {"worker_id": str(scenario.character), "amount": 1},
            "invalid payer or worker id",
        ),
        (AssessTaxHandler(), "assess-tax", {"amount": 1}, "invalid character id"),
        (
            ChargeRentHandler(),
            "charge-rent",
            {"tenant_id": str(scenario.character), "amount": 1},
            "invalid landlord or tenant id",
        ),
        (PayBillHandler(), "pay-bill", {}, "invalid character id"),
        (OpenBusinessHandler(), "open-business", {"name": "Market"}, "invalid character id"),
        (
            SellItemHandler(),
            "sell-item",
            {"item_id": str(scenario.room_a), "customer_id": str(scenario.character)},
            "invalid seller, item, or customer id",
        ),
        (
            BuyItemHandler(),
            "buy-item",
            {"seller_id": str(scenario.character), "item_id": str(scenario.room_a)},
            "invalid buyer, seller, or item id",
        ),
        (
            PromoteBusinessHandler(),
            "promote-business",
            {"business_id": str(scenario.room_a)},
            "invalid character id",
        ),
        (
            JoinHouseholdHandler(),
            "join-household",
            {"household_id": "burrow", "name": "Burrow"},
            "invalid character id",
        ),
        (
            ClaimHomeHandler(),
            "claim-home",
            {"room_id": str(scenario.room_a)},
            "invalid character id",
        ),
        (
            ClaimRoomHandler(),
            "claim-room",
            {"room_id": str(scenario.room_a)},
            "invalid character id",
        ),
        (
            SetRoutineHandler(),
            "set-routine",
            {"activity": "water herbs"},
            "invalid character id",
        ),
        (
            SetRelationshipStatusHandler(),
            "set-relationship-status",
            {"target_id": str(scenario.character), "status": "friend"},
            "invalid character or target id",
        ),
        (
            SpreadGossipHandler(),
            "spread-gossip",
            {"target_id": str(scenario.character), "text": "helpful"},
            "invalid character or target id",
        ),
        (
            WitnessRomanceHandler(),
            "witness-romance",
            {
                "partner_id": str(scenario.character),
                "rival_id": str(scenario.character),
            },
            "invalid witness, partner, or rival id",
        ),
        (
            StartPartnershipHandler(),
            "start-partnership",
            {"target_id": str(scenario.character)},
            "invalid character or target id",
        ),
        (
            EndPartnershipHandler(),
            "end-partnership",
            {"target_id": str(scenario.character)},
            "invalid character or target id",
        ),
        (
            StartPregnancyHandler(),
            "start-pregnancy",
            {"co_parent_id": str(scenario.character)},
            "invalid character or co-parent id",
        ),
        (ResolveBirthHandler(), "resolve-birth", {"child_name": "Clover"}, "invalid character id"),
        (
            AdoptChildHandler(),
            "adopt-child",
            {"child_id": str(scenario.character)},
            "invalid parent or child id",
        ),
    ]

    for handler, command_type, payload, reason in cases:
        result = execute_handler(
            handler,
            ctx,
            _handler_cmd(
                scenario,
                command_type,
                character_id="not-an-id",
                **payload,
            ),
        )
        assert result.ok is False
        assert result.reason == reason


def test_resolve_birth_handles_unplaced_parent_and_invalid_co_parent_id():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)
    actor.add_component(
        PregnancyComponent(
            started_at_epoch=0,
            due_at_epoch=0,
            co_parent_ids=("not-an-entity",),
        )
    )
    actor.add_component(BirthDueComponent(due_since_epoch=0))
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )

    result = execute_handler(
        ResolveBirthHandler(),
        ctx,
        _handler_cmd(scenario, "resolve-birth", child_name="Clover"),
    )

    assert result.ok is True
    event = result.events[0]
    assert isinstance(event, BirthResolvedEvent)
    child_id = parse_entity_id(event.child_id)
    assert child_id is not None
    assert actor.has_relationship(ParentOf, child_id)
    assert not scenario.actor.world.get_entity(scenario.room_a).has_relationship(
        Contains,
        child_id,
    )


async def test_lifesim_aging_is_disabled_by_default():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AgeComponent(born_at_epoch=0))
    character.add_component(LifeStageComponent(stage="child"))

    await scenario.actor.tick(100 * 365 * 24 * 60 * 60)

    policies = list(
        scenario.actor.world.query().with_all([LifesimAgingPolicyComponent]).execute_entities()
    )
    assert policies[0].get_component(LifesimAgingPolicyComponent).natural_aging is False
    assert character.get_component(LifeStageComponent).stage == "child"
    assert not character.has_component(DownedComponent)
    assert not character.has_component(DeadComponent)


async def test_enabled_lifesim_aging_reuses_core_death_lifecycle():
    scenario = build_scenario()
    _install(scenario.actor)
    configure_lifesim_aging(
        scenario.actor,
        natural_aging=True,
        adult_age_seconds=10,
        elder_age_seconds=20,
        natural_death_age_seconds=30,
        natural_death_checks=1,
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AgeComponent(born_at_epoch=0))
    character.add_component(LifeStageComponent(stage="child"))
    character.add_component(HealthComponent(current=100.0, maximum=100.0))
    died: list[CharacterDiedEvent] = []
    scenario.actor.bus.subscribe(CharacterDiedEvent, died.append)

    await scenario.actor.tick(20.0)

    assert character.get_component(LifeStageComponent).stage == "elder"
    assert character.get_component(HealthComponent).current == 100.0
    assert not character.has_component(DownedComponent)

    await scenario.actor.tick(10.0)

    assert character.get_component(HealthComponent).current == 0.0
    assert character.get_component(DownedComponent).cause == "natural causes"
    assert not character.has_component(DeadComponent)
    assert died == []

    await scenario.actor.tick(1.0)

    assert character.get_component(DeadComponent).cause == "natural causes"
    assert not character.has_component(DownedComponent)
    assert died[-1].cause == "natural causes"


def test_lifesim_aging_policy_is_world_level_and_persists(tmp_path):
    scenario = build_scenario()
    _install(scenario.actor)

    configure_lifesim_aging(scenario.actor, natural_aging=True)
    path = tmp_path / "world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="aging"))

    loaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    policies = list(loaded.world.query().with_all([LifesimAgingPolicyComponent]).execute_entities())
    assert len(policies) == 1
    assert policies[0].get_component(LifesimAgingPolicyComponent).natural_aging is True


def test_install_lifesim_can_enable_natural_aging_server_wide():
    scenario = build_scenario()

    install_lifesim(scenario.actor, natural_aging=True)

    policies = list(
        scenario.actor.world.query().with_all([LifesimAgingPolicyComponent]).execute_entities()
    )
    assert len(policies) == 1
    assert policies[0].get_component(LifesimAgingPolicyComponent).natural_aging is True


def test_aging_consequence_covers_stage_and_terminal_edge_paths():
    scenario = build_scenario()
    configure_lifesim_aging(
        scenario.actor,
        natural_aging=True,
        adult_age_seconds=10,
        elder_age_seconds=30,
        natural_death_age_seconds=50,
        natural_death_checks=2,
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AgeComponent(born_at_epoch=0))

    young_adult = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Fern", kind="character"),
            CharacterComponent(species="bunny"),
            AgeComponent(born_at_epoch=40),
            LifeStageComponent(stage="child"),
        ],
    )
    young_child = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Twig", kind="character"),
            CharacterComponent(species="bunny"),
            AgeComponent(born_at_epoch=55),
            LifeStageComponent(stage="child"),
        ],
    )
    already_downed = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Bramble", kind="character"),
            CharacterComponent(species="bunny"),
            AgeComponent(born_at_epoch=0),
            DownedComponent(downed_at_epoch=1, cause="fall", checks_remaining=1),
            HealthComponent(current=7.0, maximum=10.0),
        ],
    )
    suspended = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Mallow", kind="character"),
            CharacterComponent(species="bunny"),
            AgeComponent(born_at_epoch=0),
            LifeStageComponent(stage="child"),
            SuspendedComponent(reason="paused"),
        ],
    )
    dead = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Sorrel", kind="character"),
            CharacterComponent(species="bunny"),
            AgeComponent(born_at_epoch=0),
            LifeStageComponent(stage="child"),
            DeadComponent(died_at_epoch=1, cause="old age"),
        ],
    )

    assert AgingConsequence().process(scenario.actor.world, 60) == []

    assert character.get_component(LifeStageComponent).stage == "elder"
    assert character.get_component(HealthComponent).current == 0.0
    assert character.get_component(DownedComponent).checks_remaining == 2
    assert young_adult.get_component(LifeStageComponent).stage == "adult"
    assert young_child.get_component(LifeStageComponent).stage == "child"
    assert already_downed.get_component(HealthComponent).current == 7.0
    assert suspended.get_component(LifeStageComponent).stage == "child"
    assert dead.get_component(LifeStageComponent).stage == "child"


async def test_practice_and_study_progress_skill_and_emit_level_up():
    scenario = build_scenario()
    _install(scenario.actor)
    changed: list[SkillXPChangedEvent] = []
    leveled: list[SkillLeveledEvent] = []
    scenario.actor.bus.subscribe(SkillXPChangedEvent, changed.append)
    scenario.actor.bus.subscribe(SkillLeveledEvent, leveled.append)

    await scenario.actor.submit(_cmd(scenario, "practice-skill", skill="cooking", xp=60))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "study-skill", skill="cooking", xp=50))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    skills = character.get_component(SkillSetComponent)
    assert skills.levels["cooking"] == 1
    assert skills.xp["cooking"] == 10
    assert changed[-1].level == 1
    assert leveled[0].skill == "cooking"
    fragments = lifesim_fragments(scenario.actor.world, character)
    assert any("Skill cooking: level 1, 10 xp" in line for line in fragments)


async def test_mentor_skill_progresses_present_student():
    scenario = build_scenario()
    _install(scenario.actor)
    student = _co_parent(scenario)
    mentored: list[MentorshipCompletedEvent] = []
    scenario.actor.bus.subscribe(MentorshipCompletedEvent, mentored.append)

    await scenario.actor.submit(_cmd(scenario, "practice-skill", skill="gardening", xp=100))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "mentor-skill", student_id=str(student), skill="gardening", xp=95)
    )
    await scenario.actor.tick(HOUR)

    student_entity = scenario.actor.world.get_entity(student)
    skills = student_entity.get_component(SkillSetComponent)
    assert skills.levels["gardening"] == 1
    assert skills.xp["gardening"] == 0
    assert mentored[0].student_id == str(student)


async def test_career_shift_pays_funds_and_can_promote():
    scenario = build_scenario()
    _install(scenario.actor)
    shifts: list[WorkShiftCompletedEvent] = []
    promotions: list[PromotionEarnedEvent] = []
    scenario.actor.bus.subscribe(WorkShiftCompletedEvent, shifts.append)
    scenario.actor.bus.subscribe(PromotionEarnedEvent, promotions.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "find-job",
            title="Burrow Barista",
            hourly_pay=12,
            shift_duration_seconds=2 * 3600,
            shift_interval_seconds=HOUR,
            next_shift_epoch=0,
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "go-to-work", performance_gain=1.0))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    career = character.get_component(CareerComponent)
    assert career.title == "Burrow Barista"
    assert career.level == 2
    assert career.hourly_pay == 17
    assert character.get_component(HouseholdFundsComponent).balance == 24
    schedule = character.get_component(JobScheduleComponent)
    assert schedule.next_shift_epoch == scenario.actor.epoch + HOUR
    assert shifts[0].earned == 24
    assert promotions[0].level == 2


async def test_household_economy_pays_wages_taxes_rent_and_bills():
    scenario = build_scenario()
    _install(scenario.actor)
    employer = scenario.actor.world.get_entity(scenario.character)
    employer.add_component(HouseholdFundsComponent(balance=100))
    worker = spawn_entity(
        scenario.actor.world,
        [
            ActionPointsComponent(current=5.0, maximum=5.0),
            IdentityComponent(name="Marigold", kind="character"),
            CharacterComponent(),
            HouseholdFundsComponent(balance=5),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), worker.id
    )
    worker.add_relationship(ControlledBy(generation=0), scenario.controller)
    wages: list[WagePaidEvent] = []
    taxes: list[TaxAssessedEvent] = []
    paid: list[BillPaidEvent] = []
    scenario.actor.bus.subscribe(WagePaidEvent, wages.append)
    scenario.actor.bus.subscribe(TaxAssessedEvent, taxes.append)
    scenario.actor.bus.subscribe(BillPaidEvent, paid.append)

    await scenario.actor.submit(_cmd(scenario, "pay-wage", worker_id=str(worker.id), amount=25))
    await scenario.actor.tick(HOUR)

    assert employer.get_component(HouseholdFundsComponent).balance == 75
    assert worker.get_component(HouseholdFundsComponent).balance == 30
    assert wages[0].worker_balance == 30

    await scenario.actor.submit(_cmd(scenario, "assess-tax", amount=20, reason="market tax"))
    await scenario.actor.tick(HOUR)
    tax_bill_id = employer.get_relationships(HasBill)[0][1]
    assert taxes[0].bill_id == str(tax_bill_id)

    await scenario.actor.submit(_cmd(scenario, "pay-bill", bill_id=str(tax_bill_id)))
    await scenario.actor.tick(HOUR)

    assert employer.get_component(HouseholdFundsComponent).balance == 55
    assert (
        scenario.actor.world.get_entity(tax_bill_id).get_component(BillComponent).paid_at_epoch
        == scenario.actor.epoch
    )

    await scenario.actor.submit(
        _cmd(scenario, "charge-rent", tenant_id=str(worker.id), amount=15, reason="stall rent")
    )
    await scenario.actor.tick(HOUR)
    rent_bill_id = worker.get_relationships(HasBill)[0][1]

    await scenario.actor.submit(
        _cmd_for(scenario, worker.id, "pay-bill", bill_id=str(rent_bill_id))
    )
    await scenario.actor.tick(HOUR)

    assert worker.get_component(HouseholdFundsComponent).balance == 15
    assert employer.get_component(HouseholdFundsComponent).balance == 70
    assert paid[-1].bill_id == str(rent_bill_id)
    fragments = lifesim_fragments(scenario.actor.world, worker)
    assert not any("Unpaid bills" in line for line in fragments)


async def test_pay_bill_without_id_selects_first_unpaid_bill_then_rejects_when_clear():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HouseholdFundsComponent(balance=25))
    paid_bill = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=5, reason="old fee", paid_at_epoch=1)],
    )
    not_a_bill = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="bill-shaped note", kind="prop")],
    )
    unpaid_bill = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=12, reason="garden dues", creditor_id="not-an-id")],
    )
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(HasBill, {})[
        parse_entity_id("entity_999")
    ] = HasBill()
    character.add_relationship(HasBill(), paid_bill.id)
    character.add_relationship(HasBill(), not_a_bill.id)
    character.add_relationship(HasBill(), unpaid_bill.id)
    paid: list[BillPaidEvent] = []
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(BillPaidEvent, paid.append)
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "pay-bill"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "pay-bill"))
    await scenario.actor.tick(HOUR)

    assert paid[0].bill_id == str(unpaid_bill.id)
    assert character.get_component(HouseholdFundsComponent).balance == 13
    assert unpaid_bill.get_component(BillComponent).paid_at_epoch == HOUR
    assert any(event.reason == "no unpaid bills" for event in rejects)


async def test_business_sale_moves_item_out_of_inventory_and_pays_funds():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    item = spawn_entity(scenario.actor.world, [IdentityComponent(name="berry tart", kind="item")])
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    customer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Marigold", kind="character"),
            CharacterComponent(),
            CustomerComponent(budget=30),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), customer.id
    )
    sales: list[BusinessSaleEvent] = []
    scenario.actor.bus.subscribe(BusinessSaleEvent, sales.append)

    await scenario.actor.submit(
        _cmd(scenario, "open-business", name="Juniper's Table", default_price=10)
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "sell-item", item_id=str(item.id), customer_id=str(customer.id), price=15)
    )
    await scenario.actor.tick(HOUR)

    business_id = character.get_relationships(OwnsBusiness)[0][1]
    business = scenario.actor.world.get_entity(business_id).get_component(BusinessOwnerComponent)
    assert business.sales_count == 1
    assert character.get_component(HouseholdFundsComponent).balance == 15
    assert not character.has_relationship(Contains, item.id)
    assert customer.get_component(CustomerComponent).budget == 15
    assert sales[0].item_id == str(item.id)


async def test_promote_business_marks_business_and_updates_fragments():
    scenario = build_scenario()
    _install(scenario.actor)
    promoted: list[BusinessPromotedEvent] = []
    scenario.actor.bus.subscribe(BusinessPromotedEvent, promoted.append)

    await scenario.actor.submit(
        _cmd(scenario, "open-business", name="Moon Market", default_price=8)
    )
    await scenario.actor.tick(HOUR)
    business_id = scenario.actor.world.get_entity(scenario.character).get_relationships(
        OwnsBusiness
    )[0][1]
    await scenario.actor.submit(_cmd(scenario, "promote-business", business_id=str(business_id)))
    await scenario.actor.tick(HOUR)

    business = scenario.actor.world.get_entity(business_id).get_component(BusinessOwnerComponent)
    character = scenario.actor.world.get_entity(scenario.character)
    assert business.promoted is True
    assert promoted[0].business_name == "Moon Market"
    assert "You own Moon Market; 0 sales." in lifesim_fragments(scenario.actor.world, character)


async def test_buy_item_without_business_moves_inventory_and_pays_seller():
    scenario = build_scenario()
    _install(scenario.actor)
    buyer = scenario.actor.world.get_entity(scenario.character)
    buyer.add_component(HouseholdFundsComponent(balance=40))
    seller = _co_parent(scenario)
    seller_entity = scenario.actor.world.get_entity(seller)
    seller_entity.add_component(HouseholdFundsComponent(balance=5))
    item = spawn_entity(scenario.actor.world, [IdentityComponent(name="moon jam", kind="item")])
    seller_entity.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    purchases: list[BusinessPurchaseEvent] = []
    scenario.actor.bus.subscribe(BusinessPurchaseEvent, purchases.append)

    await scenario.actor.submit(
        _cmd(scenario, "buy-item", seller_id=str(seller), item_id=str(item.id), price=18)
    )
    await scenario.actor.tick(HOUR)

    assert buyer.has_relationship(Contains, item.id)
    assert not seller_entity.has_relationship(Contains, item.id)
    assert buyer.get_component(HouseholdFundsComponent).balance == 22
    assert seller_entity.get_component(HouseholdFundsComponent).balance == 23
    assert purchases[0].business_name == ""
    assert purchases[0].balance == 22


async def test_buy_item_from_business_increments_sales_count():
    scenario = build_scenario()
    _install(scenario.actor)
    buyer = scenario.actor.world.get_entity(scenario.character)
    buyer.add_component(HouseholdFundsComponent(balance=40))
    seller = _co_parent(scenario)
    seller_entity = scenario.actor.world.get_entity(seller)
    seller_entity.add_component(HouseholdFundsComponent(balance=0))
    business = spawn_entity(
        scenario.actor.world,
        [BusinessOwnerComponent(name="Hazel's Stall", default_price=11)],
    )
    seller_entity.add_relationship(OwnsBusiness(), business.id)
    item = spawn_entity(scenario.actor.world, [IdentityComponent(name="star biscuit", kind="item")])
    seller_entity.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    purchases: list[BusinessPurchaseEvent] = []
    scenario.actor.bus.subscribe(BusinessPurchaseEvent, purchases.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "buy-item",
            seller_id=str(seller),
            item_id=str(item.id),
            business_id=str(business.id),
        )
    )
    await scenario.actor.tick(HOUR)

    assert business.get_component(BusinessOwnerComponent).sales_count == 1
    assert seller_entity.get_component(HouseholdFundsComponent).balance == 11
    assert buyer.get_component(HouseholdFundsComponent).balance == 29
    assert purchases[0].business_name == "Hazel's Stall"


async def test_household_home_and_room_claims_update_world_state():
    scenario = build_scenario()
    _install(scenario.actor)
    joined: list[HouseholdJoinedEvent] = []
    scenario.actor.bus.subscribe(HouseholdJoinedEvent, joined.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-household", household_id="burrow-1", name="Moss Burrow")
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "claim-home", room_id=str(scenario.room_a)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "claim-room", room_id=str(scenario.room_b)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    home = scenario.actor.world.get_entity(scenario.room_a).get_component(HomeComponent)
    claim = scenario.actor.world.get_entity(scenario.room_b).get_component(RoomClaimComponent)
    household = character.get_component(HouseholdComponent)
    assert household.household_id == "burrow-1"
    assert household.name == "Moss Burrow"
    assert home.owner_id == str(scenario.character)
    assert home.household_id == "burrow-1"
    assert claim.claimed_by_id == str(scenario.character)
    assert joined[0].household_name == "Moss Burrow"


async def test_routine_due_consequence_advances_next_due_without_auto_commanding():
    scenario = build_scenario()
    _install(scenario.actor)
    due: list[RoutineDueEvent] = []
    scenario.actor.bus.subscribe(RoutineDueEvent, due.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "set-routine",
            activity="water the window herbs",
            interval_seconds=HOUR,
            next_due_epoch=HOUR,
        )
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR)

    routine_id = scenario.actor.world.get_entity(scenario.character).get_relationships(HasRoutine)[
        0
    ][1]
    routine = scenario.actor.world.get_entity(routine_id).get_component(RoutineComponent)
    assert routine.activity == "water the window herbs"
    assert routine.last_completed_epoch == scenario.actor.epoch
    assert routine.next_due_epoch == scenario.actor.epoch + HOUR
    assert due[0].activity == "water the window herbs"


def test_set_routine_updates_existing_routine_for_activity():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    routine = spawn_entity(
        scenario.actor.world,
        [RoutineComponent(activity="garden", interval_seconds=HOUR, next_due_epoch=HOUR)],
    )
    character.add_relationship(HasRoutine(), routine.id)

    result = execute_handler(
        SetRoutineHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "set-routine",
            activity="garden",
            interval_seconds=2 * HOUR,
            next_due_epoch=3 * HOUR,
        ),
    )

    assert result.ok is True
    assert character.get_relationships(HasRoutine) == [(HasRoutine(), routine.id)]
    updated = routine.get_component(RoutineComponent)
    assert updated.interval_seconds == 2 * HOUR
    assert updated.next_due_epoch == 3 * HOUR


def test_routine_due_consequence_skips_routines_without_live_owners():
    scenario = build_scenario()
    routine = spawn_entity(
        scenario.actor.world,
        [RoutineComponent(activity="garden", interval_seconds=HOUR, next_due_epoch=0)],
    )

    assert RoutineDueConsequence().process(scenario.actor.world, HOUR) == []
    assert routine.get_component(RoutineComponent).last_completed_epoch is None


def test_restful_sleep_consequence_removes_home_rest_after_moving_away():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(SleepingComponent(started_at_epoch=0))
    character.add_component(HomeRestComponent(asleep_since_epoch=0, room_id=str(scenario.room_a)))

    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        scenario.character,
    )

    assert RestfulSleepConsequence().process(scenario.actor.world, HOUR) == []
    assert not character.has_component(HomeRestComponent)


async def test_sleeping_in_claimed_home_grants_well_rested_skill_bonus():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.register_handler(SleepHandler())
    scenario.actor.register_handler(WakeHandler())
    rested: list[WellRestedEvent] = []
    scenario.actor.bus.subscribe(WellRestedEvent, rested.append)

    # Claim the current room as home, then sleep there.
    await scenario.actor.submit(_cmd(scenario, "claim-home", room_id=str(scenario.room_a)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "sleep"))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_component(HomeRestComponent)

    await scenario.actor.tick(2 * HOUR)  # keep sleeping at home
    await scenario.actor.submit(_cmd(scenario, "wake"))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(HomeRestComponent)
    assert character.has_component(WellRestedComponent)
    assert rested and rested[0].slept_seconds == int(3 * HOUR)
    assert rested[0].room_id == str(scenario.room_a)
    fragments = lifesim_fragments(scenario.actor.world, character)
    assert any("well-rested" in line for line in fragments)

    # Practicing while rested grants the bonus: 100 base xp * 1.25 = 125 -> level 1, 25 over.
    await scenario.actor.submit(_cmd(scenario, "practice-skill", skill="cooking", xp=100))
    await scenario.actor.tick(HOUR)
    skills = scenario.actor.world.get_entity(scenario.character).get_component(SkillSetComponent)
    assert skills.levels["cooking"] == 1
    assert skills.xp["cooking"] == 25


async def test_sleeping_away_from_home_grants_no_rest_buff():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.register_handler(SleepHandler())
    scenario.actor.register_handler(WakeHandler())
    rested: list[WellRestedEvent] = []
    scenario.actor.bus.subscribe(WellRestedEvent, rested.append)

    # The starting room is not claimed, so sleeping there earns nothing.
    await scenario.actor.submit(_cmd(scenario, "sleep"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(2 * HOUR)
    await scenario.actor.submit(_cmd(scenario, "wake"))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(HomeRestComponent)
    assert not character.has_component(WellRestedComponent)
    assert rested == []


async def test_sleep_shorter_than_threshold_grants_no_rest_buff():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.register_handler(SleepHandler())
    scenario.actor.register_handler(WakeHandler())
    rested: list[WellRestedEvent] = []
    scenario.actor.bus.subscribe(WellRestedEvent, rested.append)

    await scenario.actor.submit(_cmd(scenario, "claim-home", room_id=str(scenario.room_a)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "sleep"))
    await scenario.actor.tick(0.0)  # falls asleep at home; rest starts now
    await scenario.actor.submit(_cmd(scenario, "wake"))
    await scenario.actor.tick(HOUR / 2)  # only half an hour of rest

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(HomeRestComponent)
    assert not character.has_component(WellRestedComponent)
    assert rested == []


async def test_start_partnership_creates_bidirectional_edges():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    started: list[PartnershipStartedEvent] = []
    scenario.actor.bus.subscribe(PartnershipStartedEvent, started.append)

    await scenario.actor.submit(_cmd(scenario, "start-partnership", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    partner = scenario.actor.world.get_entity(target)
    assert character.has_relationship(PartnerOf, target)
    assert partner.has_relationship(PartnerOf, scenario.character)
    assert started[0].partner_id == str(target)


async def test_end_partnership_removes_bidirectional_edges():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    partner = scenario.actor.world.get_entity(target)
    character.add_relationship(PartnerOf(since_epoch=0), target)
    partner.add_relationship(PartnerOf(since_epoch=0), scenario.character)
    ended: list[PartnershipEndedEvent] = []
    scenario.actor.bus.subscribe(PartnershipEndedEvent, ended.append)

    await scenario.actor.submit(_cmd(scenario, "end-partnership", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert not character.has_relationship(PartnerOf, target)
    assert not partner.has_relationship(PartnerOf, scenario.character)
    assert ended[0].partner_id == str(target)


async def test_relationship_status_transition_is_prompt_visible():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "set-relationship-status",
            target_id=str(target),
            status="friend",
        )
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    fragments = lifesim_fragments(scenario.actor.world, character)
    assert any("Hazel is your friend" in line for line in fragments)


async def test_gossip_changes_target_reputation_and_prompt_context():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    gossip: list[GossipSpreadEvent] = []
    scenario.actor.bus.subscribe(GossipSpreadEvent, gossip.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "spread-gossip",
            target_id=str(target),
            text="rescued a neighbor",
            reputation_delta=0.25,
        )
    )
    await scenario.actor.tick(HOUR)

    target_entity = scenario.actor.world.get_entity(target)
    reputation = target_entity.get_component(ReputationComponent)
    assert reputation.score == 0.25
    assert reputation.known_for == ("rescued a neighbor",)
    assert gossip[0].target_id == str(target)
    fragments = lifesim_fragments(scenario.actor.world, target_entity)
    assert any("rescued a neighbor" in line for line in fragments)


async def test_witnessed_romance_between_partner_and_rival_triggers_jealousy():
    scenario = build_scenario()
    _install(scenario.actor)
    partner = _co_parent(scenario)
    rival = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Poppy", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rival.id
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(PartnerOf(since_epoch=0), partner)
    events: list[JealousyTriggeredEvent] = []
    scenario.actor.bus.subscribe(JealousyTriggeredEvent, events.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "witness-romance",
            partner_id=str(partner),
            rival_id=str(rival.id),
            intensity=0.75,
        )
    )
    await scenario.actor.tick(HOUR)

    jealousy_edges = character.get_relationships(JealousOf)
    assert len(jealousy_edges) == 1
    jealousy, target_id = jealousy_edges[0]
    assert target_id == rival.id
    assert jealousy.partner_id == str(partner)
    assert jealousy.intensity == 0.75
    assert events[0].rival_id == str(rival.id)


async def test_start_pregnancy_requires_policy_consent():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(ReproductiveComponent(can_be_pregnant=True, species_group="bunny"))
    target = _co_parent(
        scenario,
        boundary=CharacterBoundaryComponent(denied=frozenset({BoundaryTag.PREGNANCY})),
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(HOUR)

    assert not character.has_component(PregnancyComponent)
    assert any("consented" in r.reason for r in rejects)


async def test_pregnancy_becomes_due_while_suspended_but_birth_waits_for_resume():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(ReproductiveComponent(can_be_pregnant=True, species_group="bunny"))
    target = _co_parent(scenario)
    due: list[BirthDueEvent] = []
    scenario.actor.bus.subscribe(BirthDueEvent, due.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(0.0)
    assert character.has_component(PregnancyComponent)

    suspended_controller = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, suspended_controller.id)
    await scenario.actor.tick(HOUR * 2)

    assert character.has_component(SuspendedComponent)
    assert character.has_component(BirthDueComponent)
    assert len(due) == 1
    children = [target_id for _edge, target_id in character.get_relationships(ParentOf)]
    assert children == []


async def test_relationship_pregnancy_and_birth_create_llm_controlled_child():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(ReproductiveComponent(can_be_pregnant=True, species_group="bunny"))
    target = _co_parent(scenario)
    resolved: list[BirthResolvedEvent] = []
    scenario.actor.bus.subscribe(BirthResolvedEvent, resolved.append)

    await scenario.actor.submit(_cmd(scenario, "start-partnership", target_id=str(target)))
    await scenario.actor.tick(HOUR)
    assert character.has_relationship(PartnerOf, target)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR * 2)
    await scenario.actor.submit(_cmd(scenario, "resolve-birth", child_name="Clover"))
    await scenario.actor.tick(HOUR)

    assert not character.has_component(PregnancyComponent)
    assert not character.has_component(BirthDueComponent)
    child_id = resolved[0].child_id
    child = scenario.actor.world.get_entity(
        next(target_id for _edge, target_id in character.get_relationships(ParentOf))
    )
    assert str(child.id) == child_id
    assert child.get_component(IdentityComponent).name == "Clover"
    assert child.get_component(AgeComponent).born_at_epoch == scenario.actor.epoch
    assert child.get_component(LifeStageComponent).stage == "child"
    assert scenario.actor.world.get_entity(target).has_relationship(ParentOf, child.id)
    controllers = [target_id for _edge, target_id in child.get_relationships(ControlledBy)]
    assert len(controllers) == 1
    controller = scenario.actor.world.get_entity(controllers[0])
    assert controller.has_component(LLMControllerComponent)


async def test_adopt_child_creates_parent_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    child = _child(scenario)
    adopted: list[AdoptionCompletedEvent] = []
    scenario.actor.bus.subscribe(AdoptionCompletedEvent, adopted.append)

    await scenario.actor.submit(_cmd(scenario, "adopt-child", child_id=str(child)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(ParentOf, child)
    assert adopted[0].child_id == str(child)
    assert adopted[0].parent_id == str(scenario.character)


async def test_adopt_child_rejects_non_child_target():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "adopt-child", child_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert any(r.reason == "target is not a child" for r in rejects)


def test_lifesim_fragments_describe_partner_and_pregnancy():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    partner = _co_parent(scenario)
    child = _child(scenario)
    character.add_relationship(PartnerOf(since_epoch=0), partner)
    character.add_relationship(ParentOf(), child)
    character.add_component(
        PregnancyComponent(started_at_epoch=0, due_at_epoch=10, co_parent_ids=(str(partner),))
    )

    fragments = lifesim_fragments(scenario.actor.world, character)

    assert any("partners with Hazel" in line for line in fragments)
    assert any("pregnant" in line for line in fragments)
    assert any("Your children: Clover" in line for line in fragments)


def test_lifesim_component_prompt_fragments_respect_visibility_and_targets():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    viewer = spawn_entity(world, [CharacterComponent()])
    room = world.get_entity(scenario.room_a)
    room.add_component(HomeComponent(owner_id=str(character.id)))
    self_ctx = ComponentPromptContext.for_entity(world, character)
    external_ctx = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=viewer),
    )
    home_ctx = ComponentPromptContext.for_entity(
        world,
        room,
        perspective=self_ctx.perspective,
        target=character,
    )
    external_home_ctx = ComponentPromptContext.for_entity(
        world,
        room,
        perspective=external_ctx.perspective,
        target=character,
    )

    assert LifeStageComponent(stage="adult").prompt_fragments(self_ctx) == (
        "Your life stage is adult.",
    )
    assert LifeStageComponent(stage="adult").prompt_fragments(external_ctx) == ()
    assert room.get_component(HomeComponent).prompt_fragments(home_ctx) == (
        "Your home is Mosslit Burrow.",
    )
    assert room.get_component(HomeComponent).prompt_fragments(external_home_ctx) == ()
    assert WhimComponent(want="garden").prompt_fragments(home_ctx) == ("Current whim: garden.",)
    assert WhimComponent(want="garden").prompt_fragments(external_home_ctx) == ()
    assert BillComponent(amount=12, reason="rent").prompt_fragments(home_ctx) == ("rent (12)",)
    assert BillComponent(amount=12, reason="rent").prompt_fragments(external_home_ctx) == ()
    assert BusinessOwnerComponent(name="Tea Cart").prompt_fragments(home_ctx) == (
        "You own Tea Cart; 0 sales.",
    )
    assert BusinessOwnerComponent(name="Tea Cart").prompt_fragments(external_home_ctx) == ()
    assert RoutineComponent(activity="garden", next_due_epoch=9).prompt_fragments(home_ctx) == (
        "Routine: garden due at epoch 9.",
    )
    assert (
        RoutineComponent(activity="garden", next_due_epoch=9).prompt_fragments(external_home_ctx)
        == ()
    )


def test_lifesim_fragments_describe_aspiration_career_funds_routine_and_jealousy():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    partner = _co_parent(scenario)
    rival = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Poppy", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rival.id
    )
    routine = spawn_entity(
        scenario.actor.world,
        [RoutineComponent(activity="tend shop", next_due_epoch=123)],
    )
    character.add_component(
        AspirationComponent(
            name="Cozy Magnate",
            milestones=("open shop",),
            completed=("open shop",),
        )
    )
    character.add_component(CareerComponent(title="Archivist", level=3, active=True))
    character.add_component(HouseholdFundsComponent(balance=77))
    character.add_relationship(HasRoutine(), routine.id)
    character.add_relationship(
        JealousOf(partner_id=str(partner), intensity=0.5, triggered_at_epoch=10),
        rival.id,
    )

    fragments = lifesim_fragments(scenario.actor.world, character)

    assert "Your aspiration is Cozy Magnate; completed: open shop." in fragments
    assert "Your career is Archivist, level 3." in fragments
    assert "Household funds: 77." in fragments
    assert "Routine: tend shop due at epoch 123." in fragments
    assert "You feel jealous of Poppy over Hazel." in fragments


def test_lifesim_fragments_describe_parents():
    scenario = build_scenario()
    child = _child(scenario)
    parent = scenario.actor.world.get_entity(scenario.character)
    parent.add_relationship(ParentOf(), child)

    fragments = lifesim_fragments(scenario.actor.world, scenario.actor.world.get_entity(child))

    assert any("Your parents: Juniper" in line for line in fragments)


def test_lifesim_fragments_skip_empty_reputation_labels():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(ReputationComponent(score=0.5))

    fragments = lifesim_fragments(scenario.actor.world, character)

    assert not any(line.startswith("You are known for:") for line in fragments)


def test_lifesim_fragments_cover_fallbacks_and_skipped_relationships():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(LifeStageComponent(stage="adult"))
    character.add_component(AspirationComponent(name="Quiet Life"))
    character.add_component(CareerComponent(title="Retired Scout", active=False))
    character.add_component(HouseholdComponent(household_id="burrow-1"))
    character.add_component(WellRestedComponent(expires_at_epoch=100))
    character.add_component(ReputationComponent(score=1.0, known_for=("kindness", "craft")))
    character.add_component(SkillSetComponent(levels={"cooking": 2, "logic": 1}, xp={"logic": 3.5}))
    character.add_component(
        PregnancyComponent(started_at_epoch=0, due_at_epoch=10, co_parent_ids=())
    )
    character.add_component(BirthDueComponent(due_since_epoch=10))

    unpaid = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=12, reason="burrow rent")],
    )
    paid = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=5, reason="tea", paid_at_epoch=3)],
    )
    not_a_bill = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Receipt", kind="item")],
    )
    character.add_relationship(HasBill(), unpaid.id)
    character.add_relationship(HasBill(), paid.id)
    character.add_relationship(HasBill(), not_a_bill.id)

    business = spawn_entity(
        scenario.actor.world,
        [BusinessOwnerComponent(name="Moon Market", sales_count=4)],
    )
    not_a_business = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Market Stall", kind="item")],
    )
    character.add_relationship(OwnsBusiness(), business.id)
    character.add_relationship(OwnsBusiness(), not_a_business.id)

    room_a = scenario.actor.world.get_entity(scenario.room_a)
    room_b = scenario.actor.world.get_entity(scenario.room_b)
    room_a.add_component(HomeComponent(owner_id=str(character.id)))
    room_a.add_component(RoomClaimComponent(claimed_by_id=str(character.id), claimed_at_epoch=1))
    room_b.add_component(HomeComponent(owner_id="someone-else"))
    room_b.add_component(RoomClaimComponent(claimed_by_id="someone-else", claimed_at_epoch=1))

    routine = spawn_entity(
        scenario.actor.world,
        [RoutineComponent(activity="garden", next_due_epoch=44)],
    )
    not_a_routine = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Checklist", kind="item")],
    )
    character.add_relationship(HasRoutine(), routine.id)
    character.add_relationship(HasRoutine(), not_a_routine.id)

    rival = spawn_entity(scenario.actor.world, [CharacterComponent(species="bunny")])
    partner = spawn_entity(scenario.actor.world, [CharacterComponent(species="bunny")])
    character.add_relationship(
        JealousOf(partner_id=str(partner.id), intensity=0.25, triggered_at_epoch=1),
        rival.id,
    )
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(JealousOf, {})[
        parse_entity_id("entity_998")
    ] = JealousOf(partner_id="not-an-id", intensity=0.5, triggered_at_epoch=2)

    partner_without_name = spawn_entity(
        scenario.actor.world,
        [CharacterComponent(species="bunny")],
    )
    partner_with_wrong_status = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent(species="bunny")],
    )
    character.add_relationship(PartnerOf(since_epoch=0), partner_without_name.id)
    character.add_relationship(
        PartnerOf(since_epoch=0, status="apart"),
        partner_with_wrong_status.id,
    )
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(PartnerOf, {})[
        parse_entity_id("entity_997")
    ] = PartnerOf(since_epoch=0)

    relationship_target = spawn_entity(
        scenario.actor.world,
        [CharacterComponent(species="bunny")],
    )
    character.add_relationship(
        RelationshipStatus(status="neighbor", since_epoch=1),
        relationship_target.id,
    )
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(
        RelationshipStatus, {}
    )[parse_entity_id("entity_996")] = RelationshipStatus(status="rival", since_epoch=1)

    child_without_name = spawn_entity(
        scenario.actor.world,
        [CharacterComponent(species="bunny")],
    )
    character.add_relationship(ParentOf(), child_without_name.id)
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(ParentOf, {})[
        parse_entity_id("entity_995")
    ] = ParentOf()
    unnamed_parent = spawn_entity(scenario.actor.world, [CharacterComponent(species="bunny")])
    unnamed_parent.add_relationship(ParentOf(), character.id)

    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(HasBill, {})[
        parse_entity_id("entity_994")
    ] = HasBill()
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(OwnsBusiness, {})[
        parse_entity_id("entity_993")
    ] = OwnsBusiness()
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(HasRoutine, {})[
        parse_entity_id("entity_992")
    ] = HasRoutine()

    fragments = lifesim_fragments(scenario.actor.world, character)

    assert "Your life stage is adult." in fragments
    assert "Your aspiration is Quiet Life." in fragments
    assert "Household funds: 0." not in fragments
    assert "Your career is Retired Scout, level 1." not in fragments
    assert "Unpaid bills: burrow rent (12)." in fragments
    assert "You own Moon Market; 4 sales." in fragments
    assert "Your household is burrow-1." in fragments
    assert "Your home is Mosslit Burrow." in fragments
    assert "Rooms you claim: Mosslit Burrow." in fragments
    assert "You are well-rested after sleeping in your own home." in fragments
    assert "Routine: garden due at epoch 44." in fragments
    assert "You are known for: kindness, craft." in fragments
    assert "Skill cooking: level 2, 0 xp." in fragments
    assert "Skill logic: level 1, 3.5 xp." in fragments
    assert "You feel jealous of someone over someone." in fragments
    assert "You are pregnant (due now)." in fragments
    assert "You are partners with someone." in fragments
    assert "someone is your neighbor." in fragments
    assert "Your children: someone." in fragments
    assert "Your parents: someone." in fragments


def test_status_edge_and_routine_lookup_cover_match_and_miss_paths():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    target = _co_parent(scenario)
    matching = RelationshipStatus(status="friendly", intensity=2.0, since_epoch=1)
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Poppy", kind="character"), CharacterComponent()],
    )
    wrong_routine = spawn_entity(
        scenario.actor.world,
        [RoutineComponent(activity="sleep", next_due_epoch=10)],
    )
    not_a_routine = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="calendar note", kind="prop")],
    )
    matching_routine = spawn_entity(
        scenario.actor.world,
        [RoutineComponent(activity="tend shop", next_due_epoch=20)],
    )

    character.add_relationship(RelationshipStatus(status="awkward", since_epoch=0), other.id)
    character.add_relationship(matching, target)
    character.add_relationship(HasRoutine(), wrong_routine.id)
    character.add_relationship(HasRoutine(), not_a_routine.id)
    scenario.actor.world._relationships.setdefault(character.id, {}).setdefault(HasRoutine, {})[
        parse_entity_id("entity_999")
    ] = HasRoutine()
    character.add_relationship(HasRoutine(), matching_routine.id)

    assert _status_edge(character, target) == matching
    assert _status_edge(character, parse_entity_id("entity_999")) is None
    assert _routine_for_activity(scenario.actor.world, character, "tend shop") == matching_routine
    assert _routine_for_activity(scenario.actor.world, character, "garden") is None
    assert _partner_edge(character, target) is None
    assert _lifesim_aging_policy(scenario.actor.world) == LifesimAgingPolicyComponent()
    assert _first_business(scenario.actor.world, character) is None


def test_kinship_queries_return_parent_child_partner_and_sibling_labels():
    scenario = build_scenario()
    parent = scenario.actor.world.get_entity(scenario.character)
    child = _child(scenario, name="Clover")
    sibling = _child(scenario, name="Fern")
    partner = _co_parent(scenario)
    parent.add_relationship(ParentOf(), child)
    parent.add_relationship(ParentOf(), sibling)
    parent.add_relationship(PartnerOf(since_epoch=0), partner)

    assert children_of(scenario.actor.world, scenario.character) == tuple(
        sorted((str(child), str(sibling)))
    )
    assert kinship_label(scenario.actor.world, child, scenario.character) == "parent"
    assert kinship_label(scenario.actor.world, scenario.character, child) == "child"
    assert kinship_label(scenario.actor.world, scenario.character, partner) == "partner"
    assert kinship_label(scenario.actor.world, child, sibling) == "sibling"
    assert kinship_label(scenario.actor.world, child, child) == "self"
    assert kinship_label(scenario.actor.world, scenario.character, scenario.room_a) is None


async def test_lifesim_profile_whims_home_objects_invites_and_aging_controls():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    guest_id = _co_parent(scenario)
    home_object = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="reading chair", kind="furniture"),
            HomeObjectComponent(affordance="reading", cleanliness=0.4, condition=0.5),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), home_object.id
    )

    profile_events: list[ProfileUpdatedEvent] = []
    whim_added: list[WhimAddedEvent] = []
    whim_done: list[WhimCompletedEvent] = []
    used: list[HomeObjectUsedEvent] = []
    maintained: list[HomeObjectMaintainedEvent] = []
    invited: list[InvitationSentEvent] = []
    aging: list[LifesimAgingPolicyChangedEvent] = []
    scenario.actor.bus.subscribe(ProfileUpdatedEvent, profile_events.append)
    scenario.actor.bus.subscribe(WhimAddedEvent, whim_added.append)
    scenario.actor.bus.subscribe(WhimCompletedEvent, whim_done.append)
    scenario.actor.bus.subscribe(HomeObjectUsedEvent, used.append)
    scenario.actor.bus.subscribe(HomeObjectMaintainedEvent, maintained.append)
    scenario.actor.bus.subscribe(InvitationSentEvent, invited.append)
    scenario.actor.bus.subscribe(LifesimAgingPolicyChangedEvent, aging.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "update-profile",
            traits=("bookish", "tidy"),
            interests=("reading",),
            preferred_routine="morning tea",
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "add-whim", want="read a book", reward_xp=7))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "complete-whim", whim_id=whim_added[0].whim_id))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "use-home-object", object_id=str(home_object.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "maintain-home-object",
            object_id=str(home_object.id),
            action="upgrade",
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "invite-over",
            guest_id=str(guest_id),
            room_id=str(scenario.room_a),
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "configure-aging", natural_aging=True))
    await scenario.actor.tick(HOUR)

    assert character.get_component(CharacterProfileComponent).traits == ("bookish", "tidy")
    whim_id = parse_entity_id(whim_added[0].whim_id)
    assert character.has_relationship(HasWhim, whim_id)
    assert scenario.actor.world.get_entity(whim_id).get_component(WhimComponent).completed_at_epoch
    home_state = home_object.get_component(HomeObjectComponent)
    assert home_state.upgrade_level == 1
    assert home_state.condition == 0.75
    assert used[0].affordance == "reading"
    assert maintained[0].action == "upgrade"
    assert whim_done[0].want == "read a book"
    assert invited[0].guest_id == str(guest_id)
    assert aging[0].natural_aging is True
    fragments = lifesim_fragments(scenario.actor.world, character)
    assert "Your traits: bookish, tidy." in fragments
    assert "Natural aging is on." in fragments


async def test_configure_aging_uses_world_clock_when_policy_is_missing():
    scenario = build_scenario()
    scenario.actor.register_handler(ConfigureAgingHandler())

    await scenario.actor.submit(_cmd(scenario, "configure-aging", natural_aging=True))
    await scenario.actor.tick(HOUR)

    clock = next(scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities())
    assert clock.get_component(LifesimAgingPolicyComponent).natural_aging is True


def test_lifesim_catalogue_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    other_room = scenario.actor.world.get_entity(scenario.room_b)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain box", kind="prop")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    unreachable_object = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far chair", kind="furniture"),
            HomeObjectComponent(affordance="sit"),
        ],
    )
    other_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unreachable_object.id)
    broken_object = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="broken chair", kind="furniture"),
            HomeObjectComponent(affordance="sit", condition=0.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), broken_object.id)
    home_object = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clean chair", kind="furniture"),
            HomeObjectComponent(affordance="sit", cleanliness=0.2, condition=0.5),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), home_object.id)
    guest_id = _co_parent(scenario)
    no_component_whim = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="not whim", kind="prop")],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        HasWhim(), no_component_whim.id
    )
    completed_whim = spawn_entity(
        scenario.actor.world,
        [WhimComponent(want="done", completed_at_epoch=1)],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        HasWhim(), completed_whim.id
    )
    no_reward_whim = spawn_entity(
        scenario.actor.world,
        [WhimComponent(want="quiet", reward_xp=0)],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        HasWhim(), no_reward_whim.id
    )

    cases = [
        (
            UpdateProfileHandler(),
            "update-profile",
            {},
            "invalid character id",
            "not-an-id",
        ),
        (AddWhimHandler(), "add-whim", {}, "invalid character id", "not-an-id"),
        (AddWhimHandler(), "add-whim", {}, "whim want is required", None),
        (
            AddWhimHandler(),
            "add-whim",
            {"want": "bad", "reward_xp": -1},
            "reward xp must not be negative",
            None,
        ),
        (
            CompleteWhimHandler(),
            "complete-whim",
            {"whim_id": "not-an-id"},
            "invalid character or whim id",
            None,
        ),
        (
            CompleteWhimHandler(),
            "complete-whim",
            {"whim_id": "entity_999"},
            "whim does not exist",
            None,
        ),
        (
            CompleteWhimHandler(),
            "complete-whim",
            {"whim_id": str(home_object.id)},
            "whim does not belong to you",
            None,
        ),
        (
            CompleteWhimHandler(),
            "complete-whim",
            {"whim_id": str(no_component_whim.id)},
            "target is not a whim",
            None,
        ),
        (
            CompleteWhimHandler(),
            "complete-whim",
            {"whim_id": str(completed_whim.id)},
            "whim already completed",
            None,
        ),
        (
            UseHomeObjectHandler(),
            "use-home-object",
            {"object_id": "not-an-id"},
            "invalid character or object id",
            None,
        ),
        (
            UseHomeObjectHandler(),
            "use-home-object",
            {"object_id": "entity_999"},
            "object does not exist",
            None,
        ),
        (
            UseHomeObjectHandler(),
            "use-home-object",
            {"object_id": str(unreachable_object.id)},
            "object is not reachable",
            None,
        ),
        (
            UseHomeObjectHandler(),
            "use-home-object",
            {"object_id": str(wrong_kind.id)},
            "target is not a home object",
            None,
        ),
        (
            UseHomeObjectHandler(),
            "use-home-object",
            {"object_id": str(broken_object.id)},
            "home object is broken",
            None,
        ),
        (
            MaintainHomeObjectHandler(),
            "maintain-home-object",
            {"object_id": str(home_object.id), "action": "polish"},
            "maintenance action is required",
            None,
        ),
        (
            MaintainHomeObjectHandler(),
            "maintain-home-object",
            {"object_id": "entity_999", "action": "clean"},
            "object does not exist",
            None,
        ),
        (
            MaintainHomeObjectHandler(),
            "maintain-home-object",
            {"object_id": str(unreachable_object.id), "action": "clean"},
            "object is not reachable",
            None,
        ),
        (
            MaintainHomeObjectHandler(),
            "maintain-home-object",
            {"object_id": str(wrong_kind.id), "action": "clean"},
            "target is not a home object",
            None,
        ),
        (
            InviteOverHandler(),
            "invite-over",
            {"guest_id": "not-an-id"},
            "invalid character or guest id",
            None,
        ),
        (
            InviteOverHandler(),
            "invite-over",
            {"guest_id": "entity_999"},
            "guest does not exist",
            None,
        ),
        (
            InviteOverHandler(),
            "invite-over",
            {"guest_id": str(guest_id), "room_id": "entity_999"},
            "invitation room does not exist",
            None,
        ),
        (
            InviteOverHandler(),
            "invite-over",
            {"guest_id": str(guest_id), "room_id": str(wrong_kind.id)},
            "invitation target is not a room",
            None,
        ),
        (
            InviteOverHandler(),
            "invite-over",
            {"guest_id": str(guest_id), "room_id": str(scenario.room_b)},
            "you cannot invite guests there",
            None,
        ),
        (ConfigureAgingHandler(), "configure-aging", {}, "invalid character id", "not-an-id"),
    ]
    for handler, command_type, payload, reason, character_id in cases:
        result = execute_handler(
            handler,
            ctx,
            _handler_cmd(scenario, command_type, character_id=character_id, **payload),
        )
        assert result.ok is False
        assert result.reason == reason

    for action in ("clean", "repair", "decorate"):
        result = execute_handler(
            MaintainHomeObjectHandler(),
            ctx,
            _handler_cmd(
                scenario,
                "maintain-home-object",
                object_id=str(home_object.id),
                action=action,
            ),
        )
        assert result.ok is True
    result = execute_handler(
        CompleteWhimHandler(),
        ctx,
        _handler_cmd(scenario, "complete-whim", whim_id=str(no_reward_whim.id)),
    )
    assert result.ok is True
    assert len(result.events) == 1


def test_lifesim_component_prompt_fragments_external_viewer_returns_nothing():
    """Components hidden from external/private-blind viewers return no fragments."""
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    viewer = spawn_entity(world, [CharacterComponent()])
    external = ComponentPromptContext.for_entity(
        world, character, perspective=PromptPerspective(viewer=viewer)
    )

    # `is_first_person`-gated components return () for an external viewer.
    assert AspirationComponent(name="Cozy Life").prompt_fragments(external) == ()
    assert HouseholdFundsComponent(balance=10).prompt_fragments(external) == ()
    assert HouseholdComponent(household_id="moss").prompt_fragments(external) == ()
    assert WellRestedComponent(expires_at_epoch=99).prompt_fragments(external) == ()
    assert SkillSetComponent(levels={"cooking": 1}).prompt_fragments(external) == ()
    assert CharacterProfileComponent(traits=("tidy",)).prompt_fragments(external) == ()
    pregnancy = PregnancyComponent(started_at_epoch=0, due_at_epoch=5, co_parent_ids=())
    assert pregnancy.prompt_fragments(external) == ()

    # First-person profile with empty fields exercises the skip arcs (305->307 etc.).
    self_ctx = ComponentPromptContext.for_entity(world, character)
    assert CharacterProfileComponent().prompt_fragments(self_ctx) == ()
    assert CharacterProfileComponent(interests=("birding",)).prompt_fragments(self_ctx) == (
        "Your interests: birding.",
    )
    assert CharacterProfileComponent(preferred_routine="tea").prompt_fragments(self_ctx) == (
        "Your preferred routine is tea.",
    )

    # `can_view_private_state`-gated room components return () with no target.
    room = world.get_entity(scenario.room_a)
    room.add_component(HomeComponent(owner_id=str(character.id)))
    room.add_component(RoomClaimComponent(claimed_by_id=str(character.id), claimed_at_epoch=1))
    no_target = ComponentPromptContext.for_entity(world, room)
    assert room.get_component(HomeComponent).prompt_fragments(no_target) == ()
    assert room.get_component(RoomClaimComponent).prompt_fragments(no_target) == ()

    # An external viewer with no matching target fails the private-state gate (lines 204, 220).
    external_room = ComponentPromptContext.for_entity(
        world, room, perspective=PromptPerspective(viewer=viewer)
    )
    assert room.get_component(HomeComponent).prompt_fragments(external_room) == ()
    assert room.get_component(RoomClaimComponent).prompt_fragments(external_room) == ()


def test_home_and_room_claim_fragments_require_room_component_on_entity():
    """Home/claim fragments bail when the target entity is not a room (lines 208, 224)."""
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    self_ctx = ComponentPromptContext.for_entity(world, character)
    # A non-room entity carrying the components, viewed by the owner.
    bare = spawn_entity(world, [])
    home_ctx = ComponentPromptContext.for_entity(
        world, bare, perspective=self_ctx.perspective, target=character
    )
    assert HomeComponent(owner_id=str(character.id)).prompt_fragments(home_ctx) == ()
    claim = RoomClaimComponent(claimed_by_id=str(character.id), claimed_at_epoch=1)
    assert claim.prompt_fragments(home_ctx) == ()


def test_partner_and_relationship_edge_fragments_cover_negative_branches():
    """Edge prompt_fragments early returns (lines 427, 429, 440, 442)."""
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    other = spawn_entity(world, [CharacterComponent()])
    viewer = spawn_entity(world, [CharacterComponent()])

    external = ComponentPromptContext.for_entity(
        world, character, perspective=PromptPerspective(viewer=viewer), target=other
    )
    self_no_target = ComponentPromptContext.for_entity(world, character)

    # Not first person -> ().
    assert PartnerOf(since_epoch=1).prompt_fragments(external) == ()
    assert RelationshipStatus(status="friend", since_epoch=1).prompt_fragments(external) == ()
    # First person but status not "together" or no target -> ().
    assert PartnerOf(since_epoch=1, status="apart").prompt_fragments(self_no_target) == ()
    assert PartnerOf(since_epoch=1).prompt_fragments(self_no_target) == ()
    # First person but no target -> ().
    status_edge = RelationshipStatus(status="friend", since_epoch=1)
    assert status_edge.prompt_fragments(self_no_target) == ()


def test_lifesim_text_and_optional_parsers_cover_all_branches():
    """_parse_text_tuple, _optional_bool, _optional_int branches (lines 733-759)."""
    assert _parse_text_tuple(None) == ()
    assert _parse_text_tuple("a, b, a") == ("a", "b")
    assert _parse_text_tuple(["x", "y"]) == ("x", "y")
    assert _parse_text_tuple(42) == ("42",)

    assert _optional_bool(None) is None
    assert _optional_bool(True) is True
    assert _optional_bool("yes") is True
    assert _optional_bool("off") is False
    assert _optional_bool("maybe") is None

    assert _optional_int(None) is None
    assert _optional_int("7") == 7


def test_participant_ids_skips_missing_payload_keys():
    """_participant_ids skips keys whose payload value is None (branch 726->724)."""
    scenario = build_scenario()
    command = _cmd(scenario, "noop", target_id=None)
    assert _participant_ids(command, "target_id", "missing") == [str(scenario.character)]


def test_partner_edge_and_first_business_skip_non_matching_relations():
    """_partner_edge loop continue (822->821) and _first_business skip arcs (921/923/925)."""
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    # Two partner edges: the first doesn't match the requested target id.
    other = spawn_entity(world, [CharacterComponent()])
    target = spawn_entity(world, [CharacterComponent()])
    character.add_relationship(PartnerOf(since_epoch=1), other.id)
    character.add_relationship(PartnerOf(since_epoch=1), target.id)
    assert _partner_edge(character, target.id) is not None

    # _first_business with a business_id filter skips the non-matching decoy (921).
    wanted = spawn_entity(world, [BusinessOwnerComponent(name="Wanted")])
    decoy = spawn_entity(world, [BusinessOwnerComponent(name="Decoy")])
    character.add_relationship(OwnsBusiness(), decoy.id)
    character.add_relationship(OwnsBusiness(), wanted.id)
    assert _first_business(world, character, wanted.id).id == wanted.id

    # An entity without the component is ignored (925->919) before a valid one is found.
    shopkeeper = spawn_entity(world, [CharacterComponent()])
    not_a_business = spawn_entity(world, [IdentityComponent(name="ledger", kind="item")])
    real = spawn_entity(world, [BusinessOwnerComponent(name="Real")])
    shopkeeper.add_relationship(OwnsBusiness(), not_a_business.id)
    shopkeeper.add_relationship(OwnsBusiness(), real.id)
    assert _first_business(world, shopkeeper).id == real.id

    # A relationship pointing only at a nonexistent id hits the has_entity skip (923)
    # and then falls through to return None.
    loner = spawn_entity(world, [CharacterComponent()])
    world._relationships.setdefault(loner.id, {}).setdefault(OwnsBusiness, {})[
        parse_entity_id("entity_991")
    ] = OwnsBusiness()
    assert _first_business(world, loner) is None


def test_inheritance_record_lookup_skips_non_matching_records():
    """inheritance_record_for_event iterates past a non-matching record (981->979)."""
    scenario = build_scenario()
    world = scenario.actor.world
    spawn_entity(
        world,
        [
            InheritanceRecordComponent(
                decedent_id="a", heir_id="b", source_event_id="other", created_at_epoch=1
            )
        ],
    )
    match = spawn_entity(
        world,
        [
            InheritanceRecordComponent(
                decedent_id="a", heir_id="b", source_event_id="wanted", created_at_epoch=1
            )
        ],
    )
    assert inheritance_record_for_event(world, "wanted").id == match.id
    assert inheritance_record_for_event(world, "absent") is None


def test_select_heir_skips_dead_partner_and_dead_household_member():
    """_select_heir partner/household skip arcs (1051->1049, 1060->1057)."""
    scenario = build_scenario()
    world = scenario.actor.world
    decedent = world.get_entity(scenario.character)
    decedent.add_component(HouseholdComponent(household_id="moss"))

    # A dead partner must be skipped so the household fallback is reached.
    dead_partner = _co_parent(scenario)
    world.get_entity(dead_partner).add_component(DeadComponent(died_at_epoch=1, cause="loss"))
    decedent.add_relationship(PartnerOf(since_epoch=1), dead_partner)
    world.get_entity(dead_partner).add_relationship(PartnerOf(since_epoch=1), decedent.id)

    # A living member of a *different* household fails the household-id check (1060->1057).
    spawn_entity(world, [CharacterComponent(), HouseholdComponent(household_id="other")])
    # The valid household heir.
    housemate = _co_parent(scenario)
    world.get_entity(housemate).add_component(HouseholdComponent(household_id="moss"))

    event = CharacterDiedEvent(
        **event_base(
            80,
            actor_id=str(decedent.id),
            target_ids=(str(decedent.id),),
            cause="winter fever",
        )
    )
    record = project_inheritance_for_death(world, event)
    assert record is not None
    assert record.get_component(InheritanceRecordComponent).heir_id == str(housemate)
    assert record.get_component(InheritanceRecordComponent).relationship == "household"


def test_select_heir_returns_none_when_household_has_no_other_members():
    """_select_heir with a household but no eligible members returns None (1062->1064)."""
    scenario = build_scenario()
    world = scenario.actor.world
    decedent = world.get_entity(scenario.character)
    decedent.add_component(HouseholdComponent(household_id="solitary"))
    # An outsider in a different household must not be chosen.
    spawn_entity(world, [CharacterComponent(), HouseholdComponent(household_id="elsewhere")])

    event = CharacterDiedEvent(
        **event_base(
            90,
            actor_id=str(decedent.id),
            target_ids=(str(decedent.id),),
            cause="winter fever",
        )
    )
    assert project_inheritance_for_death(world, event) is None


def test_inheritance_skips_stale_property_deed_relationship():
    """_transfer_property_deeds skips OwnsProperty edges to missing entities (line 1149)."""
    scenario = build_scenario()
    world = scenario.actor.world
    decedent = world.get_entity(scenario.character)
    heir_id = _child(scenario)
    decedent.add_relationship(ParentOf(), heir_id)

    # A stale OwnsProperty edge pointing at a nonexistent property entity.
    world._relationships.setdefault(decedent.id, {}).setdefault(OwnsProperty, {})[
        parse_entity_id("entity_980")
    ] = OwnsProperty(deed_id="ghost", purchased_at_epoch=1)

    event = CharacterDiedEvent(
        **event_base(
            95,
            actor_id=str(decedent.id),
            target_ids=(str(decedent.id),),
            cause="winter fever",
        )
    )
    record = project_inheritance_for_death(world, event)
    assert record is not None
    # The stale property was skipped, so nothing is recorded as inherited property.
    assert record.get_component(InheritanceRecordComponent).inherited_property_ids == ()


def test_optional_sim_transfers_fall_back_when_modules_unavailable(monkeypatch):
    """Property/colony transfers no-op when the optional sims can't import (1143, 1172)."""
    import sys

    scenario = build_scenario()
    world = scenario.actor.world
    decedent = world.get_entity(scenario.character)
    heir = world.get_entity(scenario.room_b)  # any entity works as the heir handle

    # Force the lazy in-function imports to fail, simulating the sims being absent.
    monkeypatch.setitem(sys.modules, "bunnyland.simpacks.daggersim.mechanics", None)
    monkeypatch.setitem(sys.modules, "bunnyland.simpacks.colonysim.mechanics", None)

    assert _transfer_property_deeds(world, decedent, heir, inherited_at_epoch=1) == ()
    assert _transfer_colony_ownership(decedent, heir, inherited_at_epoch=1) == ()


def test_living_character_false_for_missing_entity():
    """_living_character returns False when the entity is absent (line 1069)."""
    scenario = build_scenario()
    missing = parse_entity_id("entity_9999")
    assert _living_character(scenario.actor.world, missing) is False


def test_maintain_home_object_rejects_invalid_object_id():
    """MaintainHomeObjectHandler rejects when object id is invalid (line 1524)."""
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = execute_handler(
        MaintainHomeObjectHandler(),
        ctx,
        _handler_cmd(scenario, "maintain-home-object", object_id="not-an-id", action="clean"),
    )
    assert result.ok is False
    assert result.reason == "invalid character or object id"


def test_invite_over_defaults_to_current_room_when_room_id_missing():
    """InviteOverHandler falls back to the actor's container room (line 1578)."""
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    guest_id = _co_parent(scenario)
    result = execute_handler(
        InviteOverHandler(),
        ctx,
        _handler_cmd(scenario, "invite-over", guest_id=str(guest_id)),
    )
    assert result.ok is True
    event = result.events[0]
    assert isinstance(event, InvitationSentEvent)
    assert event.room_id_invited == str(scenario.room_a)


def test_end_partnership_when_target_has_no_reverse_edge():
    """EndPartnershipHandler tolerates a one-sided partner edge (branch 2436->2438)."""
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)
    target_id = _co_parent(scenario)
    # Only the actor holds the edge; the target has no reverse PartnerOf.
    actor.add_relationship(PartnerOf(since_epoch=1), target_id)

    result = execute_handler(
        EndPartnershipHandler(),
        ctx,
        _handler_cmd(scenario, "end-partnership", target_id=str(target_id)),
    )
    assert result.ok is True
    assert isinstance(result.events[0], PartnershipEndedEvent)
    assert _partner_edge(actor, target_id) is None


def test_restful_sleep_drops_expired_well_rested_buff():
    """RestfulSleepConsequence removes a buff once its window has elapsed (line 2790)."""
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.add_component(WellRestedComponent(expires_at_epoch=10))

    RestfulSleepConsequence().process(world, epoch=20)

    assert not character.has_component(WellRestedComponent)


def test_lifesim_fragments_skip_stale_and_componentless_whims():
    """lifesim_fragments skips whim relations to missing/non-whim entities (2853, 2856)."""
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    world._relationships.setdefault(character.id, {}).setdefault(HasWhim, {})[
        parse_entity_id("entity_990")
    ] = HasWhim()

    not_a_whim = spawn_entity(world, [IdentityComponent(name="note", kind="item")])
    character.add_relationship(HasWhim(), not_a_whim.id)

    real_whim = spawn_entity(world, [WhimComponent(want="garden")])
    character.add_relationship(HasWhim(), real_whim.id)

    fragments = lifesim_fragments(world, character)
    assert "Current whim: garden." in fragments


def test_lifesim_fragments_inheritance_record_without_component_uses_fallback():
    """A record entity missing its component falls through to the prose line (2922->2927)."""
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    decedent = spawn_entity(world, [IdentityComponent(name="Maple", kind="character")])
    # The record entity exists but carries no InheritanceRecordComponent.
    record = spawn_entity(world, [IdentityComponent(name="stub record", kind="inheritance")])
    character.add_relationship(
        InheritedFrom(
            source_event_id="evt",
            inherited_at_epoch=5,
            relationship="child",
            record_id=str(record.id),
        ),
        decedent.id,
    )

    fragments = lifesim_fragments(world, character)
    assert any("You inherited child legacy from Maple." in line for line in fragments)
