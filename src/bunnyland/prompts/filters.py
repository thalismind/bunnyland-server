"""Asynchronous post-render prompt filtering.

Prompt building and rendering remain deterministic, synchronous compilation steps.  This
module applies character-bound filters afterwards, when memory or LLM access may require
awaiting external services.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue
from relics import Component, Entity, World

from .. import telemetry
from ..core.world_actor import WorldActor
from ..memory.store import MemoryStore
from .builder import PromptContext

LOG = logging.getLogger("bunnyland.prompt_filters")


class PromptFilterHandler(Protocol):
    async def __call__(
        self,
        text: str,
        context: PromptFilterContext,
        component: Component,
    ) -> str: ...


class PromptFilterReply(Protocol):
    content: str


class PromptFilterLLM(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict[str, JsonValue]] | None = None,
    ) -> PromptFilterReply: ...


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
    filter_entity: Entity | None
    filter_key: str
    prompt: PromptContext
    epoch: int = 0
    memory_store: MemoryStore | None = None
    llm: PromptFilterLLM | None = None


@dataclass(frozen=True)
class AutomaticPromptFilter:
    """Runtime-only filter selected by character state, without persistent ECS edges."""

    definition_id: str
    required_component: type[Component]
    component_factory: Callable[[], Component | None]


class PromptFilterRuntime:
    """Resolve a character's bounded filter relationships and apply them in order."""

    def __init__(
        self,
        actor: WorldActor,
        definitions: Sequence[PromptFilterDefinition] = (),
        *,
        llm: PromptFilterLLM | None = None,
    ) -> None:
        self.actor = actor
        self.llm = llm
        self._by_component: dict[type[Component], PromptFilterDefinition] = {}
        self._by_id: dict[str, PromptFilterDefinition] = {}
        for definition in definitions:
            if definition.id in self._by_id:
                raise ValueError(f"duplicate prompt filter definition {definition.id!r}")
            previous = self._by_component.get(definition.component_type)
            if previous is not None:
                raise ValueError(
                    f"prompt filter component {definition.component_type.__name__!r} "
                    f"is registered by both {previous.id!r} and {definition.id!r}"
                )
            self._by_component[definition.component_type] = definition
            self._by_id[definition.id] = definition

    @classmethod
    def from_actor(
        cls, actor: WorldActor, *, llm: PromptFilterLLM | None = None
    ) -> PromptFilterRuntime:
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
        include_automatic: bool = True,
    ) -> str:
        from bunnyland.foundation.prompt_filters.mechanics import PromptFilterBinding

        bindings = sorted(
            character.get_relationships(PromptFilterBinding),
            key=lambda item: (item[0].order, str(item[1])),
        )
        current = text
        explicitly_bound: set[str] = set()
        for binding, filter_id in bindings:
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
            explicitly_bound.add(definition.id)
            component = filter_entity.get_component(component_type)
            current = await self._apply_definition(
                current,
                definition=definition,
                component=component,
                character=character,
                prompt=prompt,
                epoch=epoch,
                filter_entity=filter_entity,
                filter_key=str(filter_id),
                mode="explicit",
                order=binding.order,
            )

        for automatic in self.actor.automatic_prompt_filters if include_automatic else ():
            if automatic.definition_id in explicitly_bound:
                continue
            if not character.has_component(automatic.required_component):
                continue
            definition = self._by_id.get(automatic.definition_id)
            if definition is None:
                continue
            component = automatic.component_factory()
            if component is None:
                continue
            if not isinstance(component, definition.component_type):
                LOG.warning(
                    "automatic prompt filter %s produced %s, expected %s; skipping",
                    definition.id,
                    type(component).__name__,
                    definition.component_type.__name__,
                )
                continue
            current = await self._apply_definition(
                current,
                definition=definition,
                component=component,
                character=character,
                prompt=prompt,
                epoch=epoch,
                filter_entity=None,
                filter_key=f"automatic:{definition.id}",
                mode="automatic",
                order=None,
            )
        return current

    async def _apply_definition(
        self,
        text: str,
        *,
        definition: PromptFilterDefinition,
        component: Component,
        character: Entity,
        prompt: PromptContext,
        epoch: int,
        filter_entity: Entity | None,
        filter_key: str,
        mode: str,
        order: int | None,
    ) -> str:
        context = PromptFilterContext(
            world=self.actor.world,
            character=character,
            filter_entity=filter_entity,
            filter_key=filter_key,
            prompt=prompt,
            epoch=epoch,
            memory_store=self.actor.memory_store,
            llm=self.llm,
        )
        attributes: dict[str, str | int] = {
            "character.id": str(character.id),
            "prompt.filter.id": definition.id,
            "prompt.filter.component": type(component).__name__,
            "prompt.filter.key": filter_key,
            "prompt.filter.mode": mode,
            "prompt.filter.input_chars": len(text),
        }
        if order is not None:
            attributes["prompt.filter.order"] = order
        if filter_entity is not None:
            attributes["prompt.filter.entity_id"] = str(filter_entity.id)
        with telemetry.span("prompt.filter.apply", attributes) as filter_span:
            try:
                filtered = await definition.handler(text, context, component)
                if not isinstance(filtered, str):
                    raise TypeError(
                        f"prompt filter {definition.id!r} returned "
                        f"{type(filtered).__name__}, expected str"
                    )
                filter_span.set_attribute("prompt.filter.changed", filtered != text)
                filter_span.set_attribute("prompt.filter.output_chars", len(filtered))
                filter_span.set_attribute("prompt.filter.status", "applied")
                telemetry.mark_span_ok(filter_span)
                return filtered
            except Exception as exc:
                filter_span.set_attribute("prompt.filter.changed", False)
                filter_span.set_attribute("prompt.filter.output_chars", len(text))
                filter_span.set_attribute("prompt.filter.status", "failed")
                filter_span.record_exception(exc)
                telemetry.mark_span_error(str(exc), filter_span)
                LOG.exception(
                    "prompt filter %s failed for character %s; keeping prior text",
                    definition.id,
                    character.id,
                )
                return text


async def apply_prompt_filters(
    text: str,
    *,
    runtime: PromptFilterRuntime | None,
    character: Entity,
    context: PromptContext,
    epoch: int = 0,
    include_automatic: bool = True,
) -> str:
    """Apply the configured stack, or return raw compiled text when none is configured."""

    if runtime is None:
        return text
    return await runtime.apply(
        text,
        character=character,
        prompt=context,
        epoch=epoch,
        include_automatic=include_automatic,
    )


__all__ = [
    "PromptFilterContext",
    "PromptFilterDefinition",
    "PromptFilterHandler",
    "AutomaticPromptFilter",
    "PromptFilterRuntime",
    "apply_prompt_filters",
]
