"""Command handlers for the core text-adventure verb surface (spec 13)."""

from .base import CommandHandler, HandlerContext, HandlerResult, ok, rejected
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
from .speech import SayHandler, TellHandler, infer_intent

__all__ = [
    "CommandHandler",
    "CloseHandler",
    "DropHandler",
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
    "ok",
    "rejected",
]
