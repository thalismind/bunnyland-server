"""Deterministic offline image generator."""

from __future__ import annotations

import asyncio
import io
import threading
from hashlib import sha256

from .generators import ImageGeneratorProfile, ImageGeneratorRequest
from .spec import ImagePurpose

_PROFILES = {
    ImagePurpose.PORTRAIT: ImageGeneratorProfile(
        name="portrait", purpose=ImagePurpose.PORTRAIT, width=512, height=768
    ),
    ImagePurpose.ENTITY: ImageGeneratorProfile(
        name="entity", purpose=ImagePurpose.ENTITY, width=512, height=512
    ),
    ImagePurpose.SPRITE: ImageGeneratorProfile(
        name="sprite", purpose=ImagePurpose.SPRITE, width=512, height=512
    ),
    ImagePurpose.EVENT: ImageGeneratorProfile(
        name="event", purpose=ImagePurpose.EVENT, width=768, height=512
    ),
}


class InMemoryImageGenerator:
    """Create mirrored identicon artwork without network access."""

    name = "in-memory"

    def resolve_profile(
        self, purpose: ImagePurpose, profile_name: str = ""
    ) -> ImageGeneratorProfile:
        profile = _PROFILES[purpose]
        if profile_name and profile_name != profile.name:
            raise ValueError(
                f"unknown image profile {profile_name!r} for generator 'in-memory'"
            )
        return profile

    async def generate(self, request: ImageGeneratorRequest) -> bytes:
        _load_pillow()
        return await _render_off_loop(
            request.purpose.value,
            request.prompt,
            request.seed,
            request.width,
            request.height,
        )


async def _render_off_loop(
    purpose: str, prompt: str, seed: int, width: int, height: int
) -> bytes:
    """Run Pillow on a short-lived daemon thread without occupying the default executor."""

    result: list[bytes] = []
    failure: list[BaseException] = []

    def run() -> None:
        try:
            result_bytes = _render(purpose, prompt, seed, width, height)
        except BaseException as exc:  # noqa: BLE001 - propagate worker failures to caller
            failure.append(exc)
        else:
            result.append(result_bytes)

    thread = threading.Thread(target=run, name="imagegen-in-memory", daemon=True)
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(0.001)
    if failure:
        raise failure[0]
    return result[0]


def _load_pillow() -> None:
    try:
        from PIL import Image, ImageDraw  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "in-memory image generation requires the 'imagegen' extra: "
            "pip install bunnyland[imagegen]"
        ) from exc


def _render(purpose: str, prompt: str, seed: int, width: int, height: int) -> bytes:
    from PIL import Image, ImageDraw

    digest = sha256(f"{seed}\0{purpose}\0{prompt}".encode()).digest()
    background = tuple(32 + value % 96 for value in digest[:3])
    foreground = tuple(128 + value % 128 for value in digest[3:6])
    accent = tuple(96 + value % 160 for value in digest[6:9])
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    columns, rows = 7, 7
    cell = max(1, min(width // columns, height // rows))
    grid_width, grid_height = cell * columns, cell * rows
    left = (width - grid_width) // 2
    top = (height - grid_height) // 2
    bit = 0
    for row in range(rows):
        for column in range((columns + 1) // 2):
            byte = digest[9 + (bit // 8) % (len(digest) - 9)]
            if byte & (1 << (bit % 8)):
                color = accent if (byte >> 4) & 1 else foreground
                for mirrored in {column, columns - 1 - column}:
                    x0 = left + mirrored * cell
                    y0 = top + row * cell
                    draw.rectangle((x0, y0, x0 + cell - 1, y0 + cell - 1), fill=color)
            bit += 1
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


__all__ = ["InMemoryImageGenerator"]
