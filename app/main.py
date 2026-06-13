from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from core.config import settings
# from core.logging.setup import configure_logging

# ── Routers (imported here; files are empty stubs until their phase) ──────────
from app.api.v1 import (
    auth,
    users,
    interests,
    follows,
    posts,
    replies,
    likes,
    chats,
    messages,
    notifications,
)
from app.ws.router import ws_router
# from app.middleware.request_id import RequestIDMiddleware
# from app.middleware.request_size import RequestSizeMiddleware
# from app.middleware.security_headers import SecurityHeadersMiddleware
# from app.middleware.csrf import CSRFMiddleware
from app.lifespan import lifespan


# ══════════════════════════════════════════════════════════════════════════════
#  App factory
# ══════════════════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    """
    Construct and return a fully configured FastAPI application instance.

    Called once at process startup (by uvicorn via the module-level `app`
    object at the bottom of this file) and once per test session (by the
    pytest fixture in tests/conftest.py).
    """

    # ── 1. Configure structlog before anything else logs ─────────────────────
    # configure_logging()

    # ── 2. Instantiate FastAPI ────────────────────────────────────────────────
    application = FastAPI(
        title="Chat Server API",
        description="High-throughput real-time chat server.",
        version="1.0.0",
        # /docs and /redoc are only reachable in non-production environments.
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        # Attach the lifespan context manager (startup + shutdown hooks).
        # Defined in app/lifespan.py — see Topic 2.
        lifespan=lifespan,
        # Use orjson for faster JSON serialization throughout.
        default_response_class=_get_default_response_class(),
    )

    # ── 3. Register middleware (bottom = outermost, processed first) ──────────
    _register_middleware(application)

    # ── 4. Mount versioned API routers ───────────────────────────────────────
    _register_routers(application)

    # ── 5. Register global exception handlers ─────────────────────────────────
    _register_exception_handlers(application)

    return application


# ══════════════════════════════════════════════════════════════════════════════
#  Middleware registration
# ══════════════════════════════════════════════════════════════════════════════

def _register_middleware(app: FastAPI) -> None:
    """
    Register all middleware onto the application.

    Starlette processes middleware in LIFO order relative to how they are
    added here — the LAST add_middleware call below is the FIRST middleware
    a request passes through on the way in, and the LAST on the way out.

    Intended processing order (outermost → innermost):
        1. TrustedHostMiddleware   — reject requests with bad Host headers
        # 2. SecurityHeadersMiddleware — add HSTS, CSP, X-Frame-Options, etc.
        # 3. RequestIDMiddleware     — assign X-Request-ID, bind to log context
        # 4. RequestSizeMiddleware   — reject oversized request bodies early
        # 5. CSRFMiddleware          — validate CSRF double-submit token
        6. CORSMiddleware          — handle preflight and CORS headers

    Because Starlette reverses the order, we register them in reverse below.
    """

    # 6 — CORSMiddleware (registered first = innermost = processed last)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.cors_origins],
        allow_credentials=True,          # required for cookie-based auth
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            settings.csrf_header_name,   # "X-CSRFToken" — must be explicitly allowed
        ],
        expose_headers=[
            "X-Request-ID",              # clients can read this for tracing
        ],
        max_age=600,                     # preflight cache: 10 minutes
    )

    # 5 — CSRFMiddleware (custom — implemented in Stage 7)
    # app.add_middleware(CSRFMiddleware)

    # 4 — RequestSizeMiddleware (custom — implemented in Stage 7)
    # app.add_middleware(
    #     # RequestSizeMiddleware,
    #     max_size=settings.max_upload_size_bytes,
    # )

    # 3 — RequestIDMiddleware (custom — implemented in Stage 4)
    # app.add_middleware(RequestIDMiddleware)

    # 2 — SecurityHeadersMiddleware (custom — implemented in Stage 7)
    # app.add_middleware(SecurityHeadersMiddleware)

    # 1 — TrustedHostMiddleware (outermost — registered last)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Router registration
# ══════════════════════════════════════════════════════════════════════════════

def _register_routers(app: FastAPI) -> None:
    """
    Mount all domain routers under /api/v1 and the WebSocket router
    directly at the root (WebSocket endpoints do not carry the REST prefix).

    Each router is defined in its own file and imported at the top of
    this module. When a new domain is added, only two lines change:
    the import above and one include_router call here.
    """

    API_PREFIX = "/api/v1"

    # ── REST routers ──────────────────────────────────────────────────────────
    app.include_router(
        auth.router,
        prefix=f"{API_PREFIX}/auth",
        tags=["auth"],
    )
    app.include_router(
        users.router,
        prefix=f"{API_PREFIX}/users",
        tags=["users"],
    )
    app.include_router(
        interests.router,
        prefix=f"{API_PREFIX}/interests",
        tags=["interests"],
    )
    app.include_router(
        follows.router,
        prefix=f"{API_PREFIX}/follows",
        tags=["follows"],
    )
    app.include_router(
        posts.router,
        prefix=f"{API_PREFIX}/posts",
        tags=["posts"],
    )
    app.include_router(
        replies.router,
        prefix=f"{API_PREFIX}/replies",
        tags=["replies"],
    )
    app.include_router(
        likes.router,
        prefix=f"{API_PREFIX}/likes",
        tags=["likes"],
    )
    app.include_router(
        chats.router,
        prefix=f"{API_PREFIX}/chats",
        tags=["chats"],
    )
    app.include_router(
        messages.router,
        prefix=f"{API_PREFIX}/messages",
        tags=["messages"],
    )
    app.include_router(
        notifications.router,
        prefix=f"{API_PREFIX}/notifications",
        tags=["notifications"],
    )

    # ── WebSocket router ──────────────────────────────────────────────────────
    # Mounted at root — the full path becomes /ws
    app.include_router(ws_router)

    # ── Internal / ops endpoints ──────────────────────────────────────────────
    _register_health_endpoints(app)


def _register_health_endpoints(app: FastAPI) -> None:
    """
    /health — liveness probe (process alive check, no dependencies).
    /ready  — readiness probe (all dependency checks with latency).
    """
    import time
    from fastapi import status
    from fastapi.responses import ORJSONResponse

    # ── /health — liveness ────────────────────────────────────────────────────
    @app.get(
        "/health",
        tags=["ops"],
        summary="Liveness probe",
        description=(
            "Returns 200 as long as the Python process is running. "
            "Does not check database or Redis. "
            "Used by Kubernetes liveness probe."
        ),
        include_in_schema=not settings.is_production,
        response_model=None,
    )
    async def health_check() -> ORJSONResponse:
        return ORJSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ok",
            "env": settings.app_env,
        },
        )

    # ── /ready — readiness ────────────────────────────────────────────────────
    @app.get(
        "/ready",
        tags=["ops"],
        summary="Readiness probe",
        description=(
            "Checks PostgreSQL and Redis connectivity. "
            "Returns 200 only when all dependencies are reachable. "
            "Returns 503 if any dependency is down. "
            "Includes per-dependency latency in milliseconds. "
            "Used by Kubernetes readiness probe."
        ),
        include_in_schema=not settings.is_production,
        response_model=None,
    )
    
    async def readiness_check() -> ORJSONResponse:
        from app.checks import check_db, check_redis

        # Run both checks concurrently — no point waiting for DB
        # if Redis is already failing or vice versa.
        import asyncio
        db_result, redis_result = await asyncio.gather(
            check_db(),
            check_redis(),
            return_exceptions=False,
        )

        all_ok: bool = db_result["ok"] and redis_result["ok"]

        response_body = {
            "status": "ready" if all_ok else "not_ready",
            "env": settings.app_env,
            "checks": {
                "postgres": {
                    "status": "ok" if db_result["ok"] else "fail",
                    "latency_ms": db_result["latency_ms"],
                    "detail": db_result["detail"],
                },
                "redis": {
                    "status": "ok" if redis_result["ok"] else "fail",
                    "latency_ms": redis_result["latency_ms"],
                    "detail": redis_result["detail"],
                },
            },
        }

        return ORJSONResponse(
        status_code=(
            status.HTTP_200_OK
            if all_ok
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=response_body,
        )

# ══════════════════════════════════════════════════════════════════════════════
#  Exception handlers
# ══════════════════════════════════════════════════════════════════════════════

def _register_exception_handlers(app: FastAPI) -> None:
    """
    Register global exception handlers.
    These catch unhandled exceptions and return structured JSON error
    responses instead of FastAPI's default plain-text 500 page.
    Custom exception classes are defined in core/exceptions.py (Stage 7).
    """
    from fastapi import Request, status
    from fastapi.responses import ORJSONResponse
    from fastapi.exceptions import RequestValidationError
    from core.exceptions import (
        AppError,
        RateLimitExceededError,
        NotFoundError,
        ForbiddenError,
        UnauthorizedError,
        ConflictError,
    )
    import structlog

    log = structlog.get_logger(__name__)

    # ── Pydantic validation errors (422) ──────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "validation_error",
                "message": "One or more fields failed validation.",
                "details": exc.errors(),
            },
        )

    # ── Domain-specific app errors ────────────────────────────────────────────
    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_handler(
        request: Request, exc: RateLimitExceededError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": "rate_limit_exceeded", "message": str(exc)},
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(UnauthorizedError)
    async def unauthorized_handler(
        request: Request, exc: UnauthorizedError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "unauthorized", "message": str(exc)},
        )

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(
        request: Request, exc: ForbiddenError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "forbidden", "message": str(exc)},
        )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(
        request: Request, exc: NotFoundError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "message": str(exc)},
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(
        request: Request, exc: ConflictError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "conflict", "message": str(exc)},
        )

    @app.exception_handler(AppError)
    async def app_error_handler(
        request: Request, exc: AppError
    ) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error_code, "message": str(exc)},
        )

    # ── Catch-all unhandled exceptions (500) ──────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> ORJSONResponse:
        log.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exc_type=type(exc).__name__,
            exc=str(exc),
        )
        return ORJSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred.",
            },
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_default_response_class() -> type:
    """
    Use ORJSONResponse as the default response class for all endpoints.
    orjson is significantly faster than the stdlib json module for
    serializing large payloads (message lists, user feeds, etc.).
    """
    from fastapi.responses import ORJSONResponse
    return ORJSONResponse


# ══════════════════════════════════════════════════════════════════════════════
#  Stub router files — minimal content until their phase
# ══════════════════════════════════════════════════════════════════════════════
#
#  Each of the files below currently contains only a bare APIRouter()
#  instance so this factory can import them without errors.
#  They are filled in during Phases 3–6.
#
#  app/api/v1/auth.py          →  router = APIRouter()
#  app/api/v1/users.py         →  router = APIRouter()
#  app/api/v1/interests.py     →  router = APIRouter()
#  app/api/v1/follows.py       →  router = APIRouter()
#  app/api/v1/posts.py         →  router = APIRouter()
#  app/api/v1/replies.py       →  router = APIRouter()
#  app/api/v1/likes.py         →  router = APIRouter()
#  app/api/v1/chats.py         →  router = APIRouter()
#  app/api/v1/messages.py      →  router = APIRouter()
#  app/api/v1/notifications.py →  router = APIRouter()
#  app/ws/router.py            →  ws_router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════════
#  Module-level application instance
# ══════════════════════════════════════════════════════════════════════════════

# This is the object uvicorn points at:
#   uvicorn app.main:app --reload
#
# Tests do NOT import this directly — they call create_app() themselves
# so they get a fresh instance with overridden dependencies.
app: FastAPI = create_app()