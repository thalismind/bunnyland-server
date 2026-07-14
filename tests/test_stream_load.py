"""Deterministic 40-client preview stream capacity regression."""

import asyncio

from bunnyland.server.app import next_player_update
from bunnyland.server.subscriptions import EventStream


async def test_forty_clients_fanout_overflow_reconnect_and_gap_recovery(scenario):
    stream = EventStream(scenario.actor, recent_limit=200)
    scenario.actor.event_stream = stream
    regular = [stream.subscribe(max_queue_size=100) for _ in range(34)]
    slow = [stream.subscribe(max_queue_size=2) for _ in range(5)]
    admin = stream.subscribe(max_queue_size=100)
    subscriptions = [*regular, *slow, admin]
    assert len(subscriptions) == 40

    def visible(sequence: int) -> dict:
        return {
            "type": "event",
            "data": {
                "event_type": "CrowdedRoomEvent",
                "event": {
                    "event_id": f"crowd-{sequence}",
                    "world_epoch": scenario.actor.epoch,
                    "visibility": "public",
                    "actor_id": str(scenario.character),
                },
            },
        }

    for sequence in range(10):
        stream.broadcast(visible(sequence))

    # Normal players and the administrative viewer receive the same ordered fan-out.
    for subscription in [*regular, admin]:
        messages = [subscription.queue.get_nowait() for _ in range(10)]
        frames = [subscription.frame(scenario.actor, message) for message in messages]
        assert [frame["event_id"] for frame in frames] == [f"crowd-{i}" for i in range(10)]
        assert [frame["stream_sequence"] for frame in frames] == list(range(1, 11))

    # Slow clients stay bounded and are explicitly told to replace their projection.
    for subscription in slow:
        assert subscription.queue.qsize() == 2
        update = await next_player_update(
            scenario.actor,
            subscription,
            str(scenario.character),
        )
        assert update["type"] == "resync"
        assert update["data"]["reason"] == "queue_overflow"
        assert update["data"]["resume_supported"] is False
        assert subscription.queue.empty()
        frame = subscription.frame(scenario.actor, update)
        assert frame["protocol_version"] == 1
        assert frame["projection_version"] == 1

    # A reconnect gets a new connection-local sequence and can use recent/fallback reads.
    disconnected = regular[0]
    disconnected.close()
    disconnected.close()  # idempotent cleanup
    replacement = stream.subscribe(max_queue_size=100)
    stream.broadcast(visible(10))
    message = await asyncio.wait_for(replacement.queue.get(), timeout=1)
    frame = replacement.frame(scenario.actor, message)
    assert frame["stream_sequence"] == 1
    assert frame["event_id"] == "crowd-10"

    stats = stream.stats()
    assert stats["connections_total"] == 41
    assert stats["connections"] == 40
    assert stats["dropped_frames"] >= 5
    assert stats["resyncs"] == 5
    assert stats["max_queue_depth"] == 10

    stream.record_projection_latency(0.1)
    stream.record_projection_latency(0.3)
    latency = stream.stats()
    assert latency["projection_latency_seconds"] == 0.2
    assert latency["projection_latency_max_seconds"] == 0.3

    for subscription in [*regular[1:], *slow, admin, replacement]:
        subscription.close()
