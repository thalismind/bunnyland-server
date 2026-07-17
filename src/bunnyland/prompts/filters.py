"""Asynchronous post-render prompt filtering.

Prompt building and rendering remain deterministic, synchronous compilation steps.  This
module applies character-bound filters afterwards, when memory or LLM access may require
awaiting external services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from relics import Component, Entity, World

from .builder import PromptContext

LOG = logging.getLogger("bunnyland.prompt_filters")


class PromptFilterHandler(Protocol):
    async def __call__(
        self,
        text: str,
        context: PromptFilterContext,
        component: Component,
    ) -> str: ...


@dataclass(frozen=True)
class PromptFilterDefinition:
    """Plugin contribution binding one typed component to an async text filter."""

    id: str
    component_type: type[Component]
    handler: PromptFilterHandler


@dataclass(frozen=True)
class PromptFilterContext:
    world: World
    character: Entity
    filter_entity: Entity
    prompt: PromptContext
    epoch: int = 0
    memory_store: Any | None = None
    llm: Any | None = None


class PromptFilterRuntime:
    """Resolve a character's bounded filter relationships and apply them in order."""

    def __init__(self, actor, definitions=(), *, llm=None) -> None:
        self.actor = actor
        self.llm = llm
        self._by_component: dict[type[Component], PromptFilterDefinition] = {}
        for definition in definitions:
            previous = self._by_component.get(definition.component_type)
            if previous is not None:
                raise ValueError(
                    f"prompt filter component {definition.component_type.__name__!r} "
                    f"is registered by both {previous.id!r} and {definition.id!r}"
                )
            self._by_component[definition.component_type] = definition

    @classmethod
    def from_actor(cls, actor, *, llm=None) -> PromptFilterRuntime:
        definitions = ()
        plugins = getattr(actor, "plugins", None)
        if plugins is not None:
            definitions = tuple(value for _owner, value in plugins.prompt_filters.values())
        return cls(actor, definitions, llm=llm)

    async def apply(
        self,
        text: str,
        *,
        character: Entity,
        prompt: PromptContext,
        epoch: int = 0,
    ) -> str:
        from bunnyland.foundation.prompt_filters.mechanics import PromptFilterBinding

        bindings = sorted(
            character.get_relationships(PromptFilterBinding),
            key=lambda item: (item[0].order, str(item[1])),
        )
        current = text
        for binding, filter_id in bindings:
            del binding
            filter_entity = self.actor.world.get_entity(filter_id)
            matches = [
                (component_type, definition)
                for component_type, definition in self._by_component.items()
                if filter_entity.has_component(component_type)
            ]
            if len(matches) != 1:
                LOG.warning(
                    "prompt filter entity %s has %d registered filter components; skipping",
                    filter_id,
                    len(matches),
                )
                continue
            component_type, definition = matches[0]
            component = filter_entity.get_component(component_type)
            context = PromptFilterContext(
                world=self.actor.world,
                character=character,
                filter_entity=filter_entity,
                prompt=prompt,
                epoch=epoch,
                memory_store=getattr(self.actor, "memory_store", None),
                llm=self.llm,
            )
            try:
                filtered = await definition.handler(current, context, component)
                if not isinstance(filtered, str):
                    raise TypeError(
                        f"prompt filter {definition.id!r} returned "
                        f"{type(filtered).__name__}, expected str"
                    )
                current = filtered
            except Exception:
                LOG.exception(
                    "prompt filter %s failed for character %s; keeping prior text",
                    definition.id,
                    character.id,
                )
        return current


async def apply_prompt_filters(
    text: str,
    *,
    runtime: PromptFilterRuntime | None,
    character: Entity,
    context: PromptContext,
    epoch: int = 0,
) -> str:
    """Apply the configured stack, or return raw compiled text when none is configured."""

    if runtime is None:
        return text
    return await runtime.apply(text, character=character, prompt=context, epoch=epoch)


__all__ = [
    "PromptFilterContext",
    "PromptFilterDefinition",
    "PromptFilterHandler",
    "PromptFilterRuntime",
    "apply_prompt_filters",
]
