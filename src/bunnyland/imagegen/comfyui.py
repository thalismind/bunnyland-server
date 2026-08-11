"""Shared ComfyUI implementation of the image and video generator contracts."""

from __future__ import annotations

from .client import ComfyClient
from .generators import (
    ImageGeneratorProfile,
    ImageGeneratorRequest,
    VideoGeneratorProfile,
    VideoGeneratorRequest,
)
from .spec import ImagePurpose, MediaKind, WorkflowTemplate, substitute
from .store import WorkflowTemplateStore


class ComfyUIGenerator:
    name = "comfyui"

    def __init__(self, client: ComfyClient, templates: WorkflowTemplateStore) -> None:
        self.client = client
        self.templates = templates

    def _template(
        self, purpose: ImagePurpose, profile_name: str, media: MediaKind
    ) -> WorkflowTemplate:
        template = (
            self.templates.get(profile_name)
            if profile_name
            else self.templates.for_purpose(purpose)
        )
        if template is None:
            kind = media.value
            if profile_name:
                raise ValueError(
                    f"unknown workflow template {profile_name!r}: unknown {kind} profile "
                    f"for generator 'comfyui'"
                )
            raise ValueError(
                f"no workflow template: no {kind} profile for purpose {purpose.value!r} "
                "in generator 'comfyui'"
            )
        if template.purpose is not purpose:
            raise ValueError(
                f"{media.value} profile {template.name!r} does not support purpose "
                f"{purpose.value!r}"
            )
        if template.media is not media:
            raise ValueError(
                f"workflow {template.name!r} produces {template.media.value}, not {media.value}"
            )
        return template

    def resolve_profile(
        self, purpose: ImagePurpose, profile_name: str = ""
    ) -> ImageGeneratorProfile:
        template = self._template(purpose, profile_name, MediaKind.IMAGE)
        return ImageGeneratorProfile(
            name=template.name,
            purpose=template.purpose,
            prompt_style=template.prompt_style,
            prompt_model=template.prompt_model,
            media=template.media,
            default_negative=template.default_negative,
            width=template.width,
            height=template.height,
        )

    async def generate(self, request: ImageGeneratorRequest) -> bytes:
        template = self._template(request.purpose, request.profile_name, MediaKind.IMAGE)
        return await self._generate(
            template,
            prompt=request.prompt,
            negative=request.negative,
            seed=request.seed,
            width=request.width,
            height=request.height,
        )

    def resolve_video_profile(self, profile_name: str = "") -> VideoGeneratorProfile:
        template = self._template(ImagePurpose.EVENT, profile_name, MediaKind.VIDEO)
        return VideoGeneratorProfile(
            name=template.name,
            prompt_style=template.prompt_style,
            prompt_model=template.prompt_model,
            default_negative=template.default_negative,
            width=template.width,
            height=template.height,
        )

    async def generate_video(self, request: VideoGeneratorRequest) -> bytes:
        template = self._template(ImagePurpose.EVENT, request.profile_name, MediaKind.VIDEO)
        return await self._generate(
            template,
            prompt=request.prompt,
            negative=request.negative,
            seed=request.seed,
            width=request.width,
            height=request.height,
        )

    async def _generate(
        self,
        template: WorkflowTemplate,
        *,
        prompt: str,
        negative: str,
        seed: int,
        width: int,
        height: int,
    ) -> bytes:
        graph = substitute(
            template,
            prompt=prompt,
            negative=negative,
            seed=seed,
            width=width,
            height=height,
        )
        return await self.client.generate(graph, output_node_id=template.output_node_id)


__all__ = ["ComfyUIGenerator"]
