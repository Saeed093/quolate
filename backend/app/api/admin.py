"""Admin console API (compliance).

Separate credential pair (ADMIN_USERNAME / ADMIN_PASSWORD in .env, defaults in
config) issues a short-lived JWT with role=admin. Read-only: lists users
(email + display name, never passwords) and everything they have done —
uploaded documents, duty calculations, chat, project edits — from the
audit_events trail plus the stored artifacts themselves.
"""
from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token
from app.config import settings
from app.db.models import (
    AuditEvent,
    ChatMessage,
    Document,
    LibraryDocument,
    Project,
    User,
)
from app.db.session import get_session
from app.storage import storage

router = APIRouter(prefix="/admin", tags=["admin"])

_bearer = HTTPBearer(auto_error=False)

_ADMIN_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Admin authentication required",
    headers={"WWW-Authenticate": "Bearer"},
)

_EVENT_LIMIT = 500
_CHAT_LIMIT = 200


class AdminLoginRequest(BaseModel):
    username: str
    password: str


def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if creds is None or not creds.credentials:
        raise _ADMIN_EXC
    try:
        payload = decode_token(creds.credentials)
    except pyjwt.PyJWTError:
        raise _ADMIN_EXC
    if payload.get("role") != "admin":
        raise _ADMIN_EXC


@router.post("/login")
async def admin_login(body: AdminLoginRequest) -> dict:
    if (
        body.username != settings.admin_username
        or body.password != settings.admin_password
    ):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    now = datetime.now(timezone.utc)
    token = pyjwt.encode(
        {
            "sub": "admin",
            "role": "admin",
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(hours=settings.admin_token_expire_hours)).timestamp()
            ),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"access_token": token, "token_type": "bearer"}


async def _count_by_user(session: AsyncSession, stmt) -> dict[uuid.UUID, int]:
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


@router.get("/users", dependencies=[Depends(require_admin)])
async def admin_users(session: AsyncSession = Depends(get_session)) -> list[dict]:
    users = (await session.execute(select(User).order_by(User.created_at))).scalars().all()

    projects = await _count_by_user(
        session, select(Project.owner_id, func.count()).group_by(Project.owner_id)
    )
    documents = await _count_by_user(
        session,
        select(Project.owner_id, func.count())
        .select_from(Document)
        .join(Project, Document.project_id == Project.id)
        .group_by(Project.owner_id),
    )
    library_docs = await _count_by_user(
        session,
        select(LibraryDocument.owner_id, func.count()).group_by(
            LibraryDocument.owner_id
        ),
    )
    chats = await _count_by_user(
        session,
        select(ChatMessage.owner_id, func.count())
        .where(ChatMessage.role == "user")
        .group_by(ChatMessage.owner_id),
    )
    events = await _count_by_user(
        session, select(AuditEvent.user_id, func.count()).group_by(AuditEvent.user_id)
    )
    duty_calcs = await _count_by_user(
        session,
        select(AuditEvent.user_id, func.count())
        .where(AuditEvent.path.like("/duty-calc%"))
        .group_by(AuditEvent.user_id),
    )

    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "created_at": u.created_at,
            "counts": {
                "projects": projects.get(u.id, 0),
                "documents": documents.get(u.id, 0),
                "library_documents": library_docs.get(u.id, 0),
                "chat_messages": chats.get(u.id, 0),
                "duty_calculations": duty_calcs.get(u.id, 0),
                "audit_events": events.get(u.id, 0),
            },
        }
        for u in users
    ]


