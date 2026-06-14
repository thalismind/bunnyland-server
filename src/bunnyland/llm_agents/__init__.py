"""LLM agents: the tool surface, agents that decide actions, and the dispatch loop."""

from .agent import (
    BACKGROUND_PROFILES,
    DEFAULT_MODEL,
    Agent,
    BackgroundProfile,
    BehaviorProfileAgent,
    CharacterAgent,
    GoalDirectedAgent,
    OllamaAgent,
    OpenRouterAgent,
    ProviderRouterAgent,
    ScriptedAgent,
)
from .dispatch import (
    ControllerDispatch,
    Decision,
    did_you_mean,
    name_candidates,
    persona_contradictions,
    resolve_reference,
    resolve_reference_args,
    suggest_names,
)
from .natural_language import parse_natural_command
from .tools import REFERENCE_ARG_KEYS, ToolCall, command_from_tool_call, tool_names, tool_schemas

__all__ = [
    "DEFAULT_MODEL",
    "REFERENCE_ARG_KEYS",
    "Agent",
    "BACKGROUND_PROFILES",
    "BackgroundProfile",
    "BehaviorProfileAgent",
    "CharacterAgent",
    "ControllerDispatch",
    "Decision",
    "GoalDirectedAgent",
    "OllamaAgent",
    "OpenRouterAgent",
    "ProviderRouterAgent",
    "ScriptedAgent",
    "ToolCall",
    "command_from_tool_call",
    "did_you_mean",
    "name_candidates",
    "parse_natural_command",
    "persona_contradictions",
    "resolve_reference",
    "resolve_reference_args",
    "suggest_names",
    "tool_names",
    "tool_schemas",
]
