"""OpenRouter image-output modality generator."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import ipaddress
import threading
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from types import TracebackType
from typing import Protocol, cast
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
MAX_OPENROUTER_IMAGE_BYTES = 20 * 1024 * 1024
MAX_OPENROUTER_IMAGE_PIXELS = 50_000_000


class _ImageChat(Protocol):
    async def send_async(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        modalities: list[str],
        seed: int,
        image_config: dict[str, str],
    ) -> object: ...


class _OpenRouterClient(Protocol):
    chat: _ImageChat


class _HttpResponse(Protocol):
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...

    def aiter_bytes(self) -> AsyncIterator[bytes]: ...


class _HttpStreamContext(Protocol):
    async def __aenter__(self) -> _HttpResponse: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class _HttpClient(Protocol):
    def stream(self, method: str, url: str) -> _HttpStreamContext: ...


class _HttpContext(Protocol):
    async def __aenter__(self) -> _HttpClient: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool | None: ...


class OpenRouterImageGenerator:
    name = "openrouter"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        server_url: str = "",
        client: _OpenRouterClient | None = None,
        http_factory: Callable[[], _HttpContext] | None = None,
        allowed_result_origins: Iterable[str] = (),
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
            client = cast(_OpenRouterClient, OpenRouter(**kwargs))
        self._client = client
        self._model = model
        self._http_factory = http_factory
        self._allowed_result_origins = frozenset(
            _https_origin(origin) for origin in allowed_result_origins
        )

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
                if len(encoded) > MAX_OPENROUTER_IMAGE_BYTES * 2:
                    raise ValueError("encoded image is too large")
                decoded = base64.b64decode(encoded, validate=True)
                if len(decoded) > MAX_OPENROUTER_IMAGE_BYTES:
                    raise ValueError("decoded image is too large")
                return decoded
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("OpenRouter returned a malformed image data URL") from exc
        if urlparse(value).scheme != "https":
            raise RuntimeError("OpenRouter image result must be a data URL or HTTPS URL")
        origin = _https_origin(value)
        if origin not in self._allowed_result_origins:
            raise RuntimeError(
                "OpenRouter HTTPS image result origin is not explicitly allowed; "
                "use the provider's data URL output or configure an allowed result origin"
            )
        try:
            if self._http_factory is None:
                import httpx

                _reject_nonpublic_literal_host(value)
                context = httpx.AsyncClient(timeout=120.0)
            else:
                _reject_nonpublic_literal_host(value)
                context = self._http_factory()
            async with context as http:
                async with http.stream("GET", value) as response:
                    response.raise_for_status()
                    content_length = _content_length(response.headers)
                    if (
                        content_length is not None
                        and content_length > MAX_OPENROUTER_IMAGE_BYTES
                    ):
                        raise RuntimeError("OpenRouter image result exceeds 20 MiB")
                    output = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(output) + len(chunk) > MAX_OPENROUTER_IMAGE_BYTES:
                            raise RuntimeError("OpenRouter image result exceeds 20 MiB")
                        output.extend(chunk)
                    return bytes(output)
        except Exception as exc:  # noqa: BLE001 - normalize optional HTTP client failures
            raise RuntimeError(f"failed to fetch OpenRouter image result: {exc}") from exc


def _aspect_ratio(width: int, height: int) -> str:
    if width == height:
        return "1:1"
    return "3:2" if width > height else "2:3"


def _field(value: object, name: str) -> object | None:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _reject_nonpublic_literal_host(value: str) -> None:
    host = urlparse(value).hostname
    if not host:
        raise RuntimeError("OpenRouter image result has no hostname")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise RuntimeError("OpenRouter image result resolved to a non-public address")


def _https_origin(value: str) -> str:
    """Return a canonical HTTPS origin for explicit result-host allowlisting.

    OpenRouter's documented image output is a data URL. Deployments that use an HTTPS
    result host must opt into its exact origin; arbitrary provider-returned URLs are never
    fetched, which avoids DNS rebinding between validation and connection.
    """

    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or parsed.hostname is None:
        raise ValueError("allowed OpenRouter result origins must be HTTPS URLs")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("allowed OpenRouter result origins must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("allowed OpenRouter result origin has an invalid port") from exc
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}{f':{port}' if port not in (None, 443) else ''}"


def _content_length(headers: Mapping[str, str]) -> int | None:
    value = headers.get("content-length")
    if value is None:
        value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError:
        return None
    return max(0, length)


def _normalize_png(data: bytes) -> bytes:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_OPENROUTER_IMAGE_PIXELS:
                raise ValueError("image exceeds 50 megapixels")
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
