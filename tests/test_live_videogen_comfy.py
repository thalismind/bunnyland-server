"""Optional live ComfyUI event-video generation test.

Skipped by default. Enable independently from image and text generation with
``BUNNYLAND_LIVE_VIDEOGEN_COMFY=1`` and point ``COMFYUI_SERVER_URL`` at a reachable
ComfyUI server. This submits the shipped LTX 2.3 workflow and can take several minutes.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
from conftest import build_scenario

from bunnyland.core import parse_entity_id
from bunnyland.foundation.media.service import sniff_video_extension
from bunnyland.imagegen.components import EventVideoComponent
from bunnyland.imagegen.config import MediaGenConfig, VideoGenConfig
from bunnyland.imagegen.media import SEGMENT_VIDEOS
from bunnyland.imagegen.scene import request_scene_video
from bunnyland.imagegen.wiring import build_media_services

pytestmark = pytest.mark.live_videogen_comfy


def _live_config(tmp_path) -> MediaGenConfig:
    if os.environ.get("BUNNYLAND_LIVE_VIDEOGEN_COMFY") != "1":
        pytest.skip(
            "set BUNNYLAND_LIVE_VIDEOGEN_COMFY=1 to run live ComfyUI video tests"
        )
    config = MediaGenConfig.from_env()
    if config is None or not config.comfyui.server_url:
        pytest.skip("set COMFYUI_SERVER_URL to run live ComfyUI video tests")
    return replace(
        config,
        comfyui=replace(
            config.comfyui,
            poll_interval_seconds=2.0,
            timeout_seconds=1800.0,
        ),
        media_root=str(tmp_path),
        video=VideoGenConfig(generator="comfyui", profile="event-video"),
    )


async def test_live_shipped_ltx_event_video_end_to_end(tmp_path):
    scenario = build_scenario()
    service = build_media_services(scenario.actor, _live_config(tmp_path)).video
    assert service is not None
    try:
        job = await request_scene_video(
            scenario.actor,
            service,
            character_id=scenario.character,
            requested_by="live-videogen-test",
        )
        assert job is not None
        await service.wait_idle()
        assert job.status == "succeeded", job.error

        record_id = parse_entity_id(job.entity_id)
        assert record_id is not None
        video = scenario.actor.world.get_entity(record_id).get_component(EventVideoComponent)
        name = video.url.rsplit("/", 1)[-1]
        data = service.media.read(SEGMENT_VIDEOS, name)
        assert sniff_video_extension(data) in {"mp4", "webm"}
    finally:
        await service.aclose()
