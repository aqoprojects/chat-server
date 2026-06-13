from __future__ import annotations

import uuid
import structlog

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

log = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_MAX_CLIENT_ID_LENGTH = 128   # guard against header-stuffing


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique request ID to every incoming HTTP request.

    Processing order:
        1. Read X-Request-ID from client headers (if present and valid).
        2. If absent or invalid, generate a new UUID4.
        3. Clear any leftover structlog context from a previous request
        on this worker (critical in async workers that reuse coroutines).
        4. Bind request_id, path, and method to structlog contextvars
        so every log call during this request carries these fields
        automatically.
        5. Call the next middleware / route handler.
        6. Attach X-Request-ID to the response so clients can correlate.
        7. Clear structlog contextvars after the response (cleanup).

        Why clear before AND after:
            Starlette runs middleware in an async context. A worker coroutine
            can be reused across requests. If we only cleared after, a crash
            before cleanup would bleed context into the next request on that
            worker. Clearing before the bind guarantees a clean slate.
            """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: any) -> Response:  # type: ignore[override]
        # ── 1. Resolve request ID ─────────────────────────────────────────────
        request_id = self._resolve_request_id(request)

        # ── 2. Bind to structlog context (async-safe contextvars) ─────────────
        # clear_contextvars() wipes ALL previously bound context on this
        # task — mandatory before binding new request context.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
        )

        # ── 3. Process request ────────────────────────────────────────────────
        try:
            response: Response = await call_next(request)
        except Exception:
            log.exception("unhandled_request_error", request_id=request_id)
            raise
        finally:
            # ── 4. Clean up context regardless of success or failure ──────────
            structlog.contextvars.clear_contextvars()

        # ── 5. Echo request ID back to client ─────────────────────────────────
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _resolve_request_id(request: Request) -> str:
        """
        Return the client-supplied X-Request-ID if it is a valid UUID,
        otherwise generate a new UUID4.

        Validation rules:
            - Must be present in the header.
            - Must be ≤ 128 characters (prevents header-stuffing).
            - Must parse as a valid UUID (prevents injection).

            If the client sends an invalid ID we generate a fresh one and
            do NOT raise an error — this is transparent to the caller.
            """
        client_id = request.headers.get(REQUEST_ID_HEADER, "").strip()

        if client_id and len(client_id) <= _MAX_CLIENT_ID_LENGTH:
            try:
                # Normalise to lowercase hyphenated form
                return str(uuid.UUID(client_id))
            except ValueError:
                pass  # fall through to generate

            return str(uuid.uuid4())