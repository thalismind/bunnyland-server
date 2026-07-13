"""Command handlers for the core text-adventure verb surface (spec 13)."""

from .base import (
    CommandHandler,
    HandlerContext,
    HandlerResult,
    planned,
    rejected,
    require_character,
    require_entity,
    require_reachable_entity,
)
from .interaction import (
    CloseHandler,
    InspectHandler,
    LockHandler,
    LookHandler,
    OpenHandler,
    UnlockHandler,
    UseHandler,
    WriteHandler,
)
from .inventory import (
    DropHandler,
    HoldHandler,
    PutHandler,
    RemoveHandler,
    TakeHandler,
    UnholdHandler,
    WearHandler,
)
from .lifecycle import SleepHandler, WaitHandler, WakeHandler
from .movement import MoveHandler
from .speech import (
    ConversationLineHandler,
    EndConversationHandler,
    SayHandler,
    StartConversationHandler,
    TellHandler,
    infer_intent,
)

__all__ = [
    "CommandHandler",
    "ConversationLineHandler",
    "CloseHandler",
    "DropHandler",
    "EndConversationHandler",
    "HandlerContext",
    "HandlerResult",
    "HoldHandler",
    "InspectHandler",
    "LockHandler",
    "LookHandler",
    "MoveHandler",
    "OpenHandler",
    "PutHandler",
    "RemoveHandler",
    "SayHandler",
    "SleepHandler",
    "StartConversationHandler",
    "TakeHandler",
    "TellHandler",
    "UnholdHandler",
    "UnlockHandler",
    "UseHandler",
    "WaitHandler",
    "WakeHandler",
    "WearHandler",
    "WriteHandler",
    "infer_intent",
    "planned",
    "rejected",
    "require_character",
    "require_entity",
    "require_reachable_entity",
]
