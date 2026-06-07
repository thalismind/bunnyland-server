"""Tests for life-sim romance, pregnancy, and family mechanics (spec 20.5-20.6)."""

from __future__ import annotations

from conftest import build_scenario

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
    SuspendedComponent,
    WakeHandler,
    build_submitted_command,
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
)
from bunnyland.core.handlers import HandlerContext
from bunnyland.mechanics.lifesim import (
    AdoptChildHandler,
    AgeComponent,
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
    ChargeRentHandler,
    ChooseAspirationHandler,
    ClaimHomeHandler,
    ClaimRoomHandler,
    CompleteMilestoneHandler,
    CustomerComponent,
    EndPartnershipHandler,
    FindJobHandler,
    GossipSpreadEvent,
    GoToWorkHandler,
    HasBill,
    HasRoutine,
    HomeComponent,
    HomeRestComponent,
    HouseholdComponent,
    HouseholdFundsComponent,
    HouseholdJoinedEvent,
    JealousOf,
    JealousyTriggeredEvent,
    JobScheduleComponent,
    JoinHouseholdHandler,
    LifesimAgingPolicyComponent,
    LifeStageComponent,
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
    PromoteBusinessHandler,
    PromotionEarnedEvent,
    QuitJobHandler,
    ReproductiveComponent,
    ReputationComponent,
    ResolveBirthHandler,
    RoomClaimComponent,
    RoutineComponent,
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
    WagePaidEvent,
    WellRestedComponent,
    WellRestedEvent,
    WitnessRomanceHandler,
    WorkShiftCompletedEvent,
    configure_lifesim_aging,
    install_lifesim,
    kinship_label,
    lifesim_fragments,
)
from bunnyland.mechanics.policy import (
    BoundaryTag,
    CharacterBoundaryComponent,
    install_policy,
)
from bunnyland.persistence import WorldMeta, load_world, save_world

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
        result = handler.execute(ctx, command)
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
        result = complete.execute(ctx, command)
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
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    actor.add_component(CareerComponent(title="Archivist", active=False))
    actor.add_component(JobScheduleComponent(next_shift_epoch=scenario.actor.epoch))
    result = GoToWorkHandler().execute(ctx, _handler_cmd(scenario, "go-to-work"))
    assert result.ok is False
    assert result.reason == "career is inactive"

    replace_component(actor, CareerComponent(title="Archivist", active=True))
    replace_component(actor, JobScheduleComponent(next_shift_epoch=scenario.actor.epoch + HOUR))
    result = GoToWorkHandler().execute(ctx, _handler_cmd(scenario, "go-to-work"))
    assert result.ok is False
    assert result.reason == "shift is not scheduled yet"