async def _get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _user_activity(session: AsyncSession, user_id: uuid.UUID) -> dict:
    user = await _get_user(session, user_id)

    events = (
        await session.execute(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(_EVENT_LIMIT)
        )
    ).scalars().all()

    projects = (
        await session.execute(
            select(Project).where(Project.owner_id == user_id).order_by(Project.created_at)
        )
    ).scalars().all()
    project_names = {p.id: p.name for p in projects}

    documents = (
        await session.execute(
            select(Document)
            .join(Project, Document.project_id == Project.id)
            .where(Project.owner_id == user_id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()

    library_docs = (
        await session.execute(
            select(LibraryDocument)
            .where(LibraryDocument.owner_id == user_id)
            .order_by(LibraryDocument.created_at.desc())
        )
    ).scalars().all()

    chat_messages = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.owner_id == user_id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.desc())
            .limit(_CHAT_LIMIT)
        )
    ).scalars().all()

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at,
        },
        "events": [
            {
                "created_at": e.created_at,
                "action": e.action,
                "method": e.method,
                "path": e.path,
                "query": e.query,
                "status_code": e.status_code,
            }
            for e in events
        ],
        "projects": [
            {
                "id": str(p.id),
                "name": p.name,
                "status": p.status,
                "created_at": p.created_at,
            }
            for p in projects
        ],
        "documents": [
            {
                "id": str(d.id),
                "filename": d.original_filename,
                "kind": d.kind,
                "status": d.status,
                "project": project_names.get(d.project_id),
                "created_at": d.created_at,
            }
            for d in documents
        ],
        "library_documents": [
            {
                "id": str(d.id),
                "filename": d.original_filename,
                "kind": d.kind,
                "status": d.status,
                "created_at": d.created_at,
            }
            for d in library_docs
        ],
        "chat_messages": [
            {"content": m.content[:500], "created_at": m.created_at}
            for m in chat_messages
        ],
    }


@router.get("/users/{user_id}/activity", dependencies=[Depends(require_admin)])
async def admin_user_activity(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    return await _user_activity(session, user_id)


@router.get(
    "/users/{user_id}/activity.csv",
    dependencies=[Depends(require_admin)],
    response_class=PlainTextResponse,
)
async def admin_user_activity_csv(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> PlainTextResponse:
    """Merged, time-sorted CSV of everything the user did — for the tax file."""
    data = await _user_activity(session, user_id)

    rows: list[tuple[datetime, str, str]] = []
    for e in data["events"]:
        detail = e["path"] + (f"?{e['query']}" if e["query"] else "")
        rows.append((e["created_at"], e["action"], f"{detail} (HTTP {e['status_code']})"))
    for d in data["documents"]:
        rows.append(
            (
                d["created_at"],
                "Uploaded quote document (stored)",
                f"{d['filename']} [{d['kind']}] project={d['project']}",
            )
        )
    for d in data["library_documents"]:
        rows.append(
            (d["created_at"], "Uploaded library document (stored)", f"{d['filename']} [{d['kind']}]")
        )
    for m in data["chat_messages"]:
        rows.append((m["created_at"], "Chat message (stored)", m["content"].replace("\n", " ")))
    rows.sort(key=lambda r: r[0], reverse=True)

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["timestamp", "user_email", "action", "detail"])
    email = data["user"]["email"]
    for when, action, detail in rows:
        writer.writerow([when.isoformat(), email, action, detail])

    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="activity-{email}.csv"'
        },
    )


def _file_response(filename: str, mime_type: str | None, data: bytes) -> Response:
    return Response(
        content=data,
        media_type=mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/documents/{doc_id}/file", dependencies=[Depends(require_admin)])
async def admin_download_document(
    doc_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    """Download a user's original uploaded project document (compliance copy)."""
    doc = (
        await session.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not await asyncio.to_thread(storage.exists, doc.storage_key):
        raise HTTPException(status_code=404, detail="Stored file is missing")
    data = await asyncio.to_thread(storage.get, doc.storage_key)
    return _file_response(doc.original_filename, doc.mime_type, data)


@router.get("/library-documents/{doc_id}/file", dependencies=[Depends(require_admin)])
async def admin_download_library_document(
    doc_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    """Download a user's original uploaded library document (compliance copy)."""
    doc = (
        await session.execute(
            select(LibraryDocument).where(LibraryDocument.id == doc_id)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not await asyncio.to_thread(storage.exists, doc.storage_key):
        raise HTTPException(status_code=404, detail="Stored file is missing")
    data = await asyncio.to_thread(storage.get, doc.storage_key)
    return _file_response(doc.original_filename, doc.mime_type, data)
