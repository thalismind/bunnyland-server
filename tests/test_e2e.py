"""End-to-end tests (spec 28).

These exercise the whole stack the way a running server does:

1. generate a world and verify the instantiated ECS matches what was requested
   ("fits the proposal") and what the agent is shown ("fits the prompt");
2. play several rounds with a scripted agent and verify each action is processed
   correctly across movement, inventory, needs, and speech.

The scripted agent keeps these deterministic; the same path runs live with an Ollama
agent (see the docs).
"""

from __future__ import annotations

import re

import pytest

from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    ControlledBy,
    DiscordControllerComponent,
    FocusPointsComponent,
    IdentityComponent,
    Lane,
    LLMControllerComponent,
    MemoryProfileComponent,
    PortableComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    WorldActor,
    build_submitted_command,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.components import HealthComponent, RoomComponent, WritableComponent
from bunnyland.core.edges import ExitTo
from bunnyland.core.events import (
    ActorMovedEvent,
    CommandExecutedEvent,
    CommandRejectedEvent,
    ControllerChangedEvent,
    ConversationEndedEvent,
    ConversationLineEvent,
    ConversationStartedEvent,
    ItemTakenEvent,
    NotesSearchedEvent,
    SpeechSaidEvent,
)
from bunnyland.discord import (
    assign_discord_controller,
    release_discord_character_to_llm,
    suspend_discord_character,
)
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import (
    ControllerDispatch,
    GoalDirectedAgent,
    ScriptedAgent,
    ToolCall,
    command_from_tool_call,
)
from bunnyland.mechanics.colonysim import Owns
from bunnyland.mechanics.consumables import DrinkableComponent, FoodComponent
from bunnyland.mechanics.daggersim import (
    EnchantedItemComponent,
    ItemEnchantedEvent,
    SpellCastEvent,
    SpellCreatedEvent,
    SpellTemplateComponent,
)
from bunnyland.mechanics.dinosim import (
    DinosaurComponent,
    EggComponent,
    EggHatchedEvent,
    FossilFragmentComponent,
    SpeciesIdentificationComponent,
)
from bunnyland.mechanics.gardensim import (
    CropComponent,
    CropHarvestedEvent,
    CropReadyEvent,
    HarvestableComponent,
    SeedComponent,
    SoilComponent,
)
from bunnyland.mechanics.lifesim import (
    BillComponent,
    BillPaidEvent,
    BusinessOwnerComponent,
    BusinessPurchaseEvent,
    BusinessSaleEvent,
    CustomerComponent,
    HasBill,
    HomeComponent,
    HouseholdComponent,
    HouseholdFundsComponent,
    LifeStageComponent,
    OwnsBusiness,
    RentChargedEvent,
    RoomClaimComponent,
    lifesim_fragments,
)
from bunnyland.mechanics.needs import DrinkConsumedEvent, FoodEatenEvent
from bunnyland.mechanics.nukesim import (
    DecontaminationComponent,
    JunkComponent,
    RadiationSourceComponent,
    ScavengeSiteComponent,
    nukesim_fragments,
)
from bunnyland.mechanics.persona import GoalComponent
from bunnyland.memory import InMemoryStore, install_memory
from bunnyland.memory.chroma import ChromaMemoryStore
from bunnyland.narration import NarrationProjection, check_grounding
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import (
    apply_plugins,
    bunnyland_plugins,
    collect_persona_fragments,
    collect_prompt_fragments,
)
from bunnyland.prompts.builder import PromptBuilder, render_prompt
from bunnyland.worldgen import GenOptions, StubWorldBuilder, collect_generators, instantiate

KIND_COMPONENT = {
    "food": FoodComponent,
    "water": DrinkableComponent,
    "container": ContainerComponent,
    "paper": WritableComponent,
}


class _SynonymEmbedding:
    """Tiny deterministic embedding for Chroma e2e tests."""

    _GROUPS = (
        {"petals", "blossom", "flower", "lunar", "moon", "sky", "dark"},
        {"kettle", "teapot", "rust", "ferrous"},
        {"crawlspace", "tunnel", "hidden", "below"},
    )

    def __call__(self, input):  # noqa: A002 - Chroma validates this parameter name.
        return [self._embed(text) for text in input]

    def embed_query(self, input):  # noqa: A002 - Chroma validates this parameter name.
        return self(input)

    @staticmethod
    def name() -> str:
        return "bunnyland-test-synonyms"

    @staticmethod
    def build_from_config(config):
        del config
        return _SynonymEmbedding()

    def get_config(self):
        return {}

    def default_space(self) -> str:
        return "l2"

    def supported_spaces(self) -> list[str]:
        return ["l2"]

    def is_legacy(self) -> bool:
        return False

    def _embed(self, text: str) -> list[float]:
        tokens = _tokens(text)
        vector = [float(len(tokens & group)) for group in self._GROUPS]
        return vector if any(vector) else [0.001, 0.001, 0.001]


