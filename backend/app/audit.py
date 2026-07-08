"""Compliance audit middleware: records what each user did into audit_events.

Recorded: every authenticated mutating request (POST/PATCH/DELETE) plus
duty-calculation GETs. Reads, status polls and admin traffic are skipped.
Recording is best-effort — it must never break or slow the actual request.
"""
from __future__ import annotations

import logging
import re
import uuid

import jwt as pyjwt
from fastapi import Request

from app.auth.security import decode_token

log = logging.getLogger("quolate.audit")

# (method, path regex) -> human-readable action label. First match wins.
_ACTION_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/projects/[^/]+/documents$"), "Uploaded quote document(s)"),
    ("POST", re.compile(r"^/library/documents$"), "Uploaded library document(s)"),
    ("DELETE", re.compile(r"^/library/documents/[^/]+$"), "Deleted library document"),
    ("POST", re.compile(r"^/library/documents/[^/]+/comments$"), "Commented on document"),
    ("POST", re.compile(r"^/projects/[^/]+/chat$"), "Chat message (project copilot)"),
    ("POST", re.compile(r"^/chat$"), "Chat message (global assistant)"),
    ("POST", re.compile(r"^/duty-calc/classify$"), "HS code classification"),
    ("POST", re.compile(r"^/duty-calc/invoice/parse$"), "Parsed invoice for duty calc"),
    ("POST", re.compile(r"^/duty-calc/invoice/calculate$"), "Calculated invoice duties"),
    ("GET", re.compile(r"^/duty-calc/[^/]+$"), "Duty calculation (single HS code)"),
    ("POST", re.compile(r"^/projects$"), "Created project"),
    ("PATCH", re.compile(r"^/projects/[^/]+$"), "Updated project"),
    ("POST", re.compile(r"^/projects/[^/]+/bom"), "Added BOM item(s)"),
    ("PATCH", re.compile(r"^/bom/[^/]+$"), "Updated BOM item"),
    ("DELETE", re.compile(r"^/bom/[^/]+$"), "Deleted BOM item"),
    ("POST", re.compile(r"^/projects/[^/]+/suppliers$"), "Added supplier"),
    ("DELETE", re.compile(r"^/suppliers/[^/]+$"), "Deleted supplier"),
    ("PATCH", re.compile(r"^/fields/[^/]+$"), "Corrected extracted field"),
    ("POST", re.compile(r"^/gpu/start$"), "Started GPU for chat"),
    ("POST", re.compile(r"^/tender-sources/[^/]+/pull"), "Pulled tenders"),
    ("POST", re.compile(r"^/projects/[^/]+/library-documents$"), "Linked library document to project"),
]

# GET paths under /duty-calc that are UI noise, not user actions.
_DUTY_NOISE = re.compile(r"^/duty-calc/(hs-codes|fx-rate|rate-prefill)")

_SKIP_PREFIXES = ("/admin", "/auth", "/health", "/status", "/activity")


def _action_label(method: str, path: str) -> str | None:
    """Return a label if this request should be audited, else None."""
    if path.startswith(_SKIP_PREFIXES):
        return None
    if method == "GET":
        if not path.startswith("/duty-calc") or _DUTY_NOISE.match(path):
            return None
    elif method not in ("POST", "PATCH", "PUT", "DELETE"):
        return None
    for m, pattern, label in _ACTION_RULES:
        if m == method and pattern.match(path):
            return label
    return f"{method} {path}"


def _user_id_from_request(request: Request) -> uuid.UUID | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = decode_token(auth[7:])
        return uuid.UUID(str(payload.get("sub")))
    except (pyjwt.PyJWTError, ValueError, TypeError):
        return None  # admin tokens (sub="admin") and bad tokens land here


async def audit_middleware(request: Request, call_next):
    response = await call_next(request)

    try:
        label = _action_label(request.method, request.url.path)
        if label is None:
            return response
        user_id = _user_id_from_request(request)
        if user_id is None:
            return response

        from app.db.models import AuditEvent
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            session.add(
                AuditEvent(
                    user_id=user_id,
                    action=label,
                    method=request.method,
                    path=request.url.path[:500],
                    query=(str(request.url.query)[:1000] or None),
                    status_code=response.status_code,
                )
            )
            await session.commit()
    except Exception:
        log.warning("audit event write failed", exc_info=True)
    return response
