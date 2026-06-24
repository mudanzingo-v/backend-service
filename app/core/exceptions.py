"""
Custom exceptions and FastAPI exception handlers.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base for all app-level errors."""

    status_code: int = 500
    message: str = "Internal server error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message


class NotFoundError(AppError):
    status_code = 404
    message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    message = "Resource already exists"


class ValidationError(AppError):
    status_code = 400
    message = "Invalid request"


class UnauthorizedError(AppError):
    status_code = 401
    message = "Unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    message = "Forbidden"


class NotImplementedYetError(AppError):
    status_code = 501
    message = "Endpoint not implemented yet"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.message},
        )
