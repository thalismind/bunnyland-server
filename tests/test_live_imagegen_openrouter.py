"""Opt-in live OpenRouter image-modality validation."""

from __future__ import annotations

import os

import pytest
from conftest import build_scenario

from bunnyland.imagegen.components import PortraitImageComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.generators import ImageGeneratorRequest
from bunnyland.imagegen.openrouter import OpenRouterImageGenerator
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.imagegen.wiring import build_image_service

pytestmark = pytest.mark.live_imagegen_openrouter

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _live_config(tmp_path=None) -> ImageGenConfig:
    if os.environ.get("BUNNYLAND_LIVE_IMAGEGEN_OPENROUTER") != "1":
        pytest.skip("set BUNNYLAND_LIVE_IMAGEGEN_OPENROUTER=1 to run live OpenRouter tests")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        pytest.skip("set OPENROUTER_API_KEY to run live OpenRouter image tests")
    model = os.environ.get("BUNNYLAND_LIVE_OPENROUTER_IMAGE_MODEL", "").strip()
    if not model:
        pytest.skip("set BUNNYLAND_LIVE_OPENROUTER_IMAGE_MODEL for live image tests")
    return ImageGenConfig(
        generator="openrouter",
        openrouter_image_model=model,
        openrouter_api_key=api_key,
        openrouter_server_url=os.environ.get("OPENROUTER_SERVER_URL", "").strip(),
        media_root=str(tmp_path) if tmp_path is not None else "media",
    )


async def test_live_openrouter_image_modality(tmp_path):
    config = _live_config(tmp_path)
    generator = OpenRouterImageGenerator(
        model=config.openrouter_image_model,
        api_key=config.openrouter_api_key,
        server_url=config.openrouter_server_url,
    )
    data = await generator.generate(
        ImageGeneratorRequest(
            purpose=ImagePurpose.ENTITY,
            prompt="a simple friendly cartoon rabbit icon on a plain background",
            seed=7,
            width=512,
            height=512,
            profile_name="entity",
        )
    )
    assert data.startswith(_PNG_MAGIC)


async def test_live_openrouter_service_job(tmp_path):
    config = _live_config(tmp_path)
    scenario = build_scenario()
    service = build_image_service(scenario.actor, config)
    job = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await service.wait_idle()
    assert job.status == "succeeded", job.error
    portrait = scenario.actor.world.get_entity(scenario.character).get_component(
        PortraitImageComponent
    )
    name = portrait.url.rsplit("/", 1)[-1]
    assert service.media.read("portraits", name).startswith(_PNG_MAGIC)
    assert portrait.generator == "openrouter"
    await service.aclose()
