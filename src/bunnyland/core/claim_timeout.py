"""Helpers for player claim timeout state."""

from __future__ import annotations

from dataclasses import replace

from relics import Entity

from .controllers import ClaimTimeoutComponent
from .ecs import replace_component

CLAIM_FALLBACK_SUSPEND = "suspend"
CLAIM_FALLBACK_LLM = "llm"
VALID_CLAIM_FALLBACK_CONTROLLERS = frozenset(
    {CLAIM_FALLBACK_SUSPEND, CLAIM_FALLBACK_LLM}
)
CLAIM_TIMEOUT_MIN_SECONDS = 5 * 60
CLAIM_TIMEOUT_MAX_SECONDS = 60 * 60
CLAIM_TIMEOUT_DEFAULT_SECONDS = 30 * 60


def normalize_claim_fallback(value: str | None) -> str:
    normalized = (value or CLAIM_FALLBACK_SUSPEND).strip().lower().replace("_", "-")
    if normalized in {"suspended", "offline"}:
        return CLAIM_FALLBACK_SUSPEND
    if normalized in {"ai", "agent"}:
        return CLAIM_FALLBACK_LLM
    if normalized not in VALID_CLAIM_FALLBACK_CONTROLLERS:
        valid = ", ".join(sorted(VALID_CLAIM_FALLBACK_CONTROLLERS))
        raise ValueError(f"fallback_controller must be one of: {valid}")
    return normalized


def normalize_claim_timeout(value: int | None) -> int | None:
    if value is None:
        return None
    seconds = int(value)
    if seconds < CLAIM_TIMEOUT_MIN_SECONDS or seconds > CLAIM_TIMEOUT_MAX_SECONDS:
        raise ValueError(
            "timeout_seconds must be between "
            f"{CLAIM_TIMEOUT_MIN_SECONDS} and {CLAIM_TIMEOUT_MAX_SECONDS}"
        )
    return seconds


def apply_claim_timeout_settings(
    controller: Entity,
    *,
    now_unix: int,
    fallback_controller: str | None = None,
    fallback_reason: str | None = None,
    llm_profile_name: str | None = None,
    llm_model: str | None = None,
    llm_provider: str | None = None,
    timeout_seconds: int | None = None,
    reset_activity: bool = False,
) -> ClaimTimeoutComponent:
    existing = (
        controller.get_component(ClaimTimeoutComponent)
        if controller.has_component(ClaimTimeoutComponent)
        else None
    )
    if fallback_controller is None:
        fallback = (
            existing.fallback_controller
            if existing is not None
            else CLAIM_FALLBACK_SUSPEND
        )
    else:
        fallback = normalize_claim_fallback(fallback_controller)

    component = ClaimTimeoutComponent(
        fallback_controller=fallback,
        fallback_reason=(
            fallback_reason.strip()
            if fallback_reason and fallback_reason.strip()
            else (
                existing.fallback_reason
                if existing is not None
                else "claim timed out"
            )
        ),
        llm_profile_name=(
            llm_profile_name.strip()
            if llm_profile_name and llm_profile_name.strip()
            else (
                existing.llm_profile_name
                if existing is not None
                else "default"
            )
        ),
        llm_model=(
            llm_model.strip()
            if llm_model and llm_model.strip()
            else (existing.llm_model if existing is not None else "")
        ),
        llm_provider=(
            llm_provider.strip()
            if llm_provider and llm_provider.strip()
            else (existing.llm_provider if existing is not None else "")
        ),
        timeout_seconds=(
            normalize_claim_timeout(timeout_seconds)
            if timeout_seconds is not None
            else (existing.timeout_seconds if existing is not None else 0)
        ),
        claimed_at_unix=(
            now_unix if reset_activity or existing is None else existing.claimed_at_unix
        ),
        last_command_unix=(
            now_unix if reset_activity or existing is None else existing.last_command_unix
        ),
    )
    if existing is None:
        controller.add_component(component)
    else:
        replace_component(controller, component)
    return component


def record_claim_activity(controller: Entity, *, now_unix: int) -> None:
    if not controller.has_component(ClaimTimeoutComponent):
        return
    activity = controller.get_component(ClaimTimeoutComponent)
    replace_component(controller, replace(activity, last_command_unix=now_unix))


__all__ = [
    "CLAIM_FALLBACK_LLM",
    "CLAIM_FALLBACK_SUSPEND",
    "CLAIM_TIMEOUT_DEFAULT_SECONDS",
    "CLAIM_TIMEOUT_MAX_SECONDS",
    "CLAIM_TIMEOUT_MIN_SECONDS",
    "VALID_CLAIM_FALLBACK_CONTROLLERS",
    "apply_claim_timeout_settings",
    "normalize_claim_fallback",
    "normalize_claim_timeout",
    "record_claim_activity",
]
