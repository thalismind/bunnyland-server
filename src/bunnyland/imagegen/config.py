"""Configuration for ComfyUI image generation (spec 27).

The whole feature is opt-in: image generation is only available when ``COMFYUI_SERVER_URL``
is set, so :func:`ImageGenConfig.from_env` returns ``None`` when it is absent and the server
runs exactly as before. Secrets (the LLM api key) live here only at runtime and are never
serialized into snapshots or saves.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

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


@dataclass(frozen=True)
class ImageGenConfig:
    """Connection and behavior settings for the image generation subsystem."""

    server_url: str
    use_websocket: bool = True
    poll_interval_seconds: float = 1.0
    timeout_seconds: float = 120.0
    backfill_interval_seconds: float = 5.0
    media_root: str = "media"
    public_base_url: str = ""
    templates_path: str = ""
    #: Workflow family to use for images. The base is the first keyword (before the first
    #: "-"): "anima" (default, lowest VRAM), "sdxl", "klein", or "flux2dev" (highest
    #: quality). A suffix is allowed for a server's own label, e.g. "anima-my-server".
    workflows: str = "anima"
    #: Override the prompt style for every job ("tag" or "natural"); empty uses each
    #: template's own style.
    prompt_style: str = ""
    enhancer: str = ""
    model: str = DEFAULT_MODEL
    host: str = ""
    api_key: str = ""

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ImageGenConfig | None:
        """Build a config from environment variables, or ``None`` when imagegen is disabled."""
        environ = os.environ if environ is None else environ
        server_url = environ.get("COMFYUI_SERVER_URL", "").strip()
        if not server_url:
            return None
        return cls(
            server_url=server_url.rstrip("/"),
            use_websocket=_env_bool(environ, "COMFYUI_USE_WEBSOCKET", True),
            poll_interval_seconds=_env_float(environ, "COMFYUI_POLL_INTERVAL_SECONDS", 1.0),
            timeout_seconds=_env_float(environ, "COMFYUI_TIMEOUT_SECONDS", 120.0),
            backfill_interval_seconds=_env_float(
                environ, "BUNNYLAND_IMAGE_BACKFILL_SECONDS", 5.0
            ),
            media_root=environ.get("BUNNYLAND_MEDIA_DIR", "media").strip(),
            public_base_url=environ.get("BUNNYLAND_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            templates_path=environ.get("BUNNYLAND_IMAGE_TEMPLATES", "").strip(),
            workflows=environ.get("BUNNYLAND_IMAGE_WORKFLOWS", "anima").strip() or "anima",
            prompt_style=environ.get("BUNNYLAND_IMAGE_PROMPT_STYLE", "").strip(),
            enhancer=environ.get("BUNNYLAND_IMAGE_ENHANCER", "").strip(),
            model=environ.get("BUNNYLAND_IMAGE_MODEL", DEFAULT_MODEL).strip(),
            host=environ.get("OLLAMA_HOST", "").strip(),
            api_key=environ.get("OLLAMA_CLOUD_API_KEY", "").strip(),
        )


__all__ = ["ImageGenConfig"]