class _RecordingAgent(ScriptedAgent):
    def __init__(self, calls):
        super().__init__(calls)
        self.prompts: list[str] = []

    def decide(
        self,
        prompt,
        context,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ):
        self.prompts.append(prompt)
        return super().decide(
            prompt,
            context,
            character_id=character_id,
            model=model,
            provider=provider,
            tools=tools,
        )


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower())}


async def _new_world():
    """A fully wired actor (all builtin plugins) with the stub marsh world generated."""
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = StubWorldBuilder().propose("a quiet marsh")
    result = await instantiate(actor, proposal)
    return actor, proposal, result


def _controller_generation(character):
    controller_edges = character.get_relationships(ControlledBy)
    assert controller_edges
    edge, controller_id = controller_edges[0]
    return controller_id, edge.generation


# -- the world fits the proposal --------------------------------------------------------


async def test_generated_world_matches_its_proposal():
    actor, proposal, result = await _new_world()
    world = actor.world

    # Every proposed room exists, titled as requested.
    assert len(result.rooms) == len(proposal.rooms)
    titles = {
        world.get_entity(result.rooms[r.key]).get_component(RoomComponent).title
        for r in proposal.rooms
    }
    assert titles == {r.title for r in proposal.rooms}

    # Every exit connects the requested rooms in the requested direction.
    for exit_ in proposal.exits:
        source = world.get_entity(result.rooms[exit_.from_key])
        by_direction = {edge.direction: target for edge, target in source.get_relationships(ExitTo)}
        assert by_direction.get(exit_.direction) == result.rooms[exit_.to_key]

    # Each object sits in the right room and carries the component its kind implies.
    for obj in proposal.objects:
        entity = world.get_entity(result.objects[obj.key])
        assert container_of(entity) == result.rooms[obj.room_key]
        expected = KIND_COMPONENT.get(obj.kind)
        if expected is not None:
            assert entity.has_component(expected), f"{obj.key} should have {expected.__name__}"

    # Characters are placed and wired to the requested controller kind.
    for character in proposal.characters:
        entity = world.get_entity(result.characters[character.key])
        assert entity.has_component(CharacterComponent)
        assert container_of(entity) == result.rooms[character.room_key]
        if character.controller == "suspended":
            assert entity.has_component(SuspendedComponent)
        else:
            controllers = [
                world.get_entity(target)
                for _edge, target in entity.get_relationships(ControlledBy)
            ]
            assert any(c.has_component(LLMControllerComponent) for c in controllers)


async def test_nukesim_demo_world_instantiates_playable_wasteland_loop():
    actor = WorldActor()
    plugins = bunnyland_plugins()
    apply_plugins(plugins, actor)
    generator = collect_generators(plugins)["nukesim-demo"]

    result = await generator.generate(actor, "nuke-e2e", GenOptions())

    world = actor.world
    assert result.rooms["checkpoint"]
    assert result.rooms["ruin"]
    assert list(world.query().with_all([RadiationSourceComponent]).execute_entities())
    assert list(world.query().with_all([ScavengeSiteComponent]).execute_entities())
    assert list(world.query().with_all([DecontaminationComponent]).execute_entities())
    assert list(world.query().with_all([JunkComponent]).execute_entities())

    scavenger = world.get_entity(result.characters["scavenger"])
    prompt_lines = nukesim_fragments(world, scavenger)
    assert any("Decontamination available" in line for line in prompt_lines)


async def test_prompt_includes_status_fragments_from_plugins():
    from bunnyland.plugins import collect_prompt_fragments

    actor, _proposal, result = await _new_world()
    await actor.tick(12 * 3600.0)  # noon, day 1 -> environment sets the time of day

    builder = PromptBuilder(
        actor.world, fragment_providers=collect_prompt_fragments(bunnyland_plugins())
    )
    prompt = render_prompt(builder.build(result.characters["hazel"]))

    # The plugin fragments surface under a Currently block (time of day at least).
    assert "Currently:" in prompt
    assert "It is" in prompt


async def test_agent_prompt_reflects_the_generated_world():
    actor, _proposal, result = await _new_world()
    prompt = render_prompt(PromptBuilder(actor.world).build(result.characters["hazel"]))

    assert "Mosslit Burrow" in prompt  # the room it is standing in
    assert "north" in prompt  # the exit to the tunnel
    assert "three berries" in prompt  # an item on the floor
    assert "a scrap of paper" in prompt
    assert "Juniper" in prompt  # the other character present
    assert "move north" in prompt  # an offered command


# -- playing the world processes actions ------------------------------------------------


