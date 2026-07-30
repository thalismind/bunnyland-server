"""Tests for the bounded job registry and the caller-key cap on the rate limiter.

These cover storage lifetime rather than any single endpoint. Before them, the chat,
scene-image and generation job maps were plain dicts with no eviction anywhere, and the
rate limiter's bucket map was keyed in one case by a caller-supplied username, so ordinary
traffic grew all of them for the life of the process.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bunnyland.server.jobs import JobRegistry
from bunnyland.server.rate_limit import FixedWindowRateLimiter
from bunnyland.server.v1_models import JobResource


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _job(job_id: str) -> JobResource:
    created = datetime.now(UTC)
    return JobResource(
        world_id="world-1",
        world_epoch=1,
        id=job_id,
        kind="chat",
        status="queued",
        created_at=created,
        updated_at=created,
    )


def test_registry_expires_jobs_past_their_ttl():
    clock = _Clock()
    registry = JobRegistry(ttl_seconds=60.0, clock=clock)
    registry.put(_job("a"), owner="client-a")

    assert registry.get("a", owner="client-a") is not None

    clock.advance(61.0)
    assert registry.get("a", owner="client-a") is None
    assert len(registry) == 0


def test_registry_caps_jobs_per_owner_and_drops_the_oldest():
    registry = JobRegistry(max_per_owner=3)
    for index in range(10):
        registry.put(_job(f"job-{index}"), owner="client-a")

    assert len(registry) == 3
    assert registry.get("job-0", owner="client-a") is None
    assert registry.get("job-9", owner="client-a") is not None


def test_registry_caps_total_jobs_across_owners():
    registry = JobRegistry(max_per_owner=4, max_total=6)
    for index in range(20):
        registry.put(_job(f"job-{index}"), owner=f"client-{index}")

    assert len(registry) <= 6


def test_registry_per_owner_cap_does_not_evict_another_owner():
    registry = JobRegistry(max_per_owner=1)
    registry.put(_job("mine"), owner="client-a")
    registry.put(_job("theirs"), owner="client-b")
    registry.put(_job("mine-2"), owner="client-a")

    assert registry.get("theirs", owner="client-b") is not None
    assert registry.get("mine", owner="client-a") is None
    assert registry.get("mine-2", owner="client-a") is not None


def test_registry_hides_jobs_from_a_mismatched_owner_or_attribute():
    registry = JobRegistry()
    registry.put(
        _job("a"), owner="client-a", attributes={"character_id": "entity_1", "subject": "alice"}
    )

    # A guessed job id must be indistinguishable from a missing one for anyone else.
    assert registry.get("a", owner="client-b") is None
    assert registry.get("a", owner="client-a", attributes={"character_id": "entity_2"}) is None
    assert registry.get("a", owner="client-a", attributes={"subject": "mallory"}) is None
    assert registry.get("a", owner="client-a", attributes={"subject": "alice"}) is not None


def test_registry_update_keeps_owner_attributes_and_expiry():
    clock = _Clock()
    registry = JobRegistry(ttl_seconds=60.0, clock=clock)
    registry.put(_job("a"), owner="client-a", attributes={"subject": "alice"})

    clock.advance(30.0)
    registry.update(_job("a").model_copy(update={"status": "succeeded"}))

    stored = registry.get("a", owner="client-a", attributes={"subject": "alice"})
    assert stored is not None
    assert stored.status == "succeeded"

    # Updating does not refresh the clock, so the original TTL still governs.
    clock.advance(31.0)
    assert registry.get("a", owner="client-a") is None


def test_registry_update_ignores_an_unknown_job():
    registry = JobRegistry()
    registry.update(_job("never-stored"))

    assert len(registry) == 0
    assert registry.get("never-stored") is None


def test_registry_lists_only_one_owners_unexpired_jobs():
    clock = _Clock()
    registry = JobRegistry(ttl_seconds=60.0, clock=clock)
    registry.put(_job("old"), owner="client-a")
    clock.advance(61.0)
    registry.put(_job("new"), owner="client-a")
    registry.put(_job("other"), owner="client-b")

    assert [job.id for job in registry.list_for("client-a")] == ["new"]
    assert [job.id for job in registry.list_for("client-b")] == ["other"]
    assert registry.list_for("nobody") == []


def test_rate_limiter_bucket_map_stays_bounded_under_unique_keys():
    # The login limiter keys on the submitted username, so a flood of unique usernames used
    # to add an unbounded number of buckets between the once-per-window sweeps.
    clock = _Clock()
    limiter = FixedWindowRateLimiter(5, 60.0, clock=clock, max_tracked_keys=64)

    for index in range(10_000):
        limiter.check(f"user-{index}")

    assert len(limiter._requests) <= 64


def test_rate_limiter_still_limits_a_key_it_is_tracking():
    clock = _Clock()
    limiter = FixedWindowRateLimiter(2, 60.0, clock=clock, max_tracked_keys=8)

    assert limiter.check("alice") == (True, 0)
    assert limiter.check("alice") == (True, 0)
    allowed, retry_after = limiter.check("alice")
    assert allowed is False
    assert retry_after == 60

    # Evicting a bucket only ever grants a fresh allowance; it never denies one.
    for index in range(32):
        limiter.check(f"filler-{index}")
    assert limiter.check("alice") == (True, 0)
