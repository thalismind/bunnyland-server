"""Background image generation service (spec 27).

Generation is slow and must never block a tick or the web server, so requests are queued and
run one at a time by a background worker: the slow ComfyUI call happens off the event loop and
outside the world lock, and the lock is taken only briefly to attach the resulting reference
component and publish a completion event (which the admin world websocket then
broadcasts). Once an entity or record has an image it is reused -- duplicate requests return the
existing reference instead of regenerating, and the backfill picker only selects entities that
are still missing one, so generated images persist with their entity/event.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import itertools
import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from relics import Component, Entity

from bunnyland import telemetry
from bunnyland.foundation.history.mechanics import WorldHistoryRecordComponent
from bunnyland.simpacks.toonsim.mechanics import SpriteImageComponent

from ..core.ecs import parse_entity_id, replace_component
from ..core.events import EventVisibility, event_base
from ..core.world_actor import WorldActor
from .components import (
    EventImageComponent,
    ImageRequestComponent,
    MediaSceneSnapshotComponent,
    PortraitImageComponent,
)
from .config import MediaGenConfig
from .events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
)
from .generators import ImageGenerator, ImageGeneratorProfile, ImageGeneratorRequest
from .media import (
    SEGMENT_ALPHA,
    SEGMENT_ENTITIES,
    SEGMENT_EVENTS,
    SEGMENT_PORTRAITS,
    SEGMENT_SPRITES,
    MediaStore,
)
from .prompt import ImagePromptEnhancer, ImagePromptRequest, PromptExampleSource
from .scene_models import MediaSceneSnapshot
from .scene_projection import MediaSceneProjection
from .spec import GeneratedPrompt, ImagePurpose, MediaKind, PromptStyle
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
MAX_GENERATED_IMAGE_BYTES = 20 * 1024 * 1024
MAX_GENERATED_IMAGE_DIMENSION = 8192
MAX_GENERATED_IMAGE_PIXELS = 50_000_000


@dataclass
class ImageGenJob:
    """The state of one generation request."""

    job_id: str
    entity_id: str
    purpose: ImagePurpose
    generator: str = "comfyui"
    profile_name: str = ""
    template_name: str = ""
    requested_by: str = ""
    target_id: str = ""
    status: str = "queued"
    url: str = ""
    alpha_url: str = ""
    source_event_id: str = ""
    snapshot_epoch: int | None = None
    enhanced_prompt: str = ""
    prompt_style: str = ""
    enhancer: str = ""
    prompt_fallback: bool = False
    error: str | None = None


@dataclass(frozen=True)
class _EphemeralImageInput:
    subject: str
    scene: MediaSceneSnapshot


def _seed_for(entity_id: str) -> int:
    """A stable 32-bit seed for an entity, so a regenerate reproduces the same composition."""
    return int.from_bytes(sha256(entity_id.encode()).digest()[:4], "big")


def _set_component(entity: Entity, component: Component) -> None:
    if entity.has_component(type(component)):
        replace_component(entity, component)
    else:
        entity.add_component(component)


class ImageGenService:
    """Queues and routes image generation jobs to purpose-selected generators."""

    def __init__(
        self,
        actor: WorldActor,
        config: MediaGenConfig,
        *,
        generators: dict[ImagePurpose, ImageGenerator],
        enhancer: ImagePromptEnhancer,
        examples: PromptExampleSource,
        media: MediaStore,
        scene_projection: MediaSceneProjection | None = None,
        alpha: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._actor = actor
        self._config = config
        self._generators = dict(generators)
        self._enhancer = enhancer
        self._examples = examples
        self._media = media
        self._scene_projection = scene_projection or MediaSceneProjection(actor)
        self._alpha = alpha
        self._queue: asyncio.PriorityQueue[tuple[int, int, ImageGenJob]] = (
            asyncio.PriorityQueue()
        )
        self._seq = itertools.count()
        self._jobs: dict[str, ImageGenJob] = {}
        self._extras: dict[str, str] = {}
        self._ephemeral_inputs: dict[str, _EphemeralImageInput] = {}
        self._ephemeral_callbacks: dict[str, Callable[[ImageGenJob], None]] = {}
        self._alpha_jobs: set[str] = set()
        self._parent_contexts: dict[str, object] = {}
        self._worker: asyncio.Task[None] | None = None
        self._busy = False

    # -- public API ------------------------------------------------------------------

    def job(self, job_id: str) -> ImageGenJob | None:
        return self._jobs.get(job_id)

    @property
    def media(self) -> MediaStore:
        return self._media

    @property
    def public_base_url(self) -> str:
        return self._config.public_base_url

    @property
    def scene_projection(self) -> MediaSceneProjection:
        return self._scene_projection

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
        target_id: str = "",
        extra: str = "",
        alpha: bool = False,
        force: bool = False,
    ) -> ImageGenJob:
        """Queue a job (or reuse existing generated media). Returns immediately."""
        parsed = parse_entity_id(entity_id)
        generator = self._generators[purpose]
        job = ImageGenJob(
            job_id=uuid4().hex,
            entity_id=entity_id,
            purpose=purpose,
            generator=generator.name,
            profile_name=template_name,
            template_name=template_name,
            requested_by=requested_by,
            target_id=target_id,
        )
        attributes = {
            "image.job_id": job.job_id,
            "entity.id": entity_id,
            "image.purpose": purpose.value,
            "image.generator": generator.name,
            "image.profile": template_name or "default",
            "image.alpha.requested": alpha,
        }
        with telemetry.span("image.generate.enqueue", attributes) as enqueue_span:
            async with self._actor._lock:
                if parsed is None or not self._actor.world.has_entity(parsed):
                    job.status = "failed"
                    job.error = "unknown entity"
                    self._jobs[job.job_id] = job
                    enqueue_span.set_attribute("image.outcome", "rejected")
                    telemetry.mark_span_ok(enqueue_span)
                    return job
                entity = self._actor.world.get_entity(parsed)
                existing = _existing_image_url(entity, purpose)
                if existing and not force:
                    job.status = "skipped"
                    job.url = existing
                    self._jobs[job.job_id] = job
                    enqueue_span.set_attribute("image.outcome", "skipped")
                    telemetry.mark_span_ok(enqueue_span)
                    return job
                if entity.has_component(ImageRequestComponent) and not force:
                    job.status = "duplicate"
                    self._jobs[job.job_id] = job
                    enqueue_span.set_attribute("image.outcome", "duplicate")
                    telemetry.mark_span_ok(enqueue_span)
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
            parent_context = telemetry.capture_context()
            if parent_context is not None:
                self._parent_contexts[job.job_id] = parent_context
            self._ensure_worker()
            priority = _EVENT_PRIORITY if purpose is ImagePurpose.EVENT else _BACKFILL_PRIORITY
            self._queue.put_nowait((priority, next(self._seq), job))
            enqueue_span.set_attribute("image.outcome", "queued")
            telemetry.mark_span_ok(enqueue_span)
        return job

    async def start_ephemeral(
        self,
        entity_id: str,
        *,
        subject: str,
        scene: MediaSceneSnapshot,
        template_name: str = "",
        requested_by: str = "",
        extra: str = "",
        on_complete: Callable[[ImageGenJob], None] | None = None,
    ) -> ImageGenJob:
        """Queue chat-owned event media without attaching state to the ECS entity.

        ``entity_id`` identifies the directed viewer for lifecycle events. The supplied
        subject and immutable scene snapshot are used only by this job and are discarded
        when processing begins.
        """

        parsed = parse_entity_id(entity_id)
        generator = self._generators[ImagePurpose.EVENT]
        job = ImageGenJob(
            job_id=uuid4().hex,
            entity_id=entity_id,
            purpose=ImagePurpose.EVENT,
            generator=generator.name,
            profile_name=template_name,
            template_name=template_name,
            requested_by=requested_by,
            target_id=entity_id,
        )
        async with self._actor._lock:
            if parsed is None or not self._actor.world.has_entity(parsed):
                job.status = "failed"
                job.error = "unknown entity"
                self._jobs[job.job_id] = job
                return job
        self._jobs[job.job_id] = job
        self._extras[job.job_id] = extra
        self._ephemeral_inputs[job.job_id] = _EphemeralImageInput(
            subject=subject,
            scene=scene,
        )
        if on_complete is not None:
            self._ephemeral_callbacks[job.job_id] = on_complete
        await self._publish_started(job)
        parent_context = telemetry.capture_context()
        if parent_context is not None:
            self._parent_contexts[job.job_id] = parent_context
        self._ensure_worker()
        self._queue.put_nowait((_EVENT_PRIORITY, next(self._seq), job))
        return job

    async def wait_idle(self) -> None:
        """Wait until every queued job has finished (used by tests)."""
        await self._queue.join()

    async def aclose(self) -> None:
        """Cancel the image worker; awaited from the server lifespan."""
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        self._worker = None

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
                callback = self._ephemeral_callbacks.pop(job.job_id, None)
                if callback is not None:
                    try:
                        callback(job)
                    except Exception:  # noqa: BLE001 - reporting must not stop the worker
                        logger.exception(
                            "ephemeral image completion callback failed for %s", job.job_id
                        )
                self._busy = False
                self._queue.task_done()

    async def _process(self, job: ImageGenJob) -> None:
        parent_context = self._parent_contexts.pop(job.job_id, None)
        parsed = parse_entity_id(job.entity_id)
        extra = self._extras.pop(job.job_id, "")
        ephemeral = self._ephemeral_inputs.pop(job.job_id, None)
        alpha_requested = job.job_id in self._alpha_jobs
        self._alpha_jobs.discard(job.job_id)
        attributes = {
            "image.job_id": job.job_id,
            "entity.id": job.entity_id,
            "image.purpose": job.purpose.value,
            "image.generator": job.generator,
            "image.alpha.requested": alpha_requested,
        }
        with telemetry.span(
            "image.generate", attributes, parent_context=parent_context
        ) as generation_span:
            try:
                generator = self._generators[job.purpose]
                profile = generator.resolve_profile(job.purpose, job.profile_name)
                if profile.media is not MediaKind.IMAGE:
                    raise ImageGenError(
                        f"workflow {profile.name!r} produces {profile.media.value}, not image"
                    )
                job.profile_name = profile.name
                job.template_name = profile.name
                if ephemeral is not None:
                    subject = ephemeral.subject
                    scene = ephemeral.scene
                    job.snapshot_epoch = scene.captured_at_epoch
                else:
                    async with self._actor._lock:
                        if parsed is None or not self._actor.world.has_entity(parsed):
                            raise ImageGenError("entity no longer exists")
                        entity = self._actor.world.get_entity(parsed)
                        subject = self._subject_for(entity, job.purpose)
                        scene = (
                            entity.get_component(MediaSceneSnapshotComponent).snapshot
                            if job.purpose is ImagePurpose.EVENT
                            and entity.has_component(MediaSceneSnapshotComponent)
                            else None
                        )
                        if job.purpose is ImagePurpose.EVENT:
                            record = entity.get_component(WorldHistoryRecordComponent)
                            job.source_event_id = record.source_event_id
                            job.snapshot_epoch = (
                                scene.captured_at_epoch if scene is not None else None
                            )
                generation_span.set_attribute("image.profile", profile.name)
                generation_span.set_attribute("image.width", profile.width)
                generation_span.set_attribute("image.height", profile.height)
                job.status = "running"
                seed = _seed_for(
                    f"{job.entity_id}:{job.job_id}" if ephemeral is not None else job.entity_id
                )
                with telemetry.span(
                    "image.prompt.enhance",
                    {
                        "image.job_id": job.job_id,
                        "image.enhancer": self._enhancer.name,
                        "image.purpose": job.purpose.value,
                        "image.profile": profile.name,
                    },
                ) as enhance_span:
                    prompt = await self._enhance(
                        subject, profile, job.purpose, extra, scene
                    )
                    job.enhanced_prompt = prompt.prompt
                    job.prompt_style = prompt.style.value
                    job.enhancer = prompt.enhancer
                    job.prompt_fallback = prompt.fallback
                    if not prompt.negative and profile.default_negative:
                        prompt = prompt.model_copy(
                            update={"negative": profile.default_negative}
                        )
                    enhance_span.set_attribute("media.prompt.style", prompt.style.value)
                    enhance_span.set_attribute("media.prompt.fallback", prompt.fallback)
                    enhance_span.set_attribute("media.prompt.chars", len(prompt.prompt))
                    telemetry.mark_span_ok(enhance_span)
                with telemetry.span(
                    "image.provider.generate",
                    {
                        "image.job_id": job.job_id,
                        "image.generator": generator.name,
                        "image.profile": profile.name,
                        "image.width": profile.width,
                        "image.height": profile.height,
                    },
                ) as provider_span:
                    data = await generator.generate(
                        ImageGeneratorRequest(
                            purpose=job.purpose,
                            prompt=prompt.prompt,
                            negative=prompt.negative or profile.default_negative,
                            seed=seed,
                            width=profile.width,
                            height=profile.height,
                            profile_name=profile.name,
                        )
                    )
                    provider_span.set_attribute("image.output.bytes", len(data))
                    telemetry.mark_span_ok(provider_span)
                do_alpha = self._alpha is not None and (
                    alpha_requested or job.purpose is ImagePurpose.SPRITE
                )
                with telemetry.span(
                    "image.postprocess",
                    {
                        "image.job_id": job.job_id,
                        "image.input.bytes": len(data),
                        "image.alpha.applied": do_alpha,
                    },
                ) as postprocess_span:
                    url, alpha_url = await self._store_media(
                        job.purpose, data, do_alpha
                    )
                    telemetry.mark_span_ok(postprocess_span)
                if ephemeral is None:
                    async with self._actor._lock:
                        if parsed is None or not self._actor.world.has_entity(parsed):
                            raise ImageGenError("entity no longer exists")
                        entity = self._actor.world.get_entity(parsed)
                        self._attach(
                            entity,
                            job.purpose,
                            url,
                            alpha_url,
                            prompt,
                            seed,
                            profile,
                            generator.name,
                        )
                        _clear_request(entity)
                job.status = "succeeded"
                job.url = url
                job.alpha_url = alpha_url
                await self._publish_completed(job, profile.name)
                generation_span.set_attribute("image.output.bytes", len(data))
                generation_span.set_attribute("image.alpha.applied", do_alpha)
                generation_span.set_attribute("image.outcome", "succeeded")
                telemetry.mark_span_ok(generation_span)
            except Exception as exc:  # noqa: BLE001 - any failure becomes a failed job + event
                generation_span.record_exception(exc)
                generation_span.set_attribute("image.outcome", "failed")
                telemetry.mark_span_error(str(exc), generation_span)
                logger.warning("image generation failed for %s: %s", job.entity_id, exc)
                job.status = "failed"
                job.error = str(exc)
                if (
                    ephemeral is None
                    and parsed is not None
                    and self._actor.world.has_entity(parsed)
                ):
                    async with self._actor._lock:
                        _clear_request(self._actor.world.get_entity(parsed))
                await self._publish_failed(job)

    # -- helpers ---------------------------------------------------------------------

    async def _store_media(
        self, purpose: ImagePurpose, data: bytes, do_alpha: bool
    ) -> tuple[str, str]:
        """Write the image (and any alpha variant) to disk and return their URLs.

        The alpha pass is CPU-heavy, so it runs in a worker thread, never on the event loop.
        Sprites become the transparent image directly; other purposes keep both variants.
        """
        await asyncio.to_thread(_validate_image_output, data)
        segment = _SEGMENT_BY_PURPOSE[purpose]
        if not do_alpha:
            telemetry.set_span_attributes(
                {"image.output.bytes": len(data), "image.alpha.output.bytes": 0}
            )
            return self._write(segment, data), ""
        alpha_bytes = await asyncio.to_thread(self._alpha, data)
        await asyncio.to_thread(_validate_image_output, alpha_bytes)
        telemetry.set_span_attributes(
            {
                "image.output.bytes": len(data),
                "image.alpha.output.bytes": len(alpha_bytes),
            }
        )
        if purpose is ImagePurpose.SPRITE:
            return self._write(segment, alpha_bytes), ""
        return self._write(segment, data), self._write(SEGMENT_ALPHA, alpha_bytes)

    def _write(self, segment: str, data: bytes, extension: str = "png") -> str:
        name = self._media.new_name(extension)
        self._media.write(segment, name, data)
        return self._media.public_url_for(
            segment, name, base_url=self._config.public_base_url
        )

    def _subject_for(self, entity: Entity, purpose: ImagePurpose) -> str:
        if purpose is ImagePurpose.EVENT:
            return subject_for_event(self._actor.world, entity)
        return subject_for_entity(entity)

    async def _enhance(
        self,
        subject: str,
        profile: ImageGeneratorProfile,
        purpose: ImagePurpose,
        extra: str,
        scene: MediaSceneSnapshot | None,
    ) -> GeneratedPrompt:
        # An admin-configured prompt style overrides the template's own style.
        style = profile.prompt_style
        if self._config.prompt_style:
            style = PromptStyle(self._config.prompt_style)
        examples = self._examples.examples_for(
            style,
            purpose,
            subject,
            media=MediaKind.IMAGE,
            prompt_model=profile.prompt_model,
        )
        request = ImagePromptRequest(
            subject=subject,
            style=style,
            purpose=purpose,
            scene=scene,
            extra=extra,
            prompt_model=profile.prompt_model,
        )
        return await self._enhancer.enhance_image(request, examples=examples)
    def _attach(
        self,
        entity: Entity,
        purpose: ImagePurpose,
        url: str,
        alpha_url: str,
        prompt: GeneratedPrompt,
        seed: int,
        profile: ImageGeneratorProfile,
        generator: str,
    ) -> None:
        epoch = self._actor.epoch
        if purpose is ImagePurpose.SPRITE:
            _set_component(
                entity,
                SpriteImageComponent(
                    url=url,
                    generator=generator,
                    profile=profile.name,
                    prompt=prompt.prompt,
                    negative_prompt=prompt.negative,
                    prompt_style=prompt.style.value,
                    enhancer=prompt.enhancer,
                    prompt_fallback=prompt.fallback,
                    seed=seed,
                    generated_at_epoch=epoch,
                ),
            )
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
                    negative_prompt=prompt.negative,
                    prompt_style=prompt.style.value,
                    enhancer=prompt.enhancer,
                    prompt_fallback=prompt.fallback,
                    seed=seed,
                    template=profile.name,
                    generator=generator,
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
                negative_prompt=prompt.negative,
                prompt_style=prompt.style.value,
                enhancer=prompt.enhancer,
                prompt_fallback=prompt.fallback,
                seed=seed,
                template=profile.name,
                generator=generator,
                generated_at_epoch=epoch,
            ),
        )

    async def _publish_started(self, job: ImageGenJob) -> None:
        await self._actor.bus.publish(
            ImageGenerationStartedEvent(
                **self._event_base(job),
                entity_id=job.entity_id,
                purpose=job.purpose.value,
                generator=job.generator,
                template=job.template_name,
            )
        )

    async def _publish_completed(self, job: ImageGenJob, template_name: str) -> None:
        await self._actor.bus.publish(
            ImageGenerationCompletedEvent(
                **self._event_base(job),
                entity_id=job.entity_id,
                purpose=job.purpose.value,
                url=job.url,
                alpha_url=job.alpha_url,
                generator=job.generator,
                template=template_name,
            )
        )

    async def _publish_failed(self, job: ImageGenJob) -> None:
        await self._actor.bus.publish(
            ImageGenerationFailedEvent(
                **self._event_base(job),
                entity_id=job.entity_id,
                purpose=job.purpose.value,
                generator=job.generator,
                reason=job.error or "unknown error",
            )
        )

    def _event_base(self, job: ImageGenJob) -> dict[str, object]:
        if job.target_id:
            return event_base(
                self._actor.epoch,
                default_visibility=EventVisibility.DIRECTED,
                target_ids=(job.target_id,),
            )
        return event_base(self._actor.epoch)


class ImageGenError(RuntimeError):
    """A generation job could not be completed."""


def _validate_image_output(data: bytes) -> None:
    """Reject unsafe provider output before persistence or expensive transforms."""

    if len(data) > MAX_GENERATED_IMAGE_BYTES:
        raise ImageGenError("image generator output exceeds 20 MiB")
    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if width > MAX_GENERATED_IMAGE_DIMENSION or height > MAX_GENERATED_IMAGE_DIMENSION:
                    raise ImageGenError("image generator output dimensions exceed 8192 pixels")
                if width * height > MAX_GENERATED_IMAGE_PIXELS:
                    raise ImageGenError("image generator output exceeds 50 megapixels")
                image.verify()
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow exposes several decode exceptions
        raise ImageGenError("image generator returned invalid raster image data") from exc


def _existing_image_url(entity: Entity, purpose: ImagePurpose) -> str:
    if purpose is ImagePurpose.SPRITE:
        if entity.has_component(SpriteImageComponent):
            return entity.get_component(SpriteImageComponent).url
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


__all__ = [
    "ImageGenError",
    "ImageGenJob",
    "ImageGenService",
]
