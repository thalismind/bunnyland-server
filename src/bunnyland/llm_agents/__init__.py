"""LLM agents: the tool surface, agents that decide actions, and the dispatch loop."""

from .agent import DEFAULT_MODEL, Agent, OllamaAgent, ScriptedAgent
from .dispatch import (
    ControllerDispatch,
    Decision,
    did_you_mean,
    name_candidates,
    resolve_reference,
    resolve_reference_args,
    suggest_names,
)
from .tools import REFERENCE_ARG_KEYS, ToolCall, command_from_tool_call, tool_names, tool_schemas

__all__ = [
    "DEFAULT_MODEL",
    "REFERENCE_ARG_KEYS",
    "Agent",
    "ControllerDispatch",
    "Decision",
    "OllamaAgent",
    "ScriptedAgent",
    "ToolCall",
    "command_from_tool_call",
    "did_you_mean",
    "name_candidates",
    "resolve_reference",
    "resolve_reference_args",
    "suggest_names",
    "tool_names",
    "tool_schemas",
]
