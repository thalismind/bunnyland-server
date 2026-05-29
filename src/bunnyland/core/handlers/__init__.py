"""Command handlers for the core text-adventure verb surface (spec 13)."""

from .base import CommandHandler, HandlerContext, HandlerResult, ok, rejected
from .inventory import PutHandler, TakeHandler
from .movement import MoveHandler
from .speech import SayHandler, TellHandler, infer_intent

__all__ = [
    "CommandHandler",
    "HandlerContext",
    "HandlerResult",
    "MoveHandler",
    "PutHandler",
    "SayHandler",
    "TakeHandler",
    "TellHandler",
    "infer_intent",
    "ok",
    "rejected",
]
