"""Optional live ComfyUI image-generation tests.

Skipped by default. Enable with ``BUNNYLAND_LIVE_GENERATION=1`` and ``COMFYUI_SERVER_URL``
pointing at a reachable ComfyUI server. These submit real workflows and fetch real images,
so they are slow and excluded from the default gate (like the live LLM tests).

The tests discover an available checkpoint from the server and build a small, fast workflow,
so they work against any ComfyUI without depending on the shipped default model name.
"""

from __future__ import annotations

import os

import pytest
from conftest import build_scenario

from bunnyland.core import container_of
from bunnyland.core.ecs import parse_entity_id
from bunnyland.imagegen.client import HttpComfyClient, build_comfy_client
from bunnyland.imagegen.components import EventImageComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.media import SEGMENT_EVENTS, MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.scene import request_scene_image
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.spec import (
    ImagePurpose,
    SubstitutionSlot,
    WorkflowTemplate,
    substitute,
)
from bunnyland.imagegen.store import WorkflowTemplateStore
from bunnyland.mechanics.history import record_world_history

pytestmark = pytest.mark.live_generation

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _live_config() -> ImageGenConfig:
    if os.environ.get("BUNNYLAND_LIVE_GENERATION") != "1":
        pytest.skip("set BUNNYLAND_LIVE_GENERATION=1 to run live generation tests")
    config = ImageGenConfig.from_env()
    if config is None:
        pytest.skip("set COMFYUI_SERVER_URL to run live generation tests")
    # Generous timeout for a real diffusion run.
    return ImageGenConfig(
        server_url=config.server_url,
        use_websocket=config.use_websocket,
        poll_interval_seconds=2.0,
        timeout_seconds=300.0,
    )


async def _discover_checkpoint(config: ImageGenConfig) -> str:
    import httpx

    async with httpx.AsyncClient(base_url=config.server_url, timeout=30.0) as http:
        response = await http.get("/object_info/CheckpointLoaderSimple")
        response.raise_for_status()
        info = response.json()
    names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    if not names:
        pytest.skip("the ComfyUI server has no checkpoints installed")
    return names[0]


def _live_template(checkpoint: str, purpose: ImagePurpose) -> WorkflowTemplate:
    return WorkflowTemplate(
        name=f"live-{purpose.value}",
        purpose=purpose,
        width=512,
        height=512,
        output_node_id="9",
        graph={
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 512, "height": 512, "batch_size": 1},
            },
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 0,
                    "steps": 8,
                    "cfg": 6.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "bunnyland_live", "images": ["8", 0]},
            },
        },
        slots=(
            SubstitutionSlot(node_id="6", field_path=("inputs", "text"), token="%PROMPT%"),
            SubstitutionSlot(node_id="7", field_path=("inputs", "text"), token="%NEGATIVE%"),
            SubstitutionSlot(node_id="3", field_path=("inputs", "seed"), token="%SEED%"),
            SubstitutionSlot(node_id="5", field_path=("inputs", "width"), token="%WIDTH%"),
            SubstitutionSlot(node_id="5", field_path=("inputs", "height"), token="%HEIGHT%"),
        ),
    )


async def test_live_http_generation():
    config = _live_config()
    checkpoint = await _discover_checkpoint(config)
    template = _live_template(checkpoint, ImagePurpose.ENTITY)
    graph = substitute(
        template, prompt="a friendly cartoon rabbit, masterpiece, best quality", seed=7
    )
    client = HttpComfyClient(config)
    data = await client.generate(graph, output_node_id=template.output_node_id)
    assert data.startswith(_PNG_MAGIC)


async def test_live_websocket_generation():
    config = _live_config()
    if not config.use_websocket:
        pytest.skip("COMFYUI_USE_WEBSOCKET is disabled")
    checkpoint = await _discover_checkpoint(config)
    template = _live_template(checkpoint, ImagePurpose.ENTITY)
    graph = substitute(template, prompt="a friendly cartoon fox, masterpiece", seed=11)
    client = build_comfy_client(config)
    data = await client.generate(graph, output_node_id=template.output_node_id)
    assert data.startswith(_PNG_MAGIC)


async def test_live_scene_end_to_end(tmp_path):
    config = _live_config()
    checkpoint = await _discover_checkpoint(config)
    scenario = build_scenario()
    world = scenario.actor.world
    room_id = container_of(world.get_entity(scenario.character))
    record_world_history(
        world,
        summary="seed",
        source_event_id="seed",
        event_type="scene",
        created_at_epoch=0,
        location_id=str(room_id),
    )
    service = ImageGenService(
        scenario.actor,
        config,
        client=build_comfy_client(config),
        templates=WorkflowTemplateStore(
            defaults=[_live_template(checkpoint, ImagePurpose.EVENT)]
        ),
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )
    job = await request_scene_image(scenario.actor, service, character_id=scenario.character)
    assert job is not None
    await service.wait_idle()
    record = world.get_entity(parse_entity_id(job.entity_id))
    image = record.get_component(EventImageComponent)
    assert image.url.startswith("/media/events/")
    name = image.url.split("/")[-1]
    assert MediaStore(tmp_path).read(SEGMENT_EVENTS, name).startswith(_PNG_MAGIC)
    await service.aclose()