async def test_threaded_conversation_micro_loop_e2e():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]
    room = actor.world.get_entity(container_of(actor.world.get_entity(hazel)))
    clover = spawn_entity(
        actor.world,
        [
            ActionPointsComponent(current=3.0, maximum=3.0),
            FocusPointsComponent(current=3.0, maximum=3.0),
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), clover.id)
    clover_controller = spawn_entity(actor.world)
    clover_generation = actor.assign_controller(clover.id, clover_controller.id)
    started: list[ConversationStartedEvent] = []
    lines: list[ConversationLineEvent] = []
    ended: list[ConversationEndedEvent] = []
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(ConversationStartedEvent, started.append)
    actor.bus.subscribe(ConversationLineEvent, lines.append)
    actor.bus.subscribe(ConversationEndedEvent, ended.append)
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)

    hazel_controller, hazel_generation = _controller_generation(actor.world.get_entity(hazel))
    await actor.submit(
        build_submitted_command(
            character_id=str(hazel),
            controller_id=str(hazel_controller),
            controller_generation=hazel_generation,
            command_type="start-conversation",
            cost=CommandCost(focus=1),
            lane=Lane.FOCUS,
            payload={"target_ids": (str(clover.id),), "topic": "watch rotation"},
        )
    )
    await actor.tick(1.0)
    assert rejected == []
    assert started
    conversation_id = started[0].conversation_id

    await actor.submit(
        build_submitted_command(
            character_id=str(hazel),
            controller_id=str(hazel_controller),
            controller_generation=hazel_generation,
            command_type="conversation-line",
            cost=CommandCost(focus=1),
            lane=Lane.FOCUS,
            payload={
                "conversation_id": conversation_id,
                "text": "Please watch the east tunnel.",
                "intent": "request",
            },
        )
    )
    await actor.tick(1.0)
    await actor.submit(
        build_submitted_command(
            character_id=str(clover.id),
            controller_id=str(clover_controller.id),
            controller_generation=clover_generation,
            command_type="conversation-line",
            cost=CommandCost(focus=1),
            lane=Lane.FOCUS,
            payload={
                "conversation_id": conversation_id,
                "text": "I will keep watch.",
                "intent": "promise",
            },
        )
    )
    await actor.tick(1.0)
    await actor.submit(
        build_submitted_command(
            character_id=str(hazel),
            controller_id=str(hazel_controller),
            controller_generation=hazel_generation,
            command_type="end-conversation",
            cost=CommandCost(focus=1),
            lane=Lane.FOCUS,
            payload={"conversation_id": conversation_id, "reason": "agreed"},
        )
    )
    await actor.tick(1.0)

    assert rejected == []
    assert len(lines) == 2
    assert lines[0].next_participant_id == str(clover.id)
    assert lines[1].next_participant_id == str(hazel)
    assert ended[0].reason == "agreed"


async def test_cross_player_persisted_mark_visible_after_reload_e2e(tmp_path):
    actor, _proposal, result = await _new_world()
    plugins = bunnyland_plugins()
    hazel = result.characters["hazel"]
    room = actor.world.get_entity(container_of(actor.world.get_entity(hazel)))
    clover = spawn_entity(
        actor.world,
        [
            ActionPointsComponent(current=3.0, maximum=3.0),
            FocusPointsComponent(current=3.0, maximum=3.0),
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), clover.id)
    clover_controller = spawn_entity(actor.world)
    actor.assign_controller(clover.id, clover_controller.id)
    sign = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="watch board", kind="sign"),
            WritableComponent(),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), sign.id)
    hazel_controller, hazel_generation = _controller_generation(actor.world.get_entity(hazel))

    await actor.submit(
        build_submitted_command(
            character_id=str(hazel),
            controller_id=str(hazel_controller),
            controller_generation=hazel_generation,
            command_type="write",
            cost=CommandCost(action=1, focus=1),
            lane=Lane.WORLD,
            payload={
                "target_id": str(sign.id),
                "text": "Hazel sealed the east tunnel after moonrise.",
            },
        )
    )
    await actor.tick(1.0)

    path = tmp_path / "cross-player.json"
    save_world(actor, path, meta=WorldMeta(seed="cross-player"))
    loaded, _meta = load_world(path, plugins=plugins)
    prompt = PromptBuilder(
        loaded.world, fragment_providers=collect_prompt_fragments(plugins)
    ).build(clover.id)

    assert any("watch board bears writing by Hazel" in line for line in prompt.conditions)
    assert any("Hazel sealed the east tunnel after moonrise" in line for line in prompt.conditions)


async def test_scripted_playthrough_processes_actions_each_round():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]

    seen: dict[type, list] = {
        event_type: []
        for event_type in (
            FoodEatenEvent,
            DrinkConsumedEvent,
            ItemTakenEvent,
            SpeechSaidEvent,
            ActorMovedEvent,
            CommandRejectedEvent,
        )
    }
    for event_type, sink in seen.items():
        actor.bus.subscribe(event_type, sink.append)

    # One action per round, referring to things by name (dispatch resolves names to ids).
    agent = ScriptedAgent(
        [
            ToolCall("eat", {"item_id": "three berries"}),
            ToolCall("drink", {"source_id": "a stone basin of water"}),
            ToolCall("take", {"item_id": "a scrap of paper"}),
            ToolCall("say", {"text": "Hello, burrow.", "intent": "conversation"}),
            ToolCall("move", {"direction": "north"}),
        ]
    )
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=3600.0)

    # 5 actions need 6 ticks: a tick submits round N, the next tick executes it.
    await loop.run(max_ticks=6)

    # Each action was accepted and produced its domain event; nothing was rejected.
    assert seen[CommandRejectedEvent] == []
    assert len(seen[FoodEatenEvent]) == 1
    assert len(seen[DrinkConsumedEvent]) == 1
    assert len(seen[ItemTakenEvent]) == 1
    assert len(seen[SpeechSaidEvent]) == 1
    assert len(seen[ActorMovedEvent]) == 1

    # Final state reflects the playthrough: paper carried, character moved north.
    world = actor.world
    assert container_of(world.get_entity(result.objects["paper"])) == hazel
    assert container_of(world.get_entity(hazel)) == result.rooms["tunnel"]


