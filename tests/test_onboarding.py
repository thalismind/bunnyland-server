from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

from conftest import build_scenario
from relics import EntityId

from bunnyland.core import ContainmentMode, Contains, replace_component, spawn_entity
from bunnyland.core.components import IdentityComponent, ReadableComponent, RoomComponent
from bunnyland.core.events import (
    CommandExecutedEvent,
    CommandRejectedEvent,
    DomainEvent,
    event_base,
)
from bunnyland.foundation.tutorial.mechanics import DELIVERY_MARK
from bunnyland.server import onboarding
from bunnyland.server.onboarding import OnboardingMilestone, OnboardingTracker


def test_apple_crossing_onboarding_records_only_structured_milestones() -> None:
    scenario = build_scenario()
    room = scenario.actor.world.get_entity(scenario.room_a)
    replace_component(room, RoomComponent(title="Apple Crossing"))
    ledger = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="delivery ledger", kind="ledger"),
            ReadableComponent(text="Waiting for a delivery."),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), ledger.id)
    now = [100.0]
    milestones: list[OnboardingMilestone] = []
    tracker = OnboardingTracker(
        scenario.actor,
        clock=lambda: now[0],
        record=milestones.append,
    )

    tracker.claimed("claim-private", str(scenario.character))
    tracker.claimed("claim-private", str(scenario.character))
    tracker.connected("claim-private")
    tracker.connected("claim-unknown")
    now[0] = 99.0
    tracker.command_submitted("claim-private", "command-look", "look")
    tracker.command_submitted("claim-private", "command-move", "move")
    now[0] = 104.0
    tracker.record_event(
        CommandRejectedEvent(
            **event_base(scenario.actor.epoch),
            command_id="command-unknown",
            command_type="move",
            reason="not retained",
        )
    )
    tracker.record_event(
        CommandRejectedEvent(
            **event_base(scenario.actor.epoch),
            command_id="command-move",
            command_type="move",
            reason="private rejection detail",
        )
    )
    tracker.record_event(
        CommandExecutedEvent(
            **event_base(scenario.actor.epoch),
            command_id="courier-not-yet",
            command_type="write",
        )
    )
    readable = ledger.get_component(ReadableComponent)
    replace_component(ledger, replace(readable, text=DELIVERY_MARK))
    now[0] = 109.0
    tracker.record_event(
        CommandExecutedEvent(
            **event_base(scenario.actor.epoch),
            command_id="courier-write",
            command_type="write",
        )
    )
    tracker.record_event(
        CommandExecutedEvent(
            **event_base(scenario.actor.epoch),
            command_id="courier-already-complete",
            command_type="write",
        )
    )

    assert [(item.name, item.command_type) for item in milestones] == [
        ("connection", ""),
        ("claim", ""),
        ("first_useful_action", "move"),
        ("rejection", "move"),
        ("completion", ""),
    ]
    assert milestones[-1].elapsed_seconds == 9.0
    assert "private" not in repr(milestones)


def test_onboarding_ignores_characters_outside_apple_crossing() -> None:
    scenario = build_scenario()
    milestones: list[OnboardingMilestone] = []
    tracker = OnboardingTracker(scenario.actor, record=milestones.append)

    tracker.claimed("claim-other", str(scenario.character))
    tracker.command_submitted("claim-other", "command-say", "say")

    assert milestones == []


def test_onboarding_skips_missing_and_unreadable_ledgers() -> None:
    missing = build_scenario()
    missing_room = missing.actor.world.get_entity(missing.room_a)
    replace_component(missing_room, RoomComponent(title="Apple Crossing"))
    missing_ledger = spawn_entity(
        missing.actor.world,
        [
            IdentityComponent(name="delivery ledger", kind="ledger"),
            ReadableComponent(text="Waiting."),
        ],
    )
    missing_tracker = OnboardingTracker(missing.actor, record=lambda _milestone: None)
    missing_tracker.claimed("claim-missing", str(missing.character))
    missing.actor.world.remove(missing_ledger)
    missing_tracker.record_event(
        CommandExecutedEvent(
            **event_base(missing.actor.epoch), command_id="one", command_type="write"
        )
    )

    unreadable = build_scenario()
    unreadable_room = unreadable.actor.world.get_entity(unreadable.room_a)
    replace_component(unreadable_room, RoomComponent(title="Apple Crossing"))
    unreadable_ledger = spawn_entity(
        unreadable.actor.world,
        [
            IdentityComponent(name="delivery ledger", kind="ledger"),
            ReadableComponent(text="Waiting."),
        ],
    )
    unreadable_tracker = OnboardingTracker(unreadable.actor, record=lambda _milestone: None)
    unreadable_tracker.claimed("claim-unreadable", str(unreadable.character))
    unreadable_ledger.remove_component(ReadableComponent)
    unreadable_tracker.record_event(
        CommandExecutedEvent(
            **event_base(unreadable.actor.epoch), command_id="two", command_type="write"
        )
    )


def test_onboarding_requires_a_live_character_room_and_delivery_ledger(monkeypatch) -> None:
    scenario = build_scenario()
    tracker = OnboardingTracker(scenario.actor, record=lambda _milestone: None)

    tracker.claimed("invalid", "not-an-entity-id")
    tracker.claimed("missing", "missing_999999")

    detached = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Fern", kind="character")],
    )
    tracker.claimed("detached", str(detached.id))

    monkeypatch.setattr(onboarding, "container_of", lambda _entity: EntityId("missing", 2))
    tracker.claimed("stale-room", str(scenario.character))
    monkeypatch.undo()

    blank_room = spawn_entity(scenario.actor.world, [])
    blank_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), detached.id)
    tracker.claimed("not-room", str(detached.id))

    room = scenario.actor.world.get_entity(scenario.room_a)
    replace_component(room, RoomComponent(title="Apple Crossing"))
    spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="other book", kind="book"),
            ReadableComponent(text="Nothing about deliveries."),
        ],
    )
    tracker.claimed("no-ledger", str(scenario.character))


def test_default_onboarding_recorder_emits_only_structured_attributes(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, str | float]]] = []

    @contextmanager
    def record_span(
        name: str, attributes: dict[str, str | float]
    ) -> Iterator[None]:
        calls.append((name, attributes))
        yield

    monkeypatch.setattr(onboarding.telemetry, "span", record_span)
    onboarding._record_telemetry(OnboardingMilestone(name="claim", elapsed_seconds=1.5))
    onboarding._record_telemetry(
        OnboardingMilestone(
            name="first_useful_action",
            elapsed_seconds=2.5,
            command_type="move",
        )
    )

    assert calls == [
        (
            "tutorial.onboarding",
            {
                "tutorial.name": "apple-crossing",
                "tutorial.milestone": "claim",
                "tutorial.elapsed_seconds": 1.5,
            },
        ),
        (
            "tutorial.onboarding",
            {
                "tutorial.name": "apple-crossing",
                "tutorial.milestone": "first_useful_action",
                "tutorial.elapsed_seconds": 2.5,
                "command.type": "move",
            },
        ),
    ]


def test_onboarding_ignores_unrelated_domain_events() -> None:
    scenario = build_scenario()
    tracker = OnboardingTracker(scenario.actor, record=lambda _milestone: None)

    tracker.record_event(DomainEvent(**event_base(scenario.actor.epoch)))
