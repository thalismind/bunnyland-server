"""Alpha-background post-processing for generated images (spec 27).

A port of the bunnyland-media ``remove-edge-white.py`` script that works on PNG bytes: it
flood-fills near-white pixels reachable from the image edge and makes them transparent,
preserving internal white artwork. This is CPU-intensive, so the service always runs it via
``asyncio.to_thread`` -- it must never run inline on the event loop or game tick. Pillow is
imported lazily, behind the ``imagegen`` extra.
"""

from __future__ import annotations

from collections import deque
from io import BytesIO

#: Defaults matched to the media repo's script.
DEFAULT_THRESHOLD = 242
DEFAULT_MAX_SPREAD = 18
DEFAULT_MAX_SIZE = 512


def _is_background_pixel(
    pixel: tuple[int, int, int, int], *, threshold: int, max_spread: int
) -> bool:
    red, green, blue, alpha = pixel
    if alpha == 0:
        return True
    channels = (red, green, blue)
    return min(channels) >= threshold and max(channels) - min(channels) <= max_spread


def _flood_fill_edges(output, *, threshold: int, max_spread: int) -> None:
    pixels = output.load()
    width, height = output.size
    queue: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if (x, y) in seen or not (0 <= x < width and 0 <= y < height):
            continue
        seen.add((x, y))
        if not _is_background_pixel(pixels[x, y], threshold=threshold, max_spread=max_spread):
            continue
        pixels[x, y] = (255, 255, 255, 0)
        queue.append((x + 1, y))
        queue.append((x - 1, y))
        queue.append((x, y + 1))
        queue.append((x, y - 1))


def remove_edge_background(
    data: bytes,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    max_spread: int = DEFAULT_MAX_SPREAD,
    max_size: int = DEFAULT_MAX_SIZE,
) -> bytes:
    """Return PNG bytes with the edge-connected near-white background made transparent."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "alpha post-processing requires the 'imagegen' extra (Pillow): "
            "pip install bunnyland[imagegen]"
        ) from exc
    output = Image.open(BytesIO(data)).convert("RGBA")
    _flood_fill_edges(output, threshold=threshold, max_spread=max_spread)
    if max_size > 0:
        output.thumbnail((max_size, max_size), Image.LANCZOS)
    buffer = BytesIO()
    output.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


__all__ = [
    "DEFAULT_MAX_SIZE",
    "DEFAULT_MAX_SPREAD",
    "DEFAULT_THRESHOLD",
    "remove_edge_background",
]
