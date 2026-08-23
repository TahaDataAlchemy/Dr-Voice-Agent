"""
Consistent JSON envelope for every API response:

    success -> {"data": <payload>, "error": null}
    failure -> {"data": null, "error": {"code": "...", "message": "...", "details": [...]}}

`install_exception_handlers` maps FastAPI/pydantic/HTTP/unexpected errors onto that envelope
with the right status codes (400 malformed JSON, 401/403, 404, 409, 422 validation, 500).
"""

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.logger.logger import LOG


def envelope(data: Any, status_code: int = status.HTTP_200_OK) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"data": jsonable_encoder(data), "error": None})


def error_envelope(
    status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": None, "error": {"code": code, "message": message, "details": details or []}},
    )


class AppError(Exception):
    """Domain error carrying an HTTP status + machine-readable code."""

    def __init__(
        self, status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, "not_found", message)


class ConflictError(AppError):
    def __init__(self, message: str):
        super().__init__(status.HTTP_409_CONFLICT, "conflict", message)


class ValidationFailed(AppError):
    """Raised by services when domain validation fails outside of pydantic (e.g. voice tools)."""

    def __init__(self, details: list[dict[str, Any]], message: str = "One or more fields are invalid"):
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", message, details)


def format_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    details = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
        msg = err.get("msg", "Invalid value")
        # pydantic prefixes custom ValueError messages with "Value error, " - strip for humans
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        details.append({"field": ".".join(loc) or None, "message": msg})
    return details


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        if any(
            e.get("type") == "json_invalid"
            or (e.get("type") == "missing" and tuple(e.get("loc", ())) == ("body",))
            for e in errors
        ):
            return error_envelope(status.HTTP_400_BAD_REQUEST, "bad_request", "Malformed or missing JSON body")
        return error_envelope(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "One or more fields are invalid",
            format_validation_errors(exc),
        )

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError):
        return error_envelope(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(HTTPException)
    async def _http_handler(_: Request, exc: HTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict"}.get(
            exc.status_code, "http_error"
        )
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        response = error_envelope(exc.status_code, code, detail)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        LOG.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return error_envelope(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "Internal server error")