async def test_scripted_playthrough_produces_grounded_pov_narration():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]
    projection = NarrationProjection(actor.world).attach(actor)
    agent = ScriptedAgent(
        [
            ToolCall("say", {"text": "Hello, burrow.", "intent": "conversation"}),
            ToolCall("move", {"direction": "north"}),
        ]
    )
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=3600.0)

    await loop.run(max_ticks=3)

    narrations = projection.narrations(str(hazel))
    assert len(narrations) >= 2
    assert any('You said, "Hello, burrow."' in item.text for item in narrations)
    latest = projection.latest(str(hazel))
    assert latest is not None
    assert "You moved north to North Tunnel." in latest.text
    assert latest.scene.location_title == "North Tunnel"
    assert check_grounding(latest.scene, latest.text) == ()


async def test_character_controller_lifecycle_e2e():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    world = actor.world
    room = spawn_entity(world, [RoomComponent(title="Lifecycle Room")])
    character = spawn_entity(
        world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            ActionPointsComponent(current=5.0, maximum=5.0, regen_per_hour=0.0),
            FocusPointsComponent(current=3.0, maximum=3.0, regen_per_hour=0.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), character.id)

    changed: list[ControllerChangedEvent] = []
    executed: list[CommandExecutedEvent] = []
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(ControllerChangedEvent, changed.append)
    actor.bus.subscribe(CommandExecutedEvent, executed.append)
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)

    def current_controller():
        edge, controller_id = character.get_relationships(ControlledBy)[0]
        return edge, controller_id, world.get_entity(controller_id)

    def control_command(command_type: str, controller_id, **payload):
        rels = character.get_relationships(ControlledBy)
        submitter_id = str(rels[0][1]) if rels else str(character.id)
        submitter_generation = rels[0][0].generation if rels else -1
        return build_submitted_command(
            character_id=str(character.id),
            controller_id=submitter_id,
            controller_generation=submitter_generation,
            command_type=command_type,
            cost=CommandCost(),
            lane=Lane.WORLD,
            payload={"controller_id": str(controller_id), **payload},
        )

    async def apply_control(command_type: str, controller_id, **payload) -> None:
        await actor.submit(control_command(command_type, controller_id, **payload))
        await actor.tick(0.0)

    assert not character.get_relationships(ControlledBy)
    assert not character.has_component(SuspendedComponent)

    first_llm = spawn_entity(
        world,
        [
            LLMControllerComponent(
                profile_name="first",
                model="deepseek-v4-flash",
                provider="ollama",
            )
        ],
    )
    await apply_control("take-control", first_llm.id)
    edge, controller_id, controller = current_controller()
    assert controller_id == first_llm.id
    assert edge.generation == 0
    assert controller.has_component(LLMControllerComponent)
    assert changed[-1].controller_kind == "llm"

    claimed = assign_discord_controller(
        actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )
    edge, _controller_id, controller = current_controller()
    assert claimed == "Juniper"
    assert edge.generation == 1
    assert controller.has_component(DiscordControllerComponent)

    suspended = suspend_discord_character(
        actor,
        discord_user_id=123,
        reason="player suspended",
    )
    edge, _controller_id, controller = current_controller()
    assert suspended == "Juniper"
    assert edge.generation == 2
    assert character.get_component(SuspendedComponent).reason == "player suspended"
    assert controller.has_component(SuspendedControllerComponent)

    resumed_discord = spawn_entity(
        world,
        [DiscordControllerComponent(discord_user_id=123, default_channel_id=456)],
    )
    await apply_control("resume", resumed_discord.id)
    edge, controller_id, controller = current_controller()
    assert controller_id == resumed_discord.id
    assert edge.generation == 3
    assert not character.has_component(SuspendedComponent)
    assert controller.has_component(DiscordControllerComponent)
    assert changed[-1].controller_kind == "discord"

    await actor.submit(
        build_submitted_command(
            character_id=str(character.id),
            controller_id=str(controller_id),
            controller_generation=edge.generation,
            command_type="wait",
            cost=CommandCost(),
            lane=Lane.WORLD,
        )
    )
    await actor.tick(0.0)
    assert executed[-1].command_type == "wait"

    released = release_discord_character_to_llm(
        actor,
        discord_user_id=123,
        model="deepseek-v4-flash",
        provider="openrouter",
    )
    edge, _controller_id, controller = current_controller()
    llm = controller.get_component(LLMControllerComponent)
    assert released == "Juniper"
    assert edge.generation == 4
    assert llm.model == "deepseek-v4-flash"
    assert llm.provider == "openrouter"
    assert not character.has_component(SuspendedComponent)

    agent = _RecordingAgent([ToolCall("wait", {})])
    dispatch = ControllerDispatch(actor, PromptBuilder(world), agent)
    decisions = await dispatch.run_once()
    assert len(agent.prompts) == 1
    assert "Juniper" in agent.prompts[0]
    assert len(decisions) == 1
    assert decisions[0].character_id == str(character.id)
    assert decisions[0].tool == "wait"
    await actor.tick(0.0)
    assert executed[-1].command_type == "wait"

    llm_suspender = spawn_entity(
        world, [SuspendedControllerComponent(reason="llm suspended")]
    )
    await apply_control("suspend", llm_suspender.id, reason="llm suspended")
    edge, controller_id, controller = current_controller()
    assert controller_id == llm_suspender.id
    assert edge.generation == 5
    assert character.get_component(SuspendedComponent).reason == "llm suspended"
    assert controller.has_component(SuspendedControllerComponent)
    assert changed[-1].controller_kind == "suspended"

    final_llm = spawn_entity(
        world,
        [
            LLMControllerComponent(
                profile_name="final",
                model="deepseek-v4-flash",
                provider="openrouter",
            )
        ],
    )
    await apply_control("resume", final_llm.id)
    edge, controller_id, controller = current_controller()
    assert controller_id == final_llm.id
    assert edge.generation == 6
    assert not character.has_component(SuspendedComponent)
    assert controller.get_component(LLMControllerComponent).provider == "openrouter"
    assert changed[-1].controller_kind == "llm"
    assert rejected == []


