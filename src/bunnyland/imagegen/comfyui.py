"""ComfyUI implementation of the provider-neutral image generator contract."""

from __future__ import annotations

from .client import ComfyClient
from .generators import ImageGeneratorProfile, ImageGeneratorRequest
from .spec import ImagePurpose, WorkflowTemplate, substitute
from .store import WorkflowTemplateStore


class ComfyUIImageGenerator:
    name = "comfyui"

    def __init__(self, client: ComfyClient, templates: WorkflowTemplateStore) -> None:
        self.client = client
        self.templates = templates

    def _template(self, purpose: ImagePurpose, profile_name: str) -> WorkflowTemplate:
        template = (
            self.templates.get(profile_name)
            if profile_name
            else self.templates.for_purpose(purpose)
        )
        if template is None:
            if profile_name:
                raise ValueError(
                    f"unknown workflow template {profile_name!r}: unknown image profile "
                    f"for generator 'comfyui'"
                )
            raise ValueError(
                f"no workflow template: no image profile for purpose {purpose.value!r} "
                "in generator 'comfyui'"
            )
        if template.purpose is not purpose:
            raise ValueError(
                f"image profile {template.name!r} does not support purpose {purpose.value!r}"
            )
        return template

    def resolve_profile(
        self, purpose: ImagePurpose, profile_name: str = ""
    ) -> ImageGeneratorProfile:
        template = self._template(purpose, profile_name)
        return ImageGeneratorProfile(
            name=template.name,
            purpose=template.purpose,
            prompt_style=template.prompt_style,
            media=template.media,
            default_negative=template.default_negative,
            width=template.width,
            height=template.height,
        )

    async def generate(self, request: ImageGeneratorRequest) -> bytes:
        template = self._template(request.purpose, request.profile_name)
        graph = substitute(
            template,
            prompt=request.prompt,
            negative=request.negative,
            seed=request.seed,
            width=request.width,
            height=request.height,
        )
        return await self.client.generate(graph, output_node_id=template.output_node_id)


__all__ = ["ComfyUIImageGenerator"]
