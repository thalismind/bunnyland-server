"""OpenRouter image-output modality generator."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import threading
from typing import Any
from urllib.parse import urlparse

from .generators import ImageGeneratorProfile, ImageGeneratorRequest
from .spec import ImagePurpose

_PROFILES = {
    ImagePurpose.PORTRAIT: ImageGeneratorProfile(
        name="portrait", purpose=ImagePurpose.PORTRAIT, width=832, height=1216
    ),
    ImagePurpose.ENTITY: ImageGeneratorProfile(
        name="entity", purpose=ImagePurpose.ENTITY, width=1024, height=1024
    ),
    ImagePurpose.SPRITE: ImageGeneratorProfile(
        name="sprite", purpose=ImagePurpose.SPRITE, width=1024, height=1024
    ),
    ImagePurpose.EVENT: ImageGeneratorProfile(
        name="event", purpose=ImagePurpose.EVENT, width=1216, height=832
    ),
}


class OpenRouterImageGenerator:
    name = "openrouter"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        server_url: str = "",
        client: Any | None = None,
        http_factory: Any | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError(
                "openrouter image generation requires BUNNYLAND_IMAGE_OPENROUTER_MODEL"
            )
        if not api_key.strip():
            raise ValueError("openrouter image generation requires OPENROUTER_API_KEY")
        if client is None:
            try:
                from openrouter import OpenRouter
            except ImportError as exc:
                raise RuntimeError(
                    "openrouter image generation requires the 'llm' extra: "
                    "pip install bunnyland[llm]"
                ) from exc
            kwargs = {"api_key": api_key}
            if server_url:
                kwargs["server_url"] = server_url
            client = OpenRouter(**kwargs)
        self._client = client
        self._model = model
        self._http_factory = http_factory

    def resolve_profile(
        self, purpose: ImagePurpose, profile_name: str = ""
    ) -> ImageGeneratorProfile:
        profile = _PROFILES[purpose]
        if profile_name and profile_name != profile.name:
            raise ValueError(
                f"unknown image profile {profile_name!r} for generator 'openrouter'"
            )
        return profile

    async def generate(self, request: ImageGeneratorRequest) -> bytes:
        prompt = request.prompt
        if request.negative.strip():
            prompt += f"\n\nAvoid these elements: {request.negative.strip()}"
        try:
            response = await self._client.chat.send_async(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                modalities=["image"],
                seed=request.seed,
                image_config={
                    "aspect_ratio": _aspect_ratio(request.width, request.height),
                    "output_format": "png",
                },
            )
        except Exception as exc:  # noqa: BLE001 - provider exceptions become domain errors
            raise RuntimeError(f"OpenRouter image generation failed: {exc}") from exc
        choices = _field(response, "choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned an image-less response")
        message = _field(choices[0], "message")
        refusal = _field(message, "refusal")
        if refusal and str(refusal).strip():
            raise RuntimeError(f"OpenRouter refused image generation: {str(refusal).strip()}")
        images = _field(message, "images") or []
        if not images:
            raise RuntimeError("OpenRouter returned an image-less response")
        image_url = _field(images[0], "image_url")
        value = _field(image_url, "url")
        if not isinstance(value, str) or not value:
            raise RuntimeError("OpenRouter returned a malformed image result")
        data = await self._read_result(value)
        _load_pillow()
        return await _normalize_off_loop(data)

    async def _read_result(self, value: str) -> bytes:
        if value.startswith("data:"):
            try:
                header, encoded = value.split(",", 1)
                if ";base64" not in header:
                    raise ValueError("not base64")
                return base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("OpenRouter returned a malformed image data URL") from exc
        if urlparse(value).scheme != "https":
            raise RuntimeError("OpenRouter image result must be a data URL or HTTPS URL")
        try:
            if self._http_factory is None:
                import httpx

                context = httpx.AsyncClient(timeout=120.0)
            else:
                context = self._http_factory()
            async with context as http:
                response = await http.get(value)
                response.raise_for_status()
                return response.content
        except Exception as exc:  # noqa: BLE001 - normalize optional HTTP client failures
            raise RuntimeError(f"failed to fetch OpenRouter image result: {exc}") from exc


def _aspect_ratio(width: int, height: int) -> str:
    if width == height:
        return "1:1"
    return "3:2" if width > height else "2:3"


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _normalize_png(data: bytes) -> bytes:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=False, compress_level=9)
            return output.getvalue()
    except Exception as exc:  # noqa: BLE001 - Pillow exposes several decode exceptions
        raise RuntimeError("OpenRouter returned invalid raster image data") from exc


async def _normalize_off_loop(data: bytes) -> bytes:
    result: list[bytes] = []
    failure: list[BaseException] = []

    def run() -> None:
        try:
            result_bytes = _normalize_png(data)
        except BaseException as exc:  # noqa: BLE001 - propagate worker failures to caller
            failure.append(exc)
        else:
            result.append(result_bytes)

    thread = threading.Thread(target=run, name="imagegen-openrouter-png", daemon=True)
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(0.001)
    if failure:
        raise failure[0]
    return result[0]


def _load_pillow() -> None:
    try:
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "openrouter image generation requires the 'imagegen' extra: "
            "pip install bunnyland[imagegen]"
        ) from exc


__all__ = ["OpenRouterImageGenerator"]
