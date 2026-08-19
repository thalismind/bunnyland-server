"""Configuration for independent image and video generation services."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..credentials import read_credential
from ..foundation.media.service import DEFAULT_MEDIA_CAPACITY_BYTES
from ..llm_agents.agent import DEFAULT_MODEL


def _env_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(environ: Mapping[str, str], name: str, default: float) -> float:
    value = environ.get(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    value = environ.get(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


@dataclass(frozen=True)
class ComfyUIConfig:
    """Connection and workflow settings shared by ComfyUI adapters."""

    server_url: str = ""
    use_websocket: bool = True
    poll_interval_seconds: float = 1.0
    timeout_seconds: float = 120.0
    templates_path: str = ""
    workflows: str = "anima"


@dataclass(frozen=True)
class ImageGenConfig:
    """Image provider routing and image-only behavior."""

    generator: str = ""
    generators: dict[str, str] = field(default_factory=dict)
    openrouter_image_model: str = ""
    openrouter_api_key: str = ""
    openrouter_server_url: str = ""
    openrouter_result_origins: tuple[str, ...] = ()
    backfill_interval_seconds: float = 5.0
    prompt_enhancer: str = ""

    def generator_for(self, purpose: str) -> str:
        return self.generators.get(purpose, "").strip() or self.generator


@dataclass(frozen=True)
class VideoGenConfig:
    """Video provider selection and its default named profile."""

    generator: str = ""
    profile: str = ""
    prompt_enhancer: str = ""


@dataclass(frozen=True)
class MediaGenConfig:
    """Shared media generation settings with independent modality selections."""

    comfyui: ComfyUIConfig = field(default_factory=ComfyUIConfig)
    image: ImageGenConfig = field(default_factory=ImageGenConfig)
    video: VideoGenConfig = field(default_factory=VideoGenConfig)
    media_root: str = "media"
    media_capacity_bytes: int = DEFAULT_MEDIA_CAPACITY_BYTES
    public_base_url: str = ""
    prompt_style: str = ""
    enhancer: str = ""
    model: str = DEFAULT_MODEL
    host: str = ""
    api_key: str = ""

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> MediaGenConfig | None:
        environ = os.environ if environ is None else environ
        server_url = environ.get("COMFYUI_SERVER_URL", "").strip().rstrip("/")
        image_selected = environ.get("BUNNYLAND_IMAGE_GENERATOR", "").strip()
        image_overrides = {
            purpose: value
            for purpose in ("portrait", "entity", "sprite", "event")
            if (
                value := environ.get(
                    f"BUNNYLAND_IMAGE_GENERATOR_{purpose.upper()}", ""
                ).strip()
            )
        }
        video_selected = environ.get("BUNNYLAND_VIDEO_GENERATOR", "").strip()
        video_profile = environ.get("BUNNYLAND_VIDEO_PROFILE", "").strip()
        if not image_selected and not image_overrides and not video_selected:
            return None
        return cls(
            comfyui=ComfyUIConfig(
                server_url=server_url,
                use_websocket=_env_bool(environ, "COMFYUI_USE_WEBSOCKET", True),
                poll_interval_seconds=_env_float(
                    environ, "COMFYUI_POLL_INTERVAL_SECONDS", 1.0
                ),
                timeout_seconds=_env_float(environ, "COMFYUI_TIMEOUT_SECONDS", 120.0),
                templates_path=environ.get("BUNNYLAND_MEDIA_TEMPLATES", "").strip(),
                workflows=environ.get("BUNNYLAND_IMAGE_WORKFLOWS", "anima").strip()
                or "anima",
            ),
            image=ImageGenConfig(
                generator=image_selected,
                generators=image_overrides,
                openrouter_image_model=environ.get(
                    "BUNNYLAND_IMAGE_OPENROUTER_MODEL", ""
                ).strip(),
                openrouter_api_key=read_credential("OPENROUTER_API_KEY", environ=environ),
                openrouter_server_url=environ.get("OPENROUTER_SERVER_URL", "").strip(),
                openrouter_result_origins=tuple(
                    origin.strip()
                    for origin in environ.get(
                        "BUNNYLAND_IMAGE_OPENROUTER_RESULT_ORIGINS", ""
                    ).split(",")
                    if origin.strip()
                ),
                backfill_interval_seconds=_env_float(
                    environ, "BUNNYLAND_IMAGE_BACKFILL_SECONDS", 5.0
                ),
                prompt_enhancer=environ.get(
                    "BUNNYLAND_IMAGE_PROMPT_ENHANCER", ""
                ).strip(),
            ),
            video=VideoGenConfig(
                generator=video_selected,
                profile=video_profile,
                prompt_enhancer=environ.get(
                    "BUNNYLAND_VIDEO_PROMPT_ENHANCER", ""
                ).strip(),
            ),
            media_root=environ.get("BUNNYLAND_MEDIA_DIR", "media").strip(),
            media_capacity_bytes=_env_int(
                environ,
                "BUNNYLAND_MEDIA_CAPACITY_BYTES",
                DEFAULT_MEDIA_CAPACITY_BYTES,
            ),
            public_base_url=environ.get("BUNNYLAND_PUBLIC_BASE_URL", "")
            .strip()
            .rstrip("/"),
            prompt_style=environ.get("BUNNYLAND_MEDIA_PROMPT_STYLE", "").strip(),
            enhancer=environ.get("BUNNYLAND_MEDIA_ENHANCER", "").strip(),
            model=environ.get("BUNNYLAND_MEDIA_MODEL", DEFAULT_MODEL).strip(),
            host=environ.get("OLLAMA_HOST", "").strip(),
            api_key=read_credential("OLLAMA_CLOUD_API_KEY", environ=environ),
        )


__all__ = ["ComfyUIConfig", "ImageGenConfig", "MediaGenConfig", "VideoGenConfig"]