async def test_scripted_agent_buys_grows_harvests_and_sells_garden_crop():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]
    character = actor.world.get_entity(hazel)
    replace_component(
        character,
        ActionPointsComponent(current=9.0, maximum=9.0, regen_per_hour=0.0),
    )
    character.add_component(HouseholdFundsComponent(balance=10))
    merchant = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Marigold", kind="character"),
            CharacterComponent(),
            CustomerComponent(budget=20),
            HouseholdFundsComponent(balance=0),
        ],
    )
    room_id = container_of(character)
    assert room_id is not None
    room = actor.world.get_entity(room_id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), merchant.id)
    merchant_business = spawn_entity(
        actor.world,
        [BusinessOwnerComponent(name="Marigold's Seeds", default_price=3)],
    )
    merchant.add_relationship(OwnsBusiness(), merchant_business.id)
    soil = spawn_entity(
        actor.world,
        [IdentityComponent(name="garden bed", kind="soil"), SoilComponent()],
    )
    seeds = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="radish seeds", kind="seed"),
            PortableComponent(can_pick_up=True),
            SeedComponent(
                crop_type="radish",
                growth_days=1.0,
                yield_item="radish",
                yield_quantity=2,
            ),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), soil.id)
    merchant.add_relationship(Contains(mode=ContainmentMode.INVENTORY), seeds.id)

    bought: list[BusinessPurchaseEvent] = []
    ready: list[CropReadyEvent] = []
    harvested: list[CropHarvestedEvent] = []
    sold: list[BusinessSaleEvent] = []
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(BusinessPurchaseEvent, bought.append)
    actor.bus.subscribe(CropReadyEvent, ready.append)
    actor.bus.subscribe(CropHarvestedEvent, harvested.append)
    actor.bus.subscribe(BusinessSaleEvent, sold.append)
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)

    agent = ScriptedAgent(
        [
            ToolCall("buy_item", {"seller_id": "Marigold", "item_id": str(seeds.id)}),
            ToolCall("claim_ownership", {"target_id": "garden bed"}),
            ToolCall("till", {"soil_id": "garden bed"}),
            ToolCall("plant", {"soil_id": "garden bed", "seed_id": "radish seeds"}),
            ToolCall("water_crop", {"soil_id": "garden bed"}),
            ToolCall("wait", {}),
            ToolCall("open_business", {"name": "Hazel's Farm Stand", "default_price": 8}),
            ToolCall("harvest_crop", {"soil_id": "garden bed"}),
            ToolCall("sell_item", {"item_id": "radish x2", "customer_id": "Marigold"}),
        ]
    )
    builder = PromptBuilder(
        actor.world,
        fragment_providers=collect_prompt_fragments(bunnyland_plugins()),
    )
    loop = GameLoop(
        actor,
        ControllerDispatch(actor, builder, agent),
        tick_seconds=1.0,
        time_scale=24 * 60 * 60,
    )

    await loop.run(max_ticks=10)

    assert rejected == []
    assert len(bought) == 1
    assert len(ready) == 1
    assert len(harvested) == 1
    assert len(sold) == 1
    soil_entity = actor.world.get_entity(soil.id)
    assert character.has_relationship(Owns, soil.id)
    assert not soil_entity.has_component(CropComponent)
    assert not soil_entity.has_component(HarvestableComponent)
    harvested_item = actor.world.get_entity(parse_entity_id(harvested[0].item_id))
    assert harvested_item.get_component(IdentityComponent).name == "radish x2"
    assert container_of(harvested_item) is None
    assert character.get_component(HouseholdFundsComponent).balance == 15
    assert merchant.get_component(HouseholdFundsComponent).balance == 3
    assert merchant.get_component(CustomerComponent).budget == 12


