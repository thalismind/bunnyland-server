"""Command handlers for the core text-adventure verb surface (spec 13)."""

from .base import CommandHandler, HandlerContext, HandlerResult, ok, rejected
from .interaction import UseHandler, WriteHandler
from .inventory import PutHandler, TakeHandler
from .lifecycle import SleepHandler, WaitHandler, WakeHandler
from .movement import MoveHandler
from .speech import SayHandler, TellHandler, infer_intent

__all__ = [
    "CommandHandler",
    "HandlerContext",
    "HandlerResult",
    "MoveHandler",
    "PutHandler",
    "SayHandler",
    "SleepHandler",
    "TakeHandler",
    "TellHandler",
    "UseHandler",
    "WaitHandler",
    "WakeHandler",
    "WriteHandler",
    "infer_intent",
    "ok",
    "rejected",
]
