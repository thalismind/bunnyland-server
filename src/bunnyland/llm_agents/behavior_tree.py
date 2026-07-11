"""Compact behavior-tree controller (spec 7 / spec 25).

A behavior tree is ticked once per dispatch turn against the character's ``PromptContext``
and yields a single ``ToolCall`` (or ``None`` to wait). Nodes return ``SUCCESS`` or
``FAILURE``; an ``Action`` node "succeeds" only when it produces a tool call. This stays
deterministic and model-free, like ``GoalDirectedAgent`` and ``BehaviorProfileAgent``, but
composes conditions and actions explicitly so background behaviour is easy to read and
extend. Trees are referenced by name from a ``BehaviorControllerComponent`` and resolved
through the registry below.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from ..prompts.builder import PromptContext
from .agent import _command_available, _first_unlocked_exit
from .specs import BehaviorNodeSpec, BehaviorTreeSpec
from .tools import ToolCall

#: A node yields its run status and, when it chose to act, the proposed tool call.
Result = tuple["Status", ToolCall | None]


class Status(Enum):
    """The outcome of ticking a behavior-tree node."""

    SUCCESS = "success"
    FAILURE = "failure"


class Node:
    """Base class: tick the node against the current context and report a ``Result``."""

    def tick(self, context: PromptContext) -> Result:
        raise NotImplementedError


@dataclass(frozen=True)
class Condition(Node):
    """Succeeds (without acting) when its predicate holds, fails otherwise."""

    predicate: Callable[[PromptContext], bool]

    def tick(self, context: PromptContext) -> Result:
        return (Status.SUCCESS, None) if self.predicate(context) else (Status.FAILURE, None)


@dataclass(frozen=True)
class Action(Node):
    """Succeeds with a tool call when its chooser produces one; fails when it returns None."""

    chooser: Callable[[PromptContext], ToolCall | None]

    def tick(self, context: PromptContext) -> Result:
        call = self.chooser(context)
        return (Status.SUCCESS, call) if call is not None else (Status.FAILURE, None)


class Sequence(Node):
    """Runs children in order; fails if any child fails. Returns the first call produced.

    Because a character takes at most one action per turn, the sequence stops at the first
    child that yields a tool call. A sequence with no acting child fails so a parent
    ``Selector`` can try the next branch.
    """

    def __init__(self, *children: Node) -> None:
        self.children = children

    def tick(self, context: PromptContext) -> Result:
        for child in self.children:
            status, call = child.tick(context)
            if status is Status.FAILURE:
                return (Status.FAILURE, None)
            if call is not None:
                return (Status.SUCCESS, call)
        return (Status.FAILURE, None)


class Selector(Node):
    """Runs children in order; returns the first that succeeds. Fails if all fail."""

    def __init__(self, *children: Node) -> None:
        self.children = children

    def tick(self, context: PromptContext) -> Result:
        for child in self.children:
            status, call = child.tick(context)
            if status is Status.SUCCESS:
                return (Status.SUCCESS, call)
        return (Status.FAILURE, None)


@dataclass(frozen=True)
class BehaviorTree:
    """A named behavior tree. ``decide`` ticks the root and returns its chosen call."""

    name: str
    root: Node

    def decide(self, context: PromptContext) -> ToolCall | None:
        _status, call = self.root.tick(context)
        return call


class BehaviorTreeAgent:
    """Adapts a ``BehaviorTree`` to the ``CharacterAgent`` protocol."""

    def __init__(self, tree: BehaviorTree) -> None:
        self._tree = tree

    @property
    def tree(self) -> BehaviorTree:
        return self._tree

    def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ToolCall | None | Awaitable[ToolCall | None]:
        del prompt, character_id, model, provider, tools
        return self._tree.decide(context)


# -- leaf choosers ------------------------------------------------------------------------


def _take_first_item(context: PromptContext) -> ToolCall | None:
    for item in context.visible_objects:
        if _command_available(context, f"take {item}"):
            return ToolCall("take", {"item_id": item})
    return None


def _move_first_exit(context: PromptContext) -> ToolCall | None:
    direction = _first_unlocked_exit(context)
    if direction is not None and _command_available(context, f"move {direction}"):
        return ToolCall("move", {"direction": direction})
    return None


def _address_first_character(
    context: PromptContext, *, text: str, intent: str, approach: str
) -> ToolCall | None:
    if not context.visible_characters:
        return None
    if not _command_available(context, "say something to the room"):
        return None
    target = context.visible_characters[0]
    return ToolCall("say", {"text": f"{target}, {text}", "intent": intent, "approach": approach})


def _greet_first_character(context: PromptContext) -> ToolCall | None:
    return _address_first_character(
        context, text="good to see you.", intent="praise", approach="friendly"
    )


def _warn_first_character(context: PromptContext) -> ToolCall | None:
    return _address_first_character(
        context, text="keep your distance.", intent="threat", approach="cold"
    )


def _has_visible_objects(context: PromptContext) -> bool:
    return bool(context.visible_objects)


def _has_visible_characters(context: PromptContext) -> bool:
    return bool(context.visible_characters)


def _has_open_exit(context: PromptContext) -> bool:
    return _first_unlocked_exit(context) is not None


def _builtin_trees() -> dict[str, BehaviorTree]:
    return {
        # Always waits: the no-op behaviour, useful as a safe default.
        "idle": BehaviorTree("idle", Selector()),
        # Grab anything carryable, otherwise drift through the first open exit.
        "forager": BehaviorTree(
            "forager",
            Selector(
                Sequence(Condition(_has_visible_objects), Action(_take_first_item)),
                Action(_move_first_exit),
            ),
        ),
        # Roam: take the first open exit each turn, otherwise wait.
        "wanderer": BehaviorTree("wanderer", Selector(Action(_move_first_exit))),
        # Greet visitors, otherwise hold position.
        "greeter": BehaviorTree(
            "greeter",
            Selector(Sequence(Condition(_has_visible_characters), Action(_greet_first_character))),
        ),
        # Warn off visitors, otherwise hold position.
        "guard": BehaviorTree(
            "guard",
            Selector(Sequence(Condition(_has_visible_characters), Action(_warn_first_character))),
        ),
    }


BUILTIN_BEHAVIOR_TREES: dict[str, BehaviorTree] = _builtin_trees()
_REGISTRY: dict[str, BehaviorTree] = dict(BUILTIN_BEHAVIOR_TREES)


def register_behavior_tree(tree: BehaviorTree) -> None:
    """Register (or replace) a named behavior tree so controllers can reference it."""
    _REGISTRY[tree.name] = tree


def resolve_behavior_tree(name: str) -> BehaviorTree:
    """Return the named behavior tree, or raise ``ValueError`` if it is not registered."""
    tree = _REGISTRY.get(name)
    if tree is None:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"unknown behavior tree {name!r}; available: {available}")
    return tree


def behavior_tree_names() -> frozenset[str]:
    """Names of all registered behavior trees."""
    return frozenset(_REGISTRY)


# -- named leaf library -------------------------------------------------------------------
#
# Data-driven trees cannot carry Python callables, so their condition/action leaves name an
# entry in these libraries. Each entry is a factory that takes the leaf's JSON params and
# returns the predicate/chooser the node will run. Built-in entries reuse the leaf functions
# above so code-defined and data-defined trees behave identically.

#: name -> factory(params) -> predicate(context) -> bool
ConditionFactory = Callable[[Mapping[str, object]], Callable[[PromptContext], bool]]
#: name -> factory(params) -> chooser(context) -> ToolCall | None
ActionFactory = Callable[[Mapping[str, object]], Callable[[PromptContext], ToolCall | None]]


def _str_param(params: Mapping[str, object], key: str, default: str) -> str:
    value = params.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"parameter {key!r} must be a string")
    return value


def _say_action(params: Mapping[str, object]) -> Callable[[PromptContext], ToolCall | None]:
    text = params.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("'say' action requires a non-empty 'text' parameter")
    intent = _str_param(params, "intent", "praise")
    approach = _str_param(params, "approach", "friendly")

    def chooser(context: PromptContext) -> ToolCall | None:
        if not _command_available(context, "say something to the room"):
            return None
        return ToolCall("say", {"text": text, "intent": intent, "approach": approach})

    return chooser


def _address_action(default_text: str, default_intent: str, default_approach: str) -> ActionFactory:
    def factory(params: Mapping[str, object]) -> Callable[[PromptContext], ToolCall | None]:
        text = _str_param(params, "text", default_text)
        intent = _str_param(params, "intent", default_intent)
        approach = _str_param(params, "approach", default_approach)
        return lambda context: _address_first_character(
            context, text=text, intent=intent, approach=approach
        )

    return factory


CONDITION_LIBRARY: dict[str, ConditionFactory] = {
    "has_visible_objects": lambda _params: _has_visible_objects,
    "has_visible_characters": lambda _params: _has_visible_characters,
    "has_open_exit": lambda _params: _has_open_exit,
}

ACTION_LIBRARY: dict[str, ActionFactory] = {
    "take_first_item": lambda _params: _take_first_item,
    "move_first_exit": lambda _params: _move_first_exit,
    "greet_first_character": _address_action("good to see you.", "praise", "friendly"),
    "warn_first_character": _address_action("keep your distance.", "threat", "cold"),
    "say": _say_action,
}


def register_condition(name: str, factory: ConditionFactory) -> None:
    """Register (or replace) a named condition factory for data-driven behavior trees."""
    CONDITION_LIBRARY[name] = factory


def register_action(name: str, factory: ActionFactory) -> None:
    """Register (or replace) a named action factory for data-driven behavior trees."""
    ACTION_LIBRARY[name] = factory


def condition_library_names() -> frozenset[str]:
    """Names of all registered condition factories."""
    return frozenset(CONDITION_LIBRARY)


def action_library_names() -> frozenset[str]:
    """Names of all registered action factories."""
    return frozenset(ACTION_LIBRARY)


# -- compiling data into trees ------------------------------------------------------------


def _compile_node(spec: BehaviorNodeSpec) -> Node:
    if spec.kind in ("sequence", "selector"):
        if spec.ref:
            raise ValueError(f"{spec.kind!r} node must not set 'ref'")
        children = tuple(_compile_node(child) for child in spec.children)
        return Sequence(*children) if spec.kind == "sequence" else Selector(*children)

    if spec.children:
        raise ValueError(f"{spec.kind!r} leaf must not have children")
    if not spec.ref:
        raise ValueError(f"{spec.kind!r} leaf requires a 'ref'")

    if spec.kind == "condition":
        factory = CONDITION_LIBRARY.get(spec.ref)
        if factory is None:
            available = ", ".join(sorted(CONDITION_LIBRARY)) or "(none)"
            raise ValueError(f"unknown condition {spec.ref!r}; available: {available}")
        return Condition(factory(spec.params))

    factory = ACTION_LIBRARY.get(spec.ref)
    if factory is None:
        available = ", ".join(sorted(ACTION_LIBRARY)) or "(none)"
        raise ValueError(f"unknown action {spec.ref!r}; available: {available}")
    return Action(factory(spec.params))


def compile_behavior_tree(spec: BehaviorTreeSpec) -> BehaviorTree:
    """Compile a ``BehaviorTreeSpec`` into a runnable ``BehaviorTree``.

    Raises ``ValueError`` for an unknown condition/action ref, a misplaced ``ref``/children,
    or invalid leaf parameters.
    """
    return BehaviorTree(spec.name, _compile_node(spec.root))


def register_behavior_spec(spec: BehaviorTreeSpec) -> BehaviorTree:
    """Compile and register a behavior tree from its spec; returns the compiled tree."""
    tree = compile_behavior_tree(spec)
    register_behavior_tree(tree)
    return tree


__all__ = [
    "ACTION_LIBRARY",
    "BUILTIN_BEHAVIOR_TREES",
    "CONDITION_LIBRARY",
    "Action",
    "ActionFactory",
    "BehaviorTree",
    "BehaviorTreeAgent",
    "Condition",
    "ConditionFactory",
    "Node",
    "Result",
    "Selector",
    "Sequence",
    "Status",
    "action_library_names",
    "behavior_tree_names",
    "compile_behavior_tree",
    "condition_library_names",
    "register_action",
    "register_behavior_spec",
    "register_behavior_tree",
    "register_condition",
    "resolve_behavior_tree",
]
