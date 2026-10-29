"""Stable public error envelope; no submitted values or exception text escapes."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict | list | None = None,
        headers: dict | None = None,
    ):
        self.status, self.code, self.message = status, code, message
        self.retryable, self.details, self.headers = retryable, details, headers


def error_response(error: APIError):
    return JSONResponse(
        status_code=error.status,
        headers=error.headers,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "details": error.details or {},
            }
        },
    )


def install_error_handlers(app: FastAPI):
    @app.middleware("http")
    async def contain_errors_and_secure_responses(request: Request, call_next):
        # Contain before Starlette's outer error middleware rethrows to ASGI server logging.
        # Diagnostics must be explicit sanitized events, never raw request/exception dumps.
        try:
            response = await call_next(request)
        except Exception:
            response = error_response(
                APIError(500, "INTERNAL_ERROR", "Request could not be completed", retryable=True)
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.app.state.settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(APIError)
    async def api_error(_request: Request, error: APIError):
        return error_response(error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        # Pydantic's input, ctx and msg can contain submitted credentials. Whitelist only locations.
        details = [
            {"field": ".".join(str(v) for v in item["loc"]), "code": item["type"]}
            for item in error.errors()
        ]
        return error_response(APIError(422, "VALIDATION_ERROR", "Invalid request", details=details))

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "UPLOAD_TOO_LARGE"}
        return error_response(
            APIError(
                error.status_code,
                codes.get(error.status_code, "BAD_REQUEST"),
                "Resource not found"
                if error.status_code == 404
                else "Request could not be processed",
            )
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        return error_response(
            APIError(500, "INTERNAL_ERROR", "Request could not be completed", retryable=True)
        )
