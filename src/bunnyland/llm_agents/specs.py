"""Serializable definitions for scripted and behavioral controllers (spec 7 / spec 25).

These pydantic models are the data the script editor authors and the runtime loads. They
are deliberately decoupled from the executable forms: a ``ScriptSpec`` compiles to a tuple
of ``ToolCall``s and a ``BehaviorTreeSpec`` compiles to a ``BehaviorTree``. Behavior trees
cannot carry arbitrary code, so their leaves reference a fixed library of named conditions
and actions (see ``behavior_tree.py``) with JSON parameters.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .tools import ToolCall


class ToolCallSpec(BaseModel):
    """One verb call: the tool name plus its arguments."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    def to_tool_call(self) -> ToolCall:
        return ToolCall(name=self.name, arguments=dict(self.arguments))


class ScriptSpec(BaseModel):
    """A named, fixed sequence of verb calls replayed by a scripted controller."""

    name: str
    description: str = ""
    calls: tuple[ToolCallSpec, ...] = ()


#: The four behavior-tree node kinds (see ``behavior_tree.py``).
BehaviorNodeKind = Literal["sequence", "selector", "condition", "action"]


class BehaviorNodeSpec(BaseModel):
    """A behavior-tree node.

    ``sequence``/``selector`` nodes compose ``children``. ``condition``/``action`` leaves
    reference a named library entry by ``ref`` and pass it ``params``.
    """

    kind: BehaviorNodeKind
    ref: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    children: tuple[BehaviorNodeSpec, ...] = ()


class BehaviorTreeSpec(BaseModel):
    """A named behavior tree built from a single root node."""

    name: str
    description: str = ""
    root: BehaviorNodeSpec


__all__ = [
    "BehaviorNodeKind",
    "BehaviorNodeSpec",
    "BehaviorTreeSpec",
    "ScriptSpec",
    "ToolCallSpec",
]
