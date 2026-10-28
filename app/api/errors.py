from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


STATUS_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "FORBIDDEN",
    404: "RESOURCE_NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "DEPENDENCY_UNAVAILABLE",
}


def api_exception(status_code: int, error: str, message: str, details: list[dict[str, Any]] | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": error, "message": message, "details": details or []},
    )


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        error = str(exc.detail["error"])
        message = str(exc.detail.get("message", error))
        details = exc.detail.get("details", [])
    else:
        error = STATUS_ERROR_CODES.get(exc.status_code, "REQUEST_FAILED")
        message = str(exc.detail)
        details = []
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "success": False,
            "error": error,
            "message": message,
            "details": details,
            "request_id": _request_id(request),
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"location": ".".join(str(part) for part in error.get("loc", ())), "type": error.get("type", "validation")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": details,
            "request_id": _request_id(request),
        },
    )


async def unhandled_exception_handler(request: Request, _: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "INTERNAL_ERROR",
            "message": "The request could not be completed",
            "details": [],
            "request_id": _request_id(request),
        },
    )
