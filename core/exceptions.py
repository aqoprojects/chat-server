from __future__ import annotations

from fastapi import status


class AppError(Exception):
    """
    Base class for all application-level exceptions.
    Carries an HTTP status code and a machine-readable error_code
    so the global handler can produce a consistent JSON response.
    """
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_server_error"

    def __init__(self, message: str = "An unexpected error occurred.") -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"

    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(message)


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"

    def __init__(self, message: str = "You do not have permission to perform this action.") -> None:
        super().__init__(message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"

    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(f"{resource} not found.")


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"

    def __init__(self, message: str = "A conflict occurred.") -> None:
        super().__init__(message)


class UnprocessableError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "unprocessable"

    def __init__(self, message: str = "The request could not be processed.") -> None:
        super().__init__(message)


class RateLimitExceededError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limit_exceeded"

    def __init__(
        self,
        message: str = "Too many requests. Please slow down.",
        retry_after: int = 60,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "bad_request"

    def __init__(self, message: str = "Bad request.") -> None:
        super().__init__(message)


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "service_unavailable"

    def __init__(self, message: str = "Service temporarily unavailable.") -> None:
        super().__init__(message)


class IdempotencyConflictError(AppError):
    """
    Raised when an idempotency key has already been used and the
    cached response is returned instead of re-processing the request.
    This is not an error — it is a normal idempotent replay.
    """
    status_code = status.HTTP_200_OK
    error_code = "idempotent_replay"

    def __init__(self, message: str = "Duplicate request — returning cached response.") -> None:
        super().__init__(message)


class TokenError(UnauthorizedError):
    """Raised for any JWT decode, expiry, or blacklist failure."""
    error_code = "token_invalid"

    def __init__(self, message: str = "Invalid or expired token.") -> None:
        super().__init__(message)


class StolenTokenError(UnauthorizedError):
    """
    Raised when a refresh token family reuse is detected.
    The entire family is revoked and the user must log in again.
    """
    error_code = "token_stolen"

    def __init__(self) -> None:
        super().__init__(
            "A security violation was detected. All sessions have been revoked. "
            "Please log in again."
        )