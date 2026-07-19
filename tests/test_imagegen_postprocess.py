"""Tests for alpha-background post-processing and its service integration."""

from __future__ import annotations

import sys
from io import BytesIO

import pytest
from conftest import build_scenario
from PIL import Image

from bunnyland.imagegen.components import PortraitImageComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.media import SEGMENT_ALPHA, SEGMENT_SPRITES, MediaStore
from bunnyland.imagegen.postprocess import remove_edge_background
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.simpacks.toonsim.mechanics import SpriteImageComponent


@pytest.fixture(autouse=True)
def inline_to_thread(monkeypatch):
    async def run_inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", run_inline)


def _png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    height = len(pixels)
    width = len(pixels[0])
    image = Image.new("RGBA", (width, height))
    for y, row in enumerate(pixels):
        for x, pixel in enumerate(row):
            image.putpixel((x, y), pixel)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


W = (255, 255, 255, 255)  # white (background)
R = (200, 30, 30, 255)  # red (foreground)
T = (255, 255, 255, 0)  # already transparent


def test_remove_edge_background_clears_border_keeps_center():
    # 3x3: white border, red center.
    data = _png([[W, W, W], [W, R, W], [W, W, W]])
    out = Image.open(BytesIO(remove_edge_background(data, max_size=0)))
    assert out.getpixel((0, 0))[3] == 0  # corner became transparent
    assert out.getpixel((1, 1)) == R  # center preserved


def test_remove_edge_background_preserves_internal_white():
    # White center surrounded by red ring: the inner white is not edge-reachable.
    data = _png(
        [
            [R, R, R],
            [R, W, R],
            [R, R, R],
        ]
    )
    out = Image.open(BytesIO(remove_edge_background(data, max_size=0)))
    assert out.getpixel((1, 1)) == W  # internal white kept (alpha 255)


def test_remove_edge_background_handles_existing_transparency():
    # An already-transparent edge pixel exercises the alpha==0 background branch.
    data = _png([[T, W, W], [W, R, W], [W, W, W]])
    out = Image.open(BytesIO(remove_edge_background(data, max_size=0)))
    assert out.getpixel((0, 0))[3] == 0


def test_remove_edge_background_thumbnails():
    data = _png([[W] * 4 for _ in range(4)])
    out = Image.open(BytesIO(remove_edge_background(data, max_size=2)))
    assert max(out.size) <= 2


def test_remove_edge_background_requires_pillow(monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(RuntimeError, match="requires the 'imagegen' extra"):
        remove_edge_background(b"whatever")


# --- service integration -------------------------------------------------------------


def _service(actor, tmp_path, *, alpha):
    return ImageGenService(
        actor,
        ImageGenConfig(server_url="http://comfy.local"),
        client=_StaticClient(),
        templates=WorkflowTemplateStore(defaults=default_templates()),
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
        alpha=alpha,
    )


class _StaticClient:
    async def generate(self, graph, *, output_node_id=""):
        return b"RAW"


def _fake_alpha(data: bytes) -> bytes:
    return b"ALPHA:" + data


async def test_portrait_alpha_writes_both_variants(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path, alpha=_fake_alpha)
    await service.start(str(scenario.character), ImagePurpose.PORTRAIT, alpha=True)
    await service.wait_idle()
    portrait = scenario.actor.world.get_entity(scenario.character).get_component(
        PortraitImageComponent
    )
    assert portrait.url.startswith("/v1/public/media/portraits/")
    assert portrait.alpha_url.startswith("/v1/public/media/alpha/")
    alpha_name = portrait.alpha_url.split("/")[-1]
    assert MediaStore(tmp_path).read(SEGMENT_ALPHA, alpha_name) == b"ALPHA:RAW"
    await service.aclose()


async def test_sprite_alpha_is_the_sprite(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(SpriteImageComponent())
    service = _service(scenario.actor, tmp_path, alpha=_fake_alpha)
    # Sprites get alpha automatically (no explicit alpha=True needed).
    await service.start(str(scenario.character), ImagePurpose.SPRITE)
    await service.wait_idle()
    sprite = scenario.actor.world.get_entity(scenario.character).get_component(SpriteImageComponent)
    name = sprite.url.split("/")[-1]
    assert MediaStore(tmp_path).read(SEGMENT_SPRITES, name) == b"ALPHA:RAW"
    await service.aclose()


async def test_portrait_without_alpha_request_skips_alpha(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path, alpha=_fake_alpha)
    await service.start(str(scenario.character), ImagePurpose.PORTRAIT)  # alpha not requested
    await service.wait_idle()
    portrait = scenario.actor.world.get_entity(scenario.character).get_component(
        PortraitImageComponent
    )
    assert portrait.alpha_url == ""
    await service.aclose()


async def test_alpha_request_without_processor_is_noop(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path, alpha=None)
    await service.start(str(scenario.character), ImagePurpose.PORTRAIT, alpha=True)
    await service.wait_idle()
    portrait = scenario.actor.world.get_entity(scenario.character).get_component(
        PortraitImageComponent
    )
    assert portrait.alpha_url == ""
    await service.aclose()