async def test_scripted_agent_identifies_fossil_clones_and_hatches_dino_e2e():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]
    character = actor.world.get_entity(hazel)
    replace_component(
        character,
        ActionPointsComponent(current=8.0, maximum=8.0, regen_per_hour=0.0),
    )
    room_id = container_of(character)
    assert room_id is not None
    room = actor.world.get_entity(room_id)
    fossil = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="amber bone shard", kind="fossil"),
            FossilFragmentComponent(sample_quality=0.8),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), fossil.id)
    hatched: list[EggHatchedEvent] = []
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(EggHatchedEvent, hatched.append)
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)

    agent = ScriptedAgent(
        [
            ToolCall(
                "identify_fossil",
                {"fossil_id": "amber bone shard", "species_name": "velociraptor"},
            ),
            ToolCall("extract_ancient_sample", {"fossil_id": "amber bone shard"}),
            ToolCall("prepare_clone", {"sample_id": "velociraptor ancient sample"}),
            ToolCall("incubate_egg", {"egg_id": "velociraptor egg"}),
            ToolCall("wait", {}),
            ToolCall("hatch_egg", {"egg_id": "velociraptor egg"}),
        ]
    )
    builder = PromptBuilder(
        actor.world,
        fragment_providers=collect_prompt_fragments(bunnyland_plugins()),
    )
    loop = GameLoop(
        actor,
        ControllerDispatch(actor, builder, agent),
        tick_seconds=1.0,
        time_scale=24 * 60 * 60,
    )

    await loop.run(max_ticks=7)

    assert rejected == []
    assert fossil.get_component(SpeciesIdentificationComponent).species_name == "velociraptor"
    assert hatched
    hatchling_id = parse_entity_id(hatched[0].hatchling_id)
    assert hatchling_id is not None
    hatchling = actor.world.get_entity(hatchling_id)
    assert hatchling.get_component(CharacterComponent).species == "velociraptor"
    assert hatchling.get_component(LifeStageComponent).stage == "child"
    assert hatchling.has_component(DinosaurComponent)
    assert container_of(hatchling) == room_id
    assert not list(actor.world.query().with_all([EggComponent]).execute_entities())


async def test_scripted_agent_claims_home_and_pays_rent_bill():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]
    character = actor.world.get_entity(hazel)
    replace_component(
        character,
        ActionPointsComponent(current=8.0, maximum=8.0, regen_per_hour=0.0),
    )
    character.add_component(HouseholdFundsComponent(balance=40))

    rent_charged: list[RentChargedEvent] = []
    bills_paid: list[BillPaidEvent] = []
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(RentChargedEvent, rent_charged.append)
    actor.bus.subscribe(BillPaidEvent, bills_paid.append)
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)

    agent = ScriptedAgent(
        [
            ToolCall("move", {"direction": "north"}),
            ToolCall(
                "join_household",
                {"household_id": "moss-burrow", "name": "Moss Burrow"},
            ),
            ToolCall("claim_home", {"room_id": "North Tunnel"}),
            ToolCall("claim_room", {"room_id": "North Tunnel"}),
        ]
    )
    builder = PromptBuilder(
        actor.world,
        fragment_providers=collect_prompt_fragments(bunnyland_plugins()),
    )
    loop = GameLoop(
        actor,
        ControllerDispatch(actor, builder, agent),
        tick_seconds=1.0,
        time_scale=60 * 60,
    )

    await loop.run(max_ticks=5)

    assert rejected == []
    north_tunnel = actor.world.get_entity(result.rooms["tunnel"])
    home = north_tunnel.get_component(HomeComponent)
    room_claim = north_tunnel.get_component(RoomClaimComponent)
    household = character.get_component(HouseholdComponent)
    assert home.owner_id == str(hazel)
    assert home.household_id == "moss-burrow"
    assert room_claim.claimed_by_id == str(hazel)
    assert household.name == "Moss Burrow"
    fragments = lifesim_fragments(actor.world, character)
    assert "Your household is Moss Burrow." in fragments
    assert "Your home is North Tunnel." in fragments
    assert "Rooms you claim: North Tunnel." in fragments

    landlord = spawn_entity(
        actor.world,
        [
            ActionPointsComponent(current=2.0, maximum=2.0),
            IdentityComponent(name="Marigold", kind="character"),
            CharacterComponent(),
            HouseholdFundsComponent(balance=0),
        ],
    )
    north_tunnel.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), landlord.id)
    landlord_controller = spawn_entity(actor.world)
    landlord_generation = actor.assign_controller(landlord.id, landlord_controller.id)
    await actor.submit(
        command_from_tool_call(
            ToolCall(
                "charge_rent",
                {"tenant_id": str(hazel), "amount": "12", "reason": "burrow rent"},
            ),
            character_id=str(landlord.id),
            controller_id=str(landlord_controller.id),
            controller_generation=landlord_generation,
        )
    )
    await actor.tick(60 * 60)

    assert rejected == []
    assert len(rent_charged) == 1
    bill_id = character.get_relationships(HasBill)[0][1]
    bill = actor.world.get_entity(bill_id).get_component(BillComponent)
    assert bill.reason == "burrow rent"
    assert bill.creditor_id == str(landlord.id)
    assert "Unpaid bills: burrow rent (12)." in lifesim_fragments(actor.world, character)

    hazel_controller, hazel_generation = _controller_generation(character)
    await actor.submit(
        command_from_tool_call(
            ToolCall("pay_bill", {}),
            character_id=str(hazel),
            controller_id=str(hazel_controller),
            controller_generation=hazel_generation,
        )
    )
    await actor.tick(60 * 60)

    assert rejected == []
    assert len(bills_paid) == 1
    assert actor.world.get_entity(bill_id).get_component(BillComponent).paid_at_epoch == actor.epoch
    assert character.get_component(HouseholdFundsComponent).balance == 28
    assert landlord.get_component(HouseholdFundsComponent).balance == 12
    assert not any("Unpaid bills" in line for line in lifesim_fragments(actor.world, character))


