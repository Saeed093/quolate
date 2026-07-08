"""Plain-text error log for the backend: backend/logs/errors.log.

Every failed request (4xx/5xx) and unhandled exception is appended with what
the user was doing (method + path), the error detail, and a heuristic
"possible issue" hint. Python warnings/errors from any module logger land in
the same file via a root-logger handler.
"""
from __future__ import annotations

import logging
import logging.handlers
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_FILE = LOG_DIR / "errors.log"

log = logging.getLogger("quolate.errors")


def setup_error_file_logging() -> None:
    """Attach a rotating file handler for WARNING+ records to the root logger."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_quolate_error_file", False):
            return  # already configured (uvicorn reload / tests)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler._quolate_error_file = True  # type: ignore[attr-defined]
    handler.setLevel(logging.WARNING)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    if root.level > logging.WARNING or root.level == logging.NOTSET:
        root.setLevel(logging.WARNING)


def _possible_issue(status: int, path: str, detail: str, exc: BaseException | None) -> str:
    """Best-effort diagnosis so the log reads like a support note."""
    text = f"{detail} {exc!r}".lower() if exc else detail.lower()
    if "ollama" in text or "11434" in text:
        return "Ollama is unreachable or the model is not loaded — check 'ollama serve' / Start GPU."
    if status == 503 and ("gpu" in text or path.endswith("/chat") or "/gpu/" in path):
        return "Chat requires the model fully on GPU — click 'Start GPU' or free up VRAM."
    if status == 409 and "gpu" in text:
        return "No GPU installed on this machine; GPU-only chat cannot be enabled."
    if status in (401, 403):
        return "Not logged in or the session token expired — log in again."
    if status == 422:
        return "The submitted form/request data was invalid — see detail above."
    if status == 404:
        return "The requested item does not exist or belongs to another user."
    if exc is not None and any(
        k in text for k in ("psycopg", "sqlalchemy", "connection refused", "5433")
    ):
        return "Database problem — is the Postgres docker container running (docker compose up -d)?"
    if status >= 500:
        return "Unexpected server error — see traceback above."
    return "See detail above."


def _write_entry(
    request: Request,
    status: int,
    detail: str,
    exc: BaseException | None = None,
) -> None:
    action = f"{request.method} {request.url.path}"
    lines = [
        f"user action:    {action} -> HTTP {status}",
        f"detail:         {detail[:2000]}",
        f"possible issue: {_possible_issue(status, request.url.path, detail, exc)}",
    ]
    if exc is not None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        lines.append("traceback:\n" + tb.rstrip())
    message = "\n".join(lines)
    log.error(message) if status >= 500 else log.warning(message)


def register_error_handlers(app: FastAPI) -> None:
    """Log every HTTP error / validation error / crash, then respond as usual."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc_handler(request: Request, exc: StarletteHTTPException):
        _write_entry(request, exc.status_code, str(exc.detail))
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": jsonable_encoder(exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc_handler(request: Request, exc: RequestValidationError):
        _write_entry(request, 422, str(exc.errors()))
        return JSONResponse(
            status_code=422, content={"detail": jsonable_encoder(exc.errors())}
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc_handler(request: Request, exc: Exception):
        _write_entry(request, 500, str(exc), exc)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )
