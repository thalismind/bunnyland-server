"""Compatibility catalogue for Bunnyland's canonically owned plugins.

New code should import a plugin from its Foundation or simpack package. This module only
preserves the historical bundled-catalogue API and contains no plugin definitions.
"""

from ..foundation.checkpoints.plugin import plugin as checkpoints_plugin
from ..foundation.core_verbs.plugin import plugin as core_verbs_plugin
from ..foundation.environment.plugin import plugin as environment_plugin
from ..foundation.history.plugin import plugin as history_plugin
from ..foundation.imagegen.plugin import plugin as imagegen_plugin
from ..foundation.mcp.plugin import plugin as mcp_plugin
from ..foundation.mechanisms.plugin import plugin as mechanisms_plugin
from ..foundation.memory.plugin import plugin as memory_plugin
from ..foundation.persona.plugin import plugin as persona_plugin
from ..foundation.policy.plugin import plugin as policy_plugin
from ..foundation.social.plugin import plugin as social_plugin
from ..foundation.storyteller.plugin import plugin as storyteller_plugin
from ..foundation.worldgen.plugin import plugin as worldgen_plugin
from ..simpacks.barbariansim.plugin import plugin as barbariansim_plugin
from ..simpacks.colonysim.plugin import plugin as colonysim_plugin
from ..simpacks.daggersim.plugin import plugin as daggersim_plugin
from ..simpacks.dinosim.plugin import plugin as dinosim_plugin
from ..simpacks.dragonsim.plugin import plugin as dragonsim_plugin
from ..simpacks.gardensim.plugin import plugin as gardensim_plugin
from ..simpacks.lifesim.plugin import plugin as lifesim_plugin
from ..simpacks.neonsim.plugin import plugin as neonsim_plugin
from ..simpacks.nukesim.plugin import plugin as nukesim_plugin
from ..simpacks.toonsim.plugin import plugin as toonsim_plugin
from ..simpacks.voidsim.plugin import plugin as voidsim_plugin
from .ids import (
    BARBARIANSIM,
    CHECKPOINTS,
    COLONYSIM,
    CORE_VERBS,
    DAGGERSIM,
    DINOSIM,
    DRAGONSIM,
    ENVIRONMENT,
    GARDENSIM,
    HISTORY,
    IMAGEGEN,
    LIFESIM,
    MCP,
    MECHANISMS,
    MEMORY,
    NEONSIM,
    NUKESIM,
    PERSONA,
    POLICY,
    SOCIAL,
    STORYTELLER,
    TOONSIM,
    VOIDSIM,
    WORLDGEN,
)
from .model import Plugin


def bunnyland_plugins() -> list[Plugin]:
    """Return bundled plugins in stable catalogue order."""
    return [
        core_verbs_plugin(),
        checkpoints_plugin(),
        lifesim_plugin(),
        memory_plugin(),
        worldgen_plugin(),
        environment_plugin(),
        mechanisms_plugin(),
        history_plugin(),
        social_plugin(),
        policy_plugin(),
        persona_plugin(),
        colonysim_plugin(),
        barbariansim_plugin(),
        gardensim_plugin(),
        dinosim_plugin(),
        toonsim_plugin(),
        dragonsim_plugin(),
        daggersim_plugin(),
        voidsim_plugin(),
        nukesim_plugin(),
        neonsim_plugin(),
        storyteller_plugin(),
        imagegen_plugin(),
        mcp_plugin(),
    ]


__all__ = [
    "BARBARIANSIM",
    "CHECKPOINTS",
    "COLONYSIM",
    "CORE_VERBS",
    "DAGGERSIM",
    "DINOSIM",
    "DRAGONSIM",
    "ENVIRONMENT",
    "GARDENSIM",
    "HISTORY",
    "IMAGEGEN",
    "LIFESIM",
    "MCP",
    "MECHANISMS",
    "MEMORY",
    "NEONSIM",
    "NUKESIM",
    "PERSONA",
    "POLICY",
    "SOCIAL",
    "STORYTELLER",
    "TOONSIM",
    "VOIDSIM",
    "WORLDGEN",
    "barbariansim_plugin",
    "bunnyland_plugins",
    "checkpoints_plugin",
    "colonysim_plugin",
    "core_verbs_plugin",
    "daggersim_plugin",
    "dinosim_plugin",
    "dragonsim_plugin",
    "environment_plugin",
    "gardensim_plugin",
    "history_plugin",
    "imagegen_plugin",
    "lifesim_plugin",
    "mcp_plugin",
    "mechanisms_plugin",
    "memory_plugin",
    "neonsim_plugin",
    "nukesim_plugin",
    "persona_plugin",
    "policy_plugin",
    "social_plugin",
    "storyteller_plugin",
    "toonsim_plugin",
    "voidsim_plugin",
    "worldgen_plugin",
]
