"""Background image generation service (spec 27).

Generation is slow and must never block a tick or the web server, so requests are queued and
run one at a time by a background worker: the slow ComfyUI call happens off the event loop and
outside the world lock, and the lock is taken only briefly to attach the resulting reference
component and publish a completion event (which the existing ``/world/updates`` websocket then
broadcasts). Once an entity or record has an image it is reused -- duplicate requests return the
existing reference instead of regenerating, and the backfill picker only selects entities that
are still missing one, so generated images persist with their entity/event.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from relics import Entity

from ..core.components import CharacterComponent
from ..core.ecs import parse_entity_id, replace_component
from ..core.events import event_base
from ..core.world_actor import WorldActor
from ..mechanics.history import WorldHistoryRecordComponent
from ..mechanics.toonsim import SpriteImage
from .client import ComfyClient
from .components import (
    EventImageComponent,
    ImageRequestComponent,
    PortraitImageComponent,
)
from .config import ImageGenConfig
from .events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
)
from .media import (
    SEGMENT_ALPHA,
    SEGMENT_ENTITIES,
    SEGMENT_EVENTS,
    SEGMENT_PORTRAITS,
    SEGMENT_SPRITES,
    MediaStore,
)
from .prompt import ImagePromptRequest, PromptEnhancer, PromptExampleSource
from .spec import GeneratedPrompt, ImagePurpose, PromptStyle, WorkflowTemplate, substitute
from .store import WorkflowTemplateStore
from .subject import subject_for_entity, subject_for_event

logger = logging.getLogger("bunnyland.imagegen")

_SEGMENT_BY_PURPOSE: dict[ImagePurpose, str] = {
    ImagePurpose.PORTRAIT: SEGMENT_PORTRAITS,
    ImagePurpose.ENTITY: SEGMENT_ENTITIES,
    ImagePurpose.SPRITE: SEGMENT_SPRITES,
    ImagePurpose.EVENT: SEGMENT_EVENTS,
}

#: Players' event requests outrank bulk portrait/sprite backfill.
_EVENT_PRIORITY = 0
_BACKFILL_PRIORITY = 1


@dataclass
class ImageGenJob:
    """The state of one generation request."""

    job_id: str
    entity_id: str
    purpose: ImagePurpose
    template_name: str = ""
    requested_by: str = ""
    status: str = "queued"
    url: str = ""
    alpha_url: str = ""
    error: str | None = None


def _seed_for(entity_id: str) -> int:
    """A stable 32-bit seed for an entity, so a regenerate reproduces the same composition."""
    return int.from_bytes(sha256(entity_id.encode()).digest()[:4], "big")


def _set_component(entity: Entity, component) -> None:
    if entity.has_component(type(component)):
        replace_component(entity, component)
    else:
        entity.add_component(component)


class ImageGenService:
    """Queues and runs image generation jobs against a ComfyUI server."""

    def __init__(
        self,
        actor: WorldActor,
        config: ImageGenConfig,
        *,
        client: ComfyClient,
        templates: WorkflowTemplateStore,
        enhancer: PromptEnhancer,
        examples: PromptExampleSource,
        media: MediaStore,
        alpha: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._actor = actor
        self._config = config
        self._client = client
        self._templates = templates
        self._enhancer = enhancer
        self._examples = examples
        self._media = media
        self._alpha = alpha
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._jobs: dict[str, ImageGenJob] = {}
        self._extras: dict[str, str] = {}
        self._alpha_jobs: set[str] = set()
        #: Entity ids whose generation failed; the backfill skips them so a broken workflow
        #: parks failures and keeps making progress instead of retrying one forever.
        self._failed: set[str] = set()
        self._worker: asyncio.Task | None = None
        self._backfill: asyncio.Task | None = None
        self._busy = False

    # -- public API ------------------------------------------------------------------

    def job(self, job_id: str) -> ImageGenJob | None:
        return self._jobs.get(job_id)

    @property
    def media(self) -> MediaStore:
        return self._media

    @property
    def idle(self) -> bool:
        return not self._busy and self._queue.empty()

    async def start(
        self,
        entity_id: str,
        purpose: ImagePurpose,
        *,
        template_name: str = "",
        requested_by: str = "",
        extra: str = "",
        alpha: bool = False,
        force: bool = False,
    ) -> ImageGenJob:
        """Queue a job (or reuse an existing image). Returns immediately."""
        parsed = parse_entity_id(entity_id)
        job = ImageGenJob(
            job_id=uuid4().hex,
            entity_id=entity_id,
            purpose=purpose,
            template_name=template_name,
            requested_by=requested_by,
        )
        async with self._actor._lock:
            if parsed is None or not self._actor.world.has_entity(parsed):
                job.status = "failed"
                job.error = "unknown entity"
                self._jobs[job.job_id] = job
                return job
            entity = self._actor.world.get_entity(parsed)
            existing = _existing_image_url(entity, purpose)
            if existing and not force:
                job.status = "skipped"
                job.url = existing
                self._jobs[job.job_id] = job
                return job
            if entity.has_component(ImageRequestComponent) and not force:
                job.status = "duplicate"
                self._jobs[job.job_id] = job
                return job
            _set_component(
                entity,
                ImageRequestComponent(
                    purpose=purpose.value,
                    requested_at_epoch=self._actor.epoch,
                    requested_by=requested_by,
                ),
            )
        self._jobs[job.job_id] = job
        self._extras[job.job_id] = extra
        if alpha:
            self._alpha_jobs.add(job.job_id)
        await self._publish_started(job)
        self._ensure_worker()
        priority = _EVENT_PRIORITY if purpose is ImagePurpose.EVENT else _BACKFILL_PRIORITY
        self._queue.put_nowait((priority, next(self._seq), job))
        return job

    async def enqueue_one_missing(self) -> ImageGenJob | None:
        """Backfill picker: queue one portrait/sprite that is still missing, when idle.

        Enforces the one-at-a-time cadence -- it does nothing while a job is queued or running,
        so the caller can simply invoke it every tick.
        """
        if not self.idle:
            return None
        async with self._actor._lock:
            target = _first_missing_portrait(
                self._actor, self._failed
            ) or _first_missing_sprite(self._actor, self._failed)
        if target is None:
            return None
        entity_id, purpose = target
        return await self.start(entity_id, purpose)

    async def wait_idle(self) -> None:
        """Wait until every queued job has finished (used by tests)."""
        await self._queue.join()

    def start_backfill(self, interval_seconds: float | None = None) -> None:
        """Start the throttled portrait/sprite backfill loop (idempotent).

        Runs independently of the world tick (so it never contends with the tick lock),
        enqueuing at most one missing image per interval.
        """
        if self._backfill is not None and not self._backfill.done():
            return
        interval = (
            self._config.backfill_interval_seconds if interval_seconds is None else interval_seconds
        )
        self._backfill = asyncio.create_task(
            self._run_backfill(interval), name="imagegen-backfill"
        )

    async def _run_backfill(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.enqueue_one_missing()

    async def aclose(self) -> None:
        """Cancel the worker and backfill loop; awaited from the server lifespan."""
        for task in (self._worker, self._backfill):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._worker = None
        self._backfill = None

    # -- worker ----------------------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker(), name="imagegen-worker")

    async def _run_worker(self) -> None:
        while True:
            _, _, job = await self._queue.get()
            self._busy = True
            try:
                await self._process(job)
            finally:
                self._busy = False
                self._queue.task_done()

    async def _process(self, job: ImageGenJob) -> None:
        parsed = parse_entity_id(job.entity_id)
        extra = self._extras.pop(job.job_id, "")
        alpha_requested = job.job_id in self._alpha_jobs
        self._alpha_jobs.discard(job.job_id)
        try:
            async with self._actor._lock:
                if parsed is None or not self._actor.world.has_entity(parsed):
                    raise ImageGenError("entity no longer exists")
                entity = self._actor.world.get_entity(parsed)
                template = self._template_for(job)
                subject = self._subject_for(entity, job.purpose)
            job.status = "running"
            seed = _seed_for(job.entity_id)
            prompt = await self._enhance(subject, template, job.purpose, extra)
            graph = substitute(
                template, prompt=prompt.prompt, seed=seed, negative=prompt.negative
            )
            data = await self._client.generate(graph, output_node_id=template.output_node_id)
            do_alpha = self._alpha is not None and (
                alpha_requested or job.purpose is ImagePurpose.SPRITE
            )
            url, alpha_url = await self._store_image(job.purpose, data, do_alpha)
            async with self._actor._lock:
                entity = self._actor.world.get_entity(parsed)
                self._attach(entity, job.purpose, url, alpha_url, prompt, seed, template)
                _clear_request(entity)
            job.status = "succeeded"
            job.url = url
            job.alpha_url = alpha_url
            self._failed.discard(job.entity_id)
            await self._publish_completed(job, template.name)
        except Exception as exc:  # noqa: BLE001 - any failure becomes a failed job + event
            logger.warning("image generation failed for %s: %s", job.entity_id, exc)
            job.status = "failed"
            job.error = str(exc)
            self._failed.add(job.entity_id)
            if parsed is not None and self._actor.world.has_entity(parsed):
                async with self._actor._lock:
                    _clear_request(self._actor.world.get_entity(parsed))
            await self._publish_failed(job)

    # -- helpers ---------------------------------------------------------------------

    async def _store_image(
        self, purpose: ImagePurpose, data: bytes, do_alpha: bool
    ) -> tuple[str, str]:
        """Write the image (and any alpha variant) to disk and return their URLs.

        The alpha pass is CPU-heavy, so it runs in a worker thread, never on the event loop.
        Sprites become the transparent image directly; other purposes keep both variants.
        """
        segment = _SEGMENT_BY_PURPOSE[purpose]
        if not do_alpha:
            return self._write(segment, data), ""
        alpha_bytes = await asyncio.to_thread(self._alpha, data)
        if purpose is ImagePurpose.SPRITE:
            return self._write(segment, alpha_bytes), ""
        return self._write(segment, data), self._write(SEGMENT_ALPHA, alpha_bytes)

    def _write(self, segment: str, data: bytes) -> str:
        name = self._media.new_name("png")
        self._media.write(segment, name, data)
        return self._media.url_for(segment, name)

    def _template_for(self, job: ImageGenJob) -> WorkflowTemplate:
        if job.template_name:
            template = self._templates.get(job.template_name)
            if template is None:
                raise ImageGenError(f"unknown workflow template {job.template_name!r}")
            return template
        template = self._templates.for_purpose(job.purpose)
        if template is None:
            raise ImageGenError(f"no workflow template for purpose {job.purpose.value!r}")
        return template

    def _subject_for(self, entity: Entity, purpose: ImagePurpose) -> str:
        if purpose is ImagePurpose.EVENT:
            return subject_for_event(self._actor.world, entity)
        return subject_for_entity(entity)

    async def _enhance(
        self, subject: str, template: WorkflowTemplate, purpose: ImagePurpose, extra: str
    ) -> GeneratedPrompt:
        # An admin-configured prompt style overrides the template's own style.
        style = template.prompt_style
        if self._config.prompt_style:
            style = PromptStyle(self._config.prompt_style)
        examples = self._examples.examples_for(style, purpose, subject)
        request = ImagePromptRequest(
            subject=subject,
            style=style,
            purpose=purpose,
            media=template.media,
            extra=extra,
        )
        return await self._enhancer.enhance(request, examples=examples)

    def _attach(
        self,
        entity: Entity,
        purpose: ImagePurpose,
        url: str,
        alpha_url: str,
        prompt: GeneratedPrompt,
        seed: int,
        template: WorkflowTemplate,
    ) -> None:
        epoch = self._actor.epoch
        if purpose is ImagePurpose.SPRITE:
            _set_component(entity, SpriteImage(url=url))
            return
        if purpose is ImagePurpose.EVENT:
            # EVENT jobs always target a history-record entity (subject assembly requires it).
            record = entity.get_component(WorldHistoryRecordComponent)
            _set_component(
                entity,
                EventImageComponent(
                    url=url,
                    alpha_url=alpha_url,
                    prompt=prompt.prompt,
                    seed=seed,
                    template=template.name,
                    source_event_id=record.source_event_id,
                    generated_at_epoch=epoch,
                ),
            )
            return
        _set_component(
            entity,
            PortraitImageComponent(
                url=url,
                alpha_url=alpha_url,
                prompt=prompt.prompt,
                seed=seed,
                template=template.name,
                generated_at_epoch=epoch,
            ),
        )

    async def _publish_started(self, job: ImageGenJob) -> None:
        await self._actor.bus.publish(
            ImageGenerationStartedEvent(
                **event_base(self._actor.epoch),
                entity_id=job.entity_id,
                purpose=job.purpose.value,
                template=job.template_name,
            )
        )

    async def _publish_completed(self, job: ImageGenJob, template_name: str) -> None:
        await self._actor.bus.publish(
            ImageGenerationCompletedEvent(
                **event_base(self._actor.epoch),
                entity_id=job.entity_id,
                purpose=job.purpose.value,
                url=job.url,
                alpha_url=job.alpha_url,
                template=template_name,
            )
        )

    async def _publish_failed(self, job: ImageGenJob) -> None:
        await self._actor.bus.publish(
            ImageGenerationFailedEvent(
                **event_base(self._actor.epoch),
                entity_id=job.entity_id,
                purpose=job.purpose.value,
                reason=job.error or "unknown error",
            )
        )


class ImageGenError(RuntimeError):
    """A generation job could not be completed."""


def _existing_image_url(entity: Entity, purpose: ImagePurpose) -> str:
    if purpose is ImagePurpose.SPRITE:
        if entity.has_component(SpriteImage):
            return entity.get_component(SpriteImage).url
        return ""
    if purpose is ImagePurpose.EVENT:
        if entity.has_component(EventImageComponent):
            return entity.get_component(EventImageComponent).url
        return ""
    if entity.has_component(PortraitImageComponent):
        return entity.get_component(PortraitImageComponent).url
    return ""


def _clear_request(entity: Entity) -> None:
    if entity.has_component(ImageRequestComponent):
        entity.remove_component(ImageRequestComponent)


def _first_missing_portrait(
    actor: WorldActor, skip: set[str]
) -> tuple[str, ImagePurpose] | None:
    for entity in (
        actor.world.query()
        .with_all([CharacterComponent])
        .with_none([PortraitImageComponent, ImageRequestComponent])
        .execute_entities()
    ):
        if str(entity.id) not in skip:
            return (str(entity.id), ImagePurpose.PORTRAIT)
    return None


def _first_missing_sprite(
    actor: WorldActor, skip: set[str]
) -> tuple[str, ImagePurpose] | None:
    for entity in (
        actor.world.query()
        .with_all([CharacterComponent, SpriteImage])
        .with_none([ImageRequestComponent])
        .execute_entities()
    ):
        if str(entity.id) not in skip and not entity.get_component(SpriteImage).url:
            return (str(entity.id), ImagePurpose.SPRITE)
    return None


__all__ = [
    "ImageGenError",
    "ImageGenJob",
    "ImageGenService",
]