def test_lifesim_pay_bill_handler_rejects_invalid_bills_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    actor = scenario.actor.world.get_entity(scenario.character)

    result = PayBillHandler().execute(ctx, _handler_cmd(scenario, "pay-bill"))
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
        result = PayBillHandler().execute(ctx, command)
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

    cases = [
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
            ClaimRoomHandler(),
            _handler_cmd(scenario, "claim-room", room_id="entity_999"),
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
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

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
        result = SellItemHandler().execute(ctx, command)
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
        result = SellItemHandler().execute(ctx, command)
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
        result = BuyItemHandler().execute(ctx, command)
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
        result = BuyItemHandler().execute(ctx, command)
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
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    actor.add_relationship(PartnerOf(since_epoch=scenario.actor.epoch), partner_id)
    scenario.actor.world.get_entity(partner_id).add_relationship(
        PartnerOf(since_epoch=scenario.actor.epoch), scenario.character
    )
    result = StartPartnershipHandler().execute(
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
    result = WitnessRomanceHandler().execute(
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

    actor.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    actor.add_component(
        PregnancyComponent(
            started_at_epoch=scenario.actor.epoch,
            due_at_epoch=scenario.actor.epoch + HOUR,
            co_parent_ids=(str(partner_id),),
        )
    )
    result = StartPregnancyHandler().execute(
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
    result = StartPregnancyHandler().execute(
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
    result = StartPregnancyHandler().execute(
        ctx,
        _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "co-parent cannot cause pregnancy"

    replace_component(
        co_parent,
        ReproductiveComponent(can_cause_pregnancy=True, species_group="hare"),
    )
    result = StartPregnancyHandler().execute(
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
    result = StartPregnancyHandler().execute(
        ctx,
        _handler_cmd(scenario, "start-pregnancy", co_parent_id=str(partner_id)),
    )
    assert result.ok is False
    assert result.reason == "fertility prevents pregnancy"

    replace_component(
        co_parent,
        ReproductiveComponent(can_cause_pregnancy=True, species_group="bunny"),
    )
    result = StartPregnancyHandler().execute(
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
    result = AdoptChildHandler().execute(
        ctx,
        _handler_cmd(scenario, "adopt-child", child_id=str(child_id)),
    )
    assert result.ok is False
    assert result.reason == "already parent of child"


def test_lifesim_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cases = [
        (PracticeSkillHandler(), "practice-skill", {"skill": "cooking"}, "invalid character id"),
        (StudySkillHandler(), "study-skill", {"skill": "cooking"}, "invalid character id"),
        (FindJobHandler(), "find-job", {"title": "Archivist"}, "invalid character id"),
        (GoToWorkHandler(), "go-to-work", {}, "invalid character id"),
        (QuitJobHandler(), "quit-job", {}, "invalid character id"),
        (AssessTaxHandler(), "assess-tax", {"amount": 1}, "invalid character id"),
        (PayBillHandler(), "pay-bill", {}, "invalid character id"),
        (OpenBusinessHandler(), "open-business", {"name": "Market"}, "invalid character id"),
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
            {"target_id": str(scenario.character), "claim": "helpful"},
            "invalid character or target id",
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
    ]

    for handler, command_type, payload, reason in cases:
        result = handler.execute(
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

    loaded, _meta = load_world(path)
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
    await scenario.actor.submit(
        _cmd(scenario, "go-to-work", performance_gain=1.0)
    )
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
    assert scenario.actor.world.get_entity(tax_bill_id).get_component(
        BillComponent
    ).paid_at_epoch == scenario.actor.epoch

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
    unpaid_bill = spawn_entity(
        scenario.actor.world,
        [BillComponent(amount=12, reason="garden dues")],
    )
    character.add_relationship(HasBill(), paid_bill.id)
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
    item = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="berry tart", kind="item")]
    )
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
    item = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="moon jam", kind="item")]
    )
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
    item = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="star biscuit", kind="item")]
    )
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

    routine_id = scenario.actor.world.get_entity(scenario.character).get_relationships(
        HasRoutine
    )[0][1]
    routine = scenario.actor.world.get_entity(routine_id).get_component(RoutineComponent)
    assert routine.activity == "water the window herbs"
    assert routine.last_completed_epoch == scenario.actor.epoch
    assert routine.next_due_epoch == scenario.actor.epoch + HOUR
    assert due[0].activity == "water the window herbs"


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
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
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
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
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
    children = [
        target_id for _edge, target_id in character.get_relationships(ParentOf)
    ]
    assert children == []


async def test_relationship_pregnancy_and_birth_create_llm_controlled_child():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    target = _co_parent(scenario)
    resolved: list[BirthResolvedEvent] = []
    scenario.actor.bus.subscribe(BirthResolvedEvent, resolved.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-partnership", target_id=str(target))
    )
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
    controllers = [
        target_id
        for _edge, target_id in child.get_relationships(ControlledBy)
    ]
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


def test_kinship_queries_return_parent_child_partner_and_sibling_labels():
    scenario = build_scenario()
    parent = scenario.actor.world.get_entity(scenario.character)
    child = _child(scenario, name="Clover")
    sibling = _child(scenario, name="Fern")
    partner = _co_parent(scenario)
    parent.add_relationship(ParentOf(), child)
    parent.add_relationship(ParentOf(), sibling)
    parent.add_relationship(PartnerOf(since_epoch=0), partner)

    assert kinship_label(scenario.actor.world, child, scenario.character) == "parent"
    assert kinship_label(scenario.actor.world, scenario.character, child) == "child"
    assert kinship_label(scenario.actor.world, scenario.character, partner) == "partner"
    assert kinship_label(scenario.actor.world, child, sibling) == "sibling"
