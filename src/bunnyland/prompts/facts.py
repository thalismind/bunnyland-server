"""Typed, progressively disclosed facts used by prompts and inspection views."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

STANDARD_DETAIL_CUTOFF = 10
DETAILED_DETAIL_CUTOFF = 30

_KEY_PART = re.compile(r"[^a-z0-9.-]+")


@dataclass(frozen=True)
class PromptFact:
    """One stable fact with a lower-is-more-important disclosure score."""

    key: str
    text: str
    detail: int = STANDARD_DETAIL_CUTOFF

    def __post_init__(self) -> None:
        if not self.key or "." not in self.key:
            raise ValueError("prompt fact key must be namespaced")
        if not self.text.strip():
            raise ValueError("prompt fact text must not be empty")
        if isinstance(self.detail, bool) or not isinstance(self.detail, int) or self.detail < 0:
            raise ValueError("prompt fact detail must be a non-negative integer")


PromptFactLike = str | PromptFact


def _key_part(value: str) -> str:
    return _KEY_PART.sub("-", value.lower()).strip("-") or "provider"


def coerce_prompt_facts(
    values: Iterable[PromptFactLike],
    *,
    namespace: str,
) -> tuple[PromptFact, ...]:
    """Normalize provider output while component formatters migrate to native facts.

    The provider namespace and output position give older string formatters deterministic
    keys. New and state-dependent formatters should return ``PromptFact`` directly so their
    keys remain stable when wording or output order changes.
    """

    prefix = _key_part(namespace)
    facts = tuple(
        value
        if isinstance(value, PromptFact)
        else PromptFact(key=f"{prefix}.fact-{index}", text=value)
        for index, value in enumerate(values)
    )
    keys = [fact.key for fact in facts]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate prompt fact key from {namespace}")
    return facts


def visible_prompt_facts(
    facts: Sequence[PromptFact], *, cutoff: int
) -> tuple[PromptFact, ...]:
    if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff < 0:
        raise ValueError("prompt fact cutoff must be a non-negative integer")
    return tuple(fact for fact in facts if fact.detail <= cutoff)


def collect_prompt_facts(
    world: object,
    entity: object,
    providers: Sequence[Callable[..., Iterable[PromptFactLike]]],
    *,
    cutoff: int,
    viewer: object | None = None,
) -> tuple[PromptFact, ...]:
    """Collect, validate, and filter registered providers deterministically."""

    if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff < 0:
        raise ValueError("prompt fact cutoff must be a non-negative integer")
    collected: list[PromptFact] = []
    seen: set[str] = set()
    same_viewer = viewer is None or getattr(viewer, "id", None) == getattr(entity, "id", None)
    for provider in providers:
        qualname = getattr(provider, "__qualname__", type(provider).__qualname__)
        namespace = f"{provider.__module__}.{qualname}"
        parameters = inspect.signature(provider).parameters
        if not same_viewer and "viewer" not in parameters:
            # A provider that cannot receive the real viewer would construct a self context
            # for the inspected entity and could expose private facts.
            continue
        kwargs: dict[str, object] = {}
        if "detail_cutoff" in parameters:
            kwargs["detail_cutoff"] = cutoff
        if "viewer" in parameters:
            kwargs["viewer"] = viewer
        values = (
            provider(world, entity, **kwargs)
            if kwargs
            else provider(world, entity)
        )
        for fact in coerce_prompt_facts(values, namespace=namespace):
            if fact.key in seen:
                raise ValueError(f"duplicate prompt fact key {fact.key!r}")
            seen.add(fact.key)
            if fact.detail <= cutoff:
                collected.append(fact)
    return tuple(collected)


__all__ = [
    "DETAILED_DETAIL_CUTOFF",
    "PromptFact",
    "PromptFactLike",
    "STANDARD_DETAIL_CUTOFF",
    "coerce_prompt_facts",
    "collect_prompt_facts",
    "visible_prompt_facts",
]