async def test_scripted_agent_enchants_created_spell_onto_item_e2e():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]
    character = actor.world.get_entity(hazel)
    for entity in actor.world.query().with_all([CharacterComponent]).execute_entities():
        if entity.id != hazel and not entity.has_component(SuspendedComponent):
            entity.add_component(SuspendedComponent(reason="enchantment e2e focuses on Hazel"))
    replace_component(
        character,
        ActionPointsComponent(current=8.0, maximum=8.0, regen_per_hour=0.0),
    )
    character.add_component(HealthComponent(current=2.0, maximum=10.0))
    room = actor.world.get_entity(container_of(character))
    formula = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="mend sprout formula", kind="spell-template"),
            SpellTemplateComponent(
                spell_name="Mend Sprout",
                effect_type="heal",
                magnitude=4.0,
                cost=1,
            ),
        ],
    )
    charm = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="moss charm", kind="item"),
            PortableComponent(can_pick_up=True),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), formula.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), charm.id)

    created: list[SpellCreatedEvent] = []
    enchanted: list[ItemEnchantedEvent] = []
    cast: list[SpellCastEvent] = []
    rejected: list[CommandRejectedEvent] = []
    actor.bus.subscribe(SpellCreatedEvent, created.append)
    actor.bus.subscribe(ItemEnchantedEvent, enchanted.append)
    actor.bus.subscribe(SpellCastEvent, cast.append)
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)

    agent = ScriptedAgent(
        [
            ToolCall(
                "create_spell",
                {"template_id": "mend sprout formula", "spell_name": "Mend Moss"},
            ),
            ToolCall("enchant_item", {"item_id": "moss charm", "spell_id": "Mend Moss"}),
            ToolCall("cast_spell", {"spell_id": "moss charm"}),
        ]
    )
    builder = PromptBuilder(
        actor.world,
        fragment_providers=collect_prompt_fragments(bunnyland_plugins()),
    )
    loop = GameLoop(
        actor,
        ControllerDispatch(actor, builder, agent),
        tick_seconds=1.0,
        time_scale=60 * 60,
    )

    await loop.run(max_ticks=5)

    assert rejected == []
    assert len(created) == 1
    assert len(enchanted) == 1
    assert len(cast) == 1
    enchantment = charm.get_component(EnchantedItemComponent)
    assert enchantment.spell_name == "Mend Moss"
    assert enchantment.source_spell_id == created[0].spell_id
    assert enchanted[0].item_id == str(charm.id)
    assert character.get_component(HealthComponent).current == 6.0
    assert cast[0].spell_id == str(charm.id)
    assert cast[0].target_health == 6.0


async def test_llm_agent_notes_can_be_found_by_chroma_vector_synonyms():
    chromadb = pytest.importorskip("chromadb")

    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]
    character = actor.world.get_entity(hazel)
    replace_component(
        character,
        MemoryProfileComponent(vector_collection="test-memory-synonyms"),
    )
    replace_component(
        character,
        FocusPointsComponent(current=6.0, maximum=6.0, regen_per_hour=0.0),
    )
    install_memory(
        actor,
        ChromaMemoryStore(
            client=chromadb.EphemeralClient(),
            embedding_function=_SynonymEmbedding(),
        ),
    )
    searched: list[NotesSearchedEvent] = []
    actor.bus.subscribe(NotesSearchedEvent, searched.append)

    flower_note = "Silver petals open when the sky goes dark."
    kettle_note = "The old kettle smells like rust after rain."
    crawlspace_note = "A narrow crawlspace runs below the pantry."
    flower_query = "lunar blossom"
    kettle_query = "ferrous teapot"
    assert _tokens(flower_note).isdisjoint(_tokens(flower_query))
    assert _tokens(kettle_note).isdisjoint(_tokens(kettle_query))

    agent = _RecordingAgent(
        [
            ToolCall("take_note", {"text": flower_note}),
            ToolCall("take_note", {"text": kettle_note}),
            ToolCall("take_note", {"text": crawlspace_note}),
            ToolCall("remember", {"query": flower_query, "mode": "vector", "limit": 1}),
            ToolCall("remember", {"query": kettle_query, "mode": "vector", "limit": 1}),
        ]
    )
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=0.0)

    # One extra tick executes the final command submitted by dispatch.
    await loop.run(max_ticks=6)

    assert len(agent.prompts) >= 5
    assert searched[0].query == flower_query
    assert searched[0].results == (flower_note,)
    assert searched[1].query == kettle_query
    assert searched[1].results == (kettle_note,)


