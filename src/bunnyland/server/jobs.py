"""Bounded storage for the async job records the HTTP surface hands back to clients."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .v1_models import JobResource

#: A caller polls a job for as long as it is running and then stops. An hour is far longer
#: than any chat reply, scene render, or world generation takes, so expiry never truncates a
#: live job while still bounding how long a finished one is retained.
JOB_TTL_SECONDS = 3600.0
#: Per-owner cap. Chat submissions are already rate limited per subject, but nothing bounded
#: the *total* a caller could accumulate over a long session.
MAX_JOBS_PER_OWNER = 64
#: Absolute backstop across all owners, so a large number of distinct callers cannot grow
#: the registry without limit either.
MAX_JOBS_TOTAL = 4096


@dataclass(frozen=True)
class JobRecord:
    """One stored job plus the identity that is allowed to read it back."""

    job: JobResource
    owner: str
    #: Extra fields a reader must also match (character id, client id, authenticated
    #: subject). Kept alongside the job so the several parallel side maps that used to hold
    #: them cannot drift out of sync with each other.
    attributes: Mapping[str, str | None] = field(default_factory=dict)
    created_at: float = 0.0


class JobRegistry:
    """An owner-scoped job store that expires records instead of keeping them forever.

    The chat, scene-image and generation job maps were plain dicts with no eviction
    anywhere, so every submission leaked a record (and, for chat, three more in parallel
    side maps) for the life of the process. Records here expire on read/write once they
    pass the TTL, each owner is capped, and the registry as a whole is capped.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = JOB_TTL_SECONDS,
        max_per_owner: int = MAX_JOBS_PER_OWNER,
        max_total: int = MAX_JOBS_TOTAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_per_owner = max(1, int(max_per_owner))
        self.max_total = max(1, int(max_total))
        self._clock = clock
        self._records: OrderedDict[str, JobRecord] = OrderedDict()

    def __len__(self) -> int:
        return len(self._records)

    def _expired(self, record: JobRecord, now: float) -> bool:
        return now - record.created_at >= self.ttl_seconds

    def _expire(self, now: float) -> None:
        for job_id in [
            job_id for job_id, record in self._records.items() if self._expired(record, now)
        ]:
            del self._records[job_id]

    def _trim_owner(self, owner: str) -> None:
        owned = [job_id for job_id, record in self._records.items() if record.owner == owner]
        for job_id in owned[: max(0, len(owned) - self.max_per_owner)]:
            del self._records[job_id]

    def _trim_total(self) -> None:
        # Runs after insertion, and the new record sits at the end, so the backstop drops
        # the oldest records rather than the one just stored.
        while len(self._records) > self.max_total:
            self._records.popitem(last=False)

    def put(
        self,
        job: JobResource,
        *,
        owner: str,
        attributes: Mapping[str, str | None] | None = None,
    ) -> None:
        """Store a new job for one owner, evicting that owner's oldest over the cap."""

        now = self._clock()
        self._expire(now)
        self._records[job.id] = JobRecord(
            job=job,
            owner=owner,
            attributes=dict(attributes or {}),
            created_at=now,
        )
        self._records.move_to_end(job.id)
        self._trim_owner(owner)
        self._trim_total()

    def update(self, job: JobResource) -> None:
        """Replace a stored job in place, keeping its owner, attributes and expiry."""

        record = self._records.get(job.id)
        if record is None:
            return
        self._records[job.id] = JobRecord(
            job=job,
            owner=record.owner,
            attributes=record.attributes,
            created_at=record.created_at,
        )

    def get(
        self,
        job_id: str,
        *,
        owner: str | None = None,
        attributes: Mapping[str, str | None] | None = None,
    ) -> JobResource | None:
        """Return a job only when the caller matches its owner and every stated attribute.

        A mismatch is indistinguishable from a missing job on purpose: a reader that guesses
        a job id must not be able to learn that it exists.
        """

        record = self._records.get(job_id)
        if record is None:
            return None
        if self._expired(record, self._clock()):
            del self._records[job_id]
            return None
        if owner is not None and record.owner != owner:
            return None
        for key, value in (attributes or {}).items():
            if record.attributes.get(key) != value:
                return None
        return record.job

    def list_for(self, owner: str) -> list[JobResource]:
        """Return one owner's unexpired jobs, oldest first."""

        self._expire(self._clock())
        return [record.job for record in self._records.values() if record.owner == owner]

    def discard_matching(
        self,
        *,
        owner: str | None = None,
        attributes: Mapping[str, str | None] | None = None,
    ) -> set[str]:
        """Remove and return ids for records matching the supplied ownership fields."""

        removed: set[str] = set()
        for job_id, record in tuple(self._records.items()):
            if owner is not None and record.owner != owner:
                continue
            if any(
                record.attributes.get(key) != value for key, value in (attributes or {}).items()
            ):
                continue
            del self._records[job_id]
            removed.add(job_id)
        return removed


__all__ = [
    "JOB_TTL_SECONDS",
    "MAX_JOBS_PER_OWNER",
    "MAX_JOBS_TOTAL",
    "JobRecord",
    "JobRegistry",
]
