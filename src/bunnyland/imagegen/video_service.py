"""Independent event-video generation service."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from relics import Entity

from bunnyland import telemetry
from bunnyland.foundation.history.mechanics import WorldHistoryRecordComponent
from bunnyland.foundation.media.service import sniff_video_extension

from ..core.ecs import parse_entity_id, replace_component
from ..core.events import EventVisibility, event_base
from ..core.world_actor import WorldActor
from .components import (
    EventVideoComponent,
    MediaSceneSnapshotComponent,
    VideoRequestComponent,
)
from .config import MediaGenConfig
from .events import (
    VideoGenerationCompletedEvent,
    VideoGenerationFailedEvent,
    VideoGenerationStartedEvent,
)
from .generators import VideoGenerator, VideoGeneratorProfile, VideoGeneratorRequest
from .media import SEGMENT_VIDEOS, MediaStore
from .prompt import PromptExampleSource, VideoPromptEnhancer, VideoPromptRequest
from .scene_models import MediaSceneSnapshot
from .scene_projection import MediaSceneProjection
from .spec import GeneratedPrompt, ImagePurpose, MediaKind, PromptStyle
from .subject import subject_for_event

logger = logging.getLogger("bunnyland.videogen")
MAX_GENERATED_VIDEO_BYTES = 256 * 1024 * 1024


@dataclass
class VideoGenJob:
    """The state of one video generation request."""

    job_id: str
    entity_id: str
    purpose: ImagePurpose = ImagePurpose.EVENT
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
class _EphemeralVideoInput:
    subject: str
    scene: MediaSceneSnapshot


class VideoGenService:
    """Queues event-video jobs independently from image generation."""

    def __init__(
        self,
        actor: WorldActor,
        config: MediaGenConfig,
        *,
        generator: VideoGenerator,
        profile_name: str,
        enhancer: VideoPromptEnhancer,
        examples: PromptExampleSource,
        media: MediaStore,
        scene_projection: MediaSceneProjection | None = None,
    ) -> None:
        self._actor = actor
        self._config = config
        self._generator = generator
        self._profile_name = profile_name
        self._enhancer = enhancer
        self._examples = examples
        self._media = media
        self._scene_projection = scene_projection or MediaSceneProjection(actor)
        self._queue: asyncio.Queue[VideoGenJob] = asyncio.Queue()
        self._jobs: dict[str, VideoGenJob] = {}
        self._extras: dict[str, str] = {}
        self._ephemeral_inputs: dict[str, _EphemeralVideoInput] = {}
        self._ephemeral_callbacks: dict[str, Callable[[VideoGenJob], None]] = {}
        self._parent_contexts: dict[str, object] = {}
        self._worker: asyncio.Task[None] | None = None
        self._busy = False

    @property
    def media(self) -> MediaStore:
        return self._media

    @property
    def scene_projection(self) -> MediaSceneProjection:
        return self._scene_projection

    @property
    def idle(self) -> bool:
        return not self._busy and self._queue.empty()

    def job(self, job_id: str) -> VideoGenJob | None:
        return self._jobs.get(job_id)

    async def start(
        self,
        entity_id: str,
        *,
        template_name: str = "",
        requested_by: str = "",
        target_id: str = "",
        extra: str = "",
        force: bool = False,
    ) -> VideoGenJob:
        parsed = parse_entity_id(entity_id)
        profile_name = template_name or self._profile_name
        job = VideoGenJob(
            job_id=uuid4().hex,
            entity_id=entity_id,
            generator=self._generator.name,
            profile_name=profile_name,
            template_name=profile_name,
            requested_by=requested_by,
            target_id=target_id,
        )
        async with self._actor._lock:
            if parsed is None or not self._actor.world.has_entity(parsed):
                job.status = "failed"
                job.error = "unknown entity"
                self._jobs[job.job_id] = job
                return job
            entity = self._actor.world.get_entity(parsed)
            if entity.has_component(EventVideoComponent) and not force:
                job.status = "skipped"
                job.url = entity.get_component(EventVideoComponent).url
                self._jobs[job.job_id] = job
                return job
            if entity.has_component(VideoRequestComponent) and not force:
                job.status = "duplicate"
                self._jobs[job.job_id] = job
                return job
            marker = VideoRequestComponent(
                requested_at_epoch=self._actor.epoch,
                requested_by=requested_by,
            )
            if entity.has_component(VideoRequestComponent):
                replace_component(entity, marker)
            else:
                entity.add_component(marker)
        self._jobs[job.job_id] = job
        self._extras[job.job_id] = extra
        await self._publish_started(job)
        parent_context = telemetry.capture_context()
        if parent_context is not None:
            self._parent_contexts[job.job_id] = parent_context
        self._ensure_worker()
        self._queue.put_nowait(job)
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
        on_complete: Callable[[VideoGenJob], None] | None = None,
    ) -> VideoGenJob:
        """Queue chat-owned video without attaching state to the ECS entity."""

        parsed = parse_entity_id(entity_id)
        profile_name = template_name or self._profile_name
        job = VideoGenJob(
            job_id=uuid4().hex,
            entity_id=entity_id,
            generator=self._generator.name,
            profile_name=profile_name,
            template_name=profile_name,
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
        self._ephemeral_inputs[job.job_id] = _EphemeralVideoInput(
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
        self._queue.put_nowait(job)
        return job

    async def wait_idle(self) -> None:
        await self._queue.join()

    async def aclose(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        self._worker = None

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker(), name="videogen-worker")

    async def _run_worker(self) -> None:
        while True:
            job = await self._queue.get()
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
                            "ephemeral video completion callback failed for %s", job.job_id
                        )
                self._busy = False
                self._queue.task_done()

    async def _process(self, job: VideoGenJob) -> None:
        parsed = parse_entity_id(job.entity_id)
        extra = self._extras.pop(job.job_id, "")
        ephemeral = self._ephemeral_inputs.pop(job.job_id, None)
        parent_context = self._parent_contexts.pop(job.job_id, None)
        attributes = {
            "video.job_id": job.job_id,
            "entity.id": job.entity_id,
            "video.generator": job.generator,
        }
        with telemetry.span("video.generate", attributes, parent_context=parent_context) as span:
            try:
                profile = self._generator.resolve_video_profile(job.profile_name)
                job.profile_name = profile.name
                job.template_name = profile.name
                if ephemeral is not None:
                    subject = ephemeral.subject
                    scene = ephemeral.scene
                    job.snapshot_epoch = scene.captured_at_epoch
                else:
                    async with self._actor._lock:
                        if parsed is None or not self._actor.world.has_entity(parsed):
                            raise VideoGenError("entity no longer exists")
                        entity = self._actor.world.get_entity(parsed)
                        subject = subject_for_event(self._actor.world, entity)
                        scene = (
                            entity.get_component(MediaSceneSnapshotComponent).snapshot
                            if entity.has_component(MediaSceneSnapshotComponent)
                            else None
                        )
                        record = entity.get_component(WorldHistoryRecordComponent)
                        job.source_event_id = record.source_event_id
                        job.snapshot_epoch = (
                            scene.captured_at_epoch if scene is not None else None
                        )
                job.status = "running"
                seed_key = (
                    f"{job.entity_id}:{job.job_id}" if ephemeral is not None else job.entity_id
                )
                seed = int.from_bytes(sha256(seed_key.encode()).digest()[:4], "big")
                prompt = await self._enhance(subject, profile, extra, scene)
                job.enhanced_prompt = prompt.prompt
                job.prompt_style = prompt.style.value
                job.enhancer = prompt.enhancer
                job.prompt_fallback = prompt.fallback
                if not prompt.negative and profile.default_negative:
                    prompt = prompt.model_copy(update={"negative": profile.default_negative})
                telemetry.set_span_attributes(
                    {
                        "media.prompt.style": prompt.style.value,
                        "media.prompt.fallback": prompt.fallback,
                        "media.prompt.chars": len(prompt.prompt),
                    }
                )
                data = await self._generator.generate_video(
                    VideoGeneratorRequest(
                        prompt=prompt.prompt,
                        negative=prompt.negative or profile.default_negative,
                        seed=seed,
                        width=profile.width,
                        height=profile.height,
                        profile_name=profile.name,
                    )
                )
                if len(data) > MAX_GENERATED_VIDEO_BYTES:
                    raise VideoGenError("video generator output exceeds 256 MiB")
                extension = sniff_video_extension(data)
                if extension is None:
                    raise VideoGenError("video generator returned an unsupported container")
                name = self._media.new_name(extension)
                self._media.write(SEGMENT_VIDEOS, name, data)
                url = self._media.url_for(SEGMENT_VIDEOS, name)
                if ephemeral is None:
                    async with self._actor._lock:
                        if parsed is None or not self._actor.world.has_entity(parsed):
                            raise VideoGenError("entity no longer exists")
                        entity = self._actor.world.get_entity(parsed)
                        record = entity.get_component(WorldHistoryRecordComponent)
                        component = EventVideoComponent(
                            url=url,
                            prompt=prompt.prompt,
                            negative_prompt=prompt.negative,
                            prompt_style=prompt.style.value,
                            enhancer=prompt.enhancer,
                            prompt_fallback=prompt.fallback,
                            seed=seed,
                            template=profile.name,
                            generator=self._generator.name,
                            source_event_id=record.source_event_id,
                            generated_at_epoch=self._actor.epoch,
                        )
                        if entity.has_component(EventVideoComponent):
                            replace_component(entity, component)
                        else:
                            entity.add_component(component)
                        self._clear_request(entity)
                job.status = "succeeded"
                job.url = url
                await self._publish_completed(job)
                span.set_attribute("video.output.bytes", len(data))
                telemetry.mark_span_ok(span)
            except Exception as exc:  # noqa: BLE001 - failures become job state and events
                span.record_exception(exc)
                telemetry.mark_span_error(str(exc), span)
                logger.warning("video generation failed for %s: %s", job.entity_id, exc)
                job.status = "failed"
                job.error = str(exc)
                if ephemeral is None and parsed is not None:
                    async with self._actor._lock:
                        if self._actor.world.has_entity(parsed):
                            self._clear_request(self._actor.world.get_entity(parsed))
                await self._publish_failed(job)

    async def _enhance(
        self,
        subject: str,
        profile: VideoGeneratorProfile,
        extra: str,
        scene: MediaSceneSnapshot | None,
    ) -> GeneratedPrompt:
        style = profile.prompt_style
        if self._config.prompt_style:
            style = PromptStyle(self._config.prompt_style)
        examples = self._examples.examples_for(
            style,
            ImagePurpose.EVENT,
            subject,
            media=MediaKind.VIDEO,
            prompt_model=profile.prompt_model,
        )
        return await self._enhancer.enhance_video(
            VideoPromptRequest(
                subject=subject,
                style=style,
                scene=scene,
                extra=extra,
                prompt_model=profile.prompt_model,
            ),
            examples=examples,
        )

    def _event_base(self, job: VideoGenJob) -> dict[str, object]:
        if job.target_id:
            return event_base(
                self._actor.epoch,
                default_visibility=EventVisibility.DIRECTED,
                target_ids=(job.target_id,),
            )
        return event_base(self._actor.epoch)

    async def _publish_started(self, job: VideoGenJob) -> None:
        await self._actor.bus.publish(
            VideoGenerationStartedEvent(
                **self._event_base(job),
                entity_id=job.entity_id,
                generator=job.generator,
                template=job.template_name,
            )
        )

    async def _publish_completed(self, job: VideoGenJob) -> None:
        await self._actor.bus.publish(
            VideoGenerationCompletedEvent(
                **self._event_base(job),
                entity_id=job.entity_id,
                url=job.url,
                generator=job.generator,
                template=job.template_name,
            )
        )

    async def _publish_failed(self, job: VideoGenJob) -> None:
        await self._actor.bus.publish(
            VideoGenerationFailedEvent(
                **self._event_base(job),
                entity_id=job.entity_id,
                generator=job.generator,
                reason=job.error or "unknown error",
            )
        )

    @staticmethod
    def _clear_request(entity: Entity) -> None:
        if entity.has_component(VideoRequestComponent):
            entity.remove_component(VideoRequestComponent)


class VideoGenError(RuntimeError):
    """A video generation job could not be completed."""


__all__ = ["VideoGenError", "VideoGenJob", "VideoGenService"]
