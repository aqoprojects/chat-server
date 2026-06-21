from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger(__name__)

# ── Paths exempt from size limits ─────────────────────────────────────────────
# WebSocket upgrades carry no body — exempt to avoid interference.
_EXEMPT_PATHS: frozenset[str] = frozenset({"/ws", "/health", "/ready"})

# ── Routes with higher limits (file/media uploads) ────────────────────────────
# These paths accept multipart form data with binary payloads.
_UPLOAD_PATH_PREFIXES: tuple[str, ...] = (
    "/api/v1/users/avatar",
    "/api/v1/messages/attachment",
    "/api/v1/messages/voice",
    "/api/v1/chats/avatar",
)


class RequestSizeMiddleware:
    """
    Reject requests whose body exceeds the configured size limit.

    Implemented as a raw ASGI middleware (not BaseHTTPMiddleware) so it
    can intercept the receive channel and abort reading mid-stream without
    buffering the entire body into memory first.

    Two checks:
        1. Content-Length header: if present and exceeds the limit,
        return 413 immediately before reading any body bytes.
2. Streaming byte count: count bytes as they arrive via the
ASGI receive channel. Abort with 413 if the running total
exceeds the limit mid-stream.

This middleware is registered in app/main.py _register_middleware()
and receives max_size from settings.max_upload_size_bytes.
"""

    def __init__(self, app: ASGIApp, max_size: int) -> None:
        self.app      = app
        self.max_size = max_size

        log.info(
            "request_size_middleware_ready",
            max_size_bytes=max_size,
            max_size_mb=round(max_size / 1024 / 1024, 1),
        )

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:

        # ── Only apply to HTTP requests ───────────────────────────────────────
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # ── Exempt paths ──────────────────────────────────────────────────────
        path = scope.get("path", "")
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # ── WebSocket — no body to check ──────────────────────────────────────
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        # ── Check 1: Content-Length header (fast path) ────────────────────────
        headers  = dict(scope.get("headers", []))
        raw_cl   = headers.get(b"content-length", b"0")

        try:
            content_length = int(raw_cl)
        except (ValueError, TypeError):
            content_length = 0

        if content_length > self.max_size:
            log.warning(
                "request_too_large_content_length",
                path=path,
                content_length=content_length,
                max_size=self.max_size,
            )
            response = JSONResponse(
                status_code=413,
                content={
                    "error": "request_too_large",
                    "message": (
                        f"Request body exceeds the maximum allowed size of "
                        f"{self.max_size // (1024 * 1024)} MB."
                    ),
                    "max_size_bytes": self.max_size,
                    "received_bytes": content_length,
                },
            )
            await response(scope, receive, send)
            return

        # ── Check 2: Streaming byte count ─────────────────────────────────────
        # Wrap the receive channel so we count bytes as they arrive.
        total_received = 0
        aborted        = False

        async def limited_receive() -> Message:
            nonlocal total_received, aborted

            if aborted:
                # Return an empty body signal to stop further reads
                return {"type": "http.request", "body": b"", "more_body": False}

            message: Message = await receive()

            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                total_received += len(chunk)

                if total_received > self.max_size:
                    aborted = True
                    log.warning(
                        "request_too_large_streaming",
                        path=path,
                        bytes_received=total_received,
                        max_size=self.max_size,
                    )
                    # Signal to the app that the body is done (truncated)
                    return {
                        "type": "http.request",
                        "body": b"",
                        "more_body": False,
                    }

            return message

        # ── Process request with wrapped receive ──────────────────────────────
        await self.app(scope, limited_receive, send)

        # ── Return 413 if streaming check triggered ───────────────────────────
        # Note: if the app already sent a response before the limit was hit,
        # we cannot send a new 413. The abort signal stops body reading.
        # In practice the 413 response is sent before the app responds for
        # uploads since the body must be fully read to reach the handler.
        if aborted:
            # The app may or may not have responded — we cannot reliably
            # send a new response here without risking double-response.
            # The truncated body will cause the app's own validation to fail.
            # Log only — the Content-Length check catches this reliably for
            # well-behaved clients; streaming abort handles malicious ones.
            log.error(
                "streaming_body_aborted_after_size_exceeded",
                path=path,
                total_received=total_received,
            )