async def test_prompt_recall_surfaces_memory_when_context_becomes_relevant():
    actor, _proposal, result = await _new_world()
    hazel_id = result.characters["hazel"]
    hazel = actor.world.get_entity(hazel_id)
    replace_component(hazel, MemoryProfileComponent(vector_collection="hazel-recall"))
    start_room_id = container_of(hazel)
    assert start_room_id is not None
    direction, destination_id = actor.world.get_entity(start_room_id).get_relationships(ExitTo)[0]
    destination = actor.world.get_entity(destination_id)
    store = install_memory(actor, InMemoryStore())
    relevant = store.add(
        "hazel-recall",
        text="The moon dial marks a cobalt glyph.",
        tags=("moon", "dial", "cobalt"),
        created_at_epoch=1,
    )
    store.add(
        "hazel-recall",
        text="The pantry shelf squeaks in summer.",
        tags=("pantry",),
        created_at_epoch=2,
    )
    builder = PromptBuilder(actor.world, memory_store=store)

    before = builder.build(hazel_id)
    recall_marker = spawn_entity(
        actor.world,
        [IdentityComponent(name="moon dial", kind="item"), PortableComponent()],
    )
    destination.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), recall_marker.id)
    edge, controller_id = hazel.get_relationships(ControlledBy)[0]
    await actor.submit(
        build_submitted_command(
            character_id=str(hazel_id),
            controller_id=str(controller_id),
            controller_generation=edge.generation,
            command_type="move",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"direction": direction.direction},
        )
    )
    await actor.tick(0.0)
    after = builder.build(hazel_id)

    assert all("cobalt glyph" not in item for item in before.recall)
    assert any("cobalt glyph" in item for item in after.recall)
    assert any(f"memory:{relevant.id}" in item for item in after.recall)
    assert all("pantry shelf" not in item for item in after.recall)


async def test_goal_directed_agent_acts_on_goal_through_actor_tick():
    actor, _proposal, result = await _new_world()
    hazel_id = result.characters["hazel"]
    hazel = actor.world.get_entity(hazel_id)
    goal = GoalComponent(active_goals=("find the silver key",))
    if hazel.has_component(GoalComponent):
        replace_component(hazel, goal)
    else:
        hazel.add_component(goal)
    room_id = container_of(hazel)
    assert room_id is not None
    key = spawn_entity(
        actor.world,
        [IdentityComponent(name="silver key", kind="item"), PortableComponent(can_pick_up=True)],
    )
    actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), key.id
    )
    taken: list[ItemTakenEvent] = []
    actor.bus.subscribe(ItemTakenEvent, taken.append)
    builder = PromptBuilder(
        actor.world,
        persona_providers=collect_persona_fragments(bunnyland_plugins()),
    )
    loop = GameLoop(
        actor,
        ControllerDispatch(actor, builder, GoalDirectedAgent()),
        tick_seconds=1.0,
        time_scale=0.0,
    )

    await loop.run(max_ticks=2)

    assert container_of(actor.world.get_entity(key.id)) == hazel_id
    assert taken and taken[0].item_id == str(key.id)


async def test_unreachable_target_is_not_processed_and_coaches_the_agent():
    # An action naming something that isn't there must not execute, and the agent should be
    # given a "did you mean..." hint on its next prompt (parity with the Discord bot).
    actor, _proposal, result = await _new_world()

    rejected: list = []
    moved: list = []
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)
    actor.bus.subscribe(ActorMovedEvent, moved.append)

    # "paper" is not a prefix of any item, but it is near "a scrap of paper".
    agent = ScriptedAgent([ToolCall("take", {"item_id": "paper"})])
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=3600.0)
    # One round: the agent names an item it can't resolve; nothing should be submitted.
    await loop.run(max_ticks=1)

    # The doomed command was never submitted, so there is no handler rejection either.
    assert rejected == []
    assert moved == []
    # A "did you mean..." hint is queued for the agent's next prompt.
    feedback = dispatch._feedback.get(str(result.characters["hazel"]))
    assert feedback and "did you mean" in feedback.lower()
    assert "a scrap of paper" in feedback
