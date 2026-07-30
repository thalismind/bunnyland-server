"""Tests for the request body cap.

The cap previously read Content-Length only, so a request sent with chunked transfer
encoding carried no such header, skipped the check entirely, and was buffered in full --
the media upload route reads the whole part before measuring it. nginx's
client_max_body_size does cover chunked bodies, so this was edge-dependent, which is the
exact failure mode the in-app cap exists to backstop.

Exercised at the ASGI layer because that is where the byte counting lives, and because HTTP
clients differ in when they choose chunked encoding.
"""

from __future__ import annotations

import json

import pytest

from bunnyland.server.body_limit import MaxBodySizeMiddleware, RequestBodyTooLarge


async def _echo_app(scope, receive, send):
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(len(body)).encode()})


async def _call(app, chunks, headers=None):
    remaining = list(chunks)
    sent = []

    async def receive():
        if remaining:
            return {"type": "http.request", "body": remaining.pop(0), "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app({"type": "http", "path": "/x", "headers": headers or []}, receive, send)
    return sent


def _status(sent):
    return sent[0]["status"]


async def test_body_without_content_length_is_capped_on_bytes_received():
    app = MaxBodySizeMiddleware(_echo_app, max_bytes=200)

    sent = await _call(app, [b"x" * 100] * 20)

    assert _status(sent) == 413
    problem = json.loads(sent[1]["body"])
    assert problem["code"] == "content_too_large"
    assert problem["status"] == 413


async def test_body_within_the_cap_reaches_the_application():
    app = MaxBodySizeMiddleware(_echo_app, max_bytes=200)

    sent = await _call(app, [b"x" * 50, b"x" * 50])

    assert _status(sent) == 200
    assert sent[1]["body"] == b"100"


async def test_non_request_receive_message_passes_through_unchanged():
    observed = []
    sent = []

    async def app(_scope, receive, send):
        observed.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    middleware = MaxBodySizeMiddleware(app, max_bytes=1)
    await middleware({"type": "http", "path": "/x", "headers": []}, receive, send)

    assert observed == [{"type": "http.disconnect"}]
    assert _status(sent) == 200


async def test_declared_content_length_over_the_cap_is_rejected_before_the_app_runs():
    async def never(scope, receive, send):  # pragma: no cover - must not be reached
        raise AssertionError("application should not run")

    app = MaxBodySizeMiddleware(never, max_bytes=200)

    sent = await _call(app, [b""], headers=[(b"content-length", b"5000")])

    assert _status(sent) == 413


async def test_unparsable_content_length_falls_through_to_byte_counting():
    app = MaxBodySizeMiddleware(_echo_app, max_bytes=200)

    sent = await _call(app, [b"x" * 300], headers=[(b"content-length", b"not-a-number")])

    assert _status(sent) == 413


async def test_a_zero_cap_disables_the_check():
    app = MaxBodySizeMiddleware(_echo_app, max_bytes=0)

    sent = await _call(app, [b"x" * 10_000])

    assert _status(sent) == 200


async def test_non_http_scopes_pass_straight_through():
    seen = []

    async def websocket_app(scope, receive, send):
        seen.append(scope["type"])

    app = MaxBodySizeMiddleware(websocket_app, max_bytes=1)
    await app({"type": "websocket", "headers": []}, None, None)

    assert seen == ["websocket"]


async def test_an_oversized_body_after_the_response_started_is_not_masked():
    # Once the handler has begun replying there is no status left to change, so the error
    # propagates and the connection drops rather than emitting a torn response.
    async def responds_then_reads(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while True:
            message = await receive()
            if not message.get("more_body"):
                break

    app = MaxBodySizeMiddleware(responds_then_reads, max_bytes=100)

    with pytest.raises(RequestBodyTooLarge):
        await _call(app, [b"x" * 200])
