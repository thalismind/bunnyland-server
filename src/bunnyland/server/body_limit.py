"""Request body cap enforced on the bytes actually received.

The previous check read ``Content-Length`` only. A request sent with
``Transfer-Encoding: chunked`` carries no such header, so the cap was skipped entirely and
the body was buffered in full -- the media upload route, for instance, reads the whole part
before measuring it. nginx's ``client_max_body_size`` does cover chunked bodies, so this was
edge-dependent, which is exactly the failure mode the in-app cap exists to backstop.

Implemented as pure ASGI rather than a ``BaseHTTPMiddleware`` because only the raw
``receive`` channel can count bytes as they arrive.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping

Scope = MutableMapping[str, object]
Message = MutableMapping[str, object]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class RequestBodyTooLarge(Exception):
    """Raised from the receive channel once a request body passes the cap."""


class MaxBodySizeMiddleware:
    """Reject a request as soon as its body exceeds ``max_bytes``.

    A declared ``Content-Length`` over the cap is refused before the app runs at all. Bodies
    without one are counted chunk by chunk and refused as soon as they pass it, so an
    oversized upload is never fully buffered.
    """

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return

        if self._declared_length(scope) > self.max_bytes:
            await self._reject(scope, send)
            return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body") or b""
                received += len(body)
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        async def watching_send(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, watching_send)
        except RequestBodyTooLarge:
            if response_started:
                # The handler already began replying, so there is no status left to set.
                # Let it propagate and drop the connection rather than send a torn response.
                raise
            await self._reject(scope, send)

    @staticmethod
    def _declared_length(scope: Scope) -> int:
        headers = scope.get("headers") or []
        for name, value in headers:
            if name.lower() == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return 0
        return 0

    async def _reject(self, scope: Scope, send: Send) -> None:
        body = json.dumps(
            {
                "type": "https://bunnyland.dev/problems/content_too_large",
                "title": "Content Too Large",
                "status": 413,
                "detail": "request body too large",
                "instance": scope.get("path", ""),
                "code": "content_too_large",
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = ["MaxBodySizeMiddleware", "RequestBodyTooLarge"]
