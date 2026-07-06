"""Chat router: server-side tool loop streamed over SSE.

Two surfaces:
  - /projects/{project_id}/chat — project workbench copilot (matrix tools etc.)
  - /chat                       — global assistant over the user's whole database
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project
from app.auth.deps import get_current_user
from app.chat.loop import run_chat_stream
from app.chat.tools import ChatContext
from app.db.models import ChatMessage, Project, User
from app.db.session import get_session
from app.jobs import queue
from app.schemas import ChatRequest, ChatMessageOut

router = APIRouter(tags=["chat"])

_HISTORY_LIMIT = 20


async def _save_message(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    project_id: uuid.UUID | None,
    role: str,
    content: str,
    tool_calls: dict | None = None,
) -> None:
    """Save a chat message and queue its RAG embedding."""
    message = ChatMessage(
        project_id=project_id,
        owner_id=owner_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
    )
    session.add(message)
    await session.flush()
    await queue.enqueue(
        session, "embed_chat_message", {"chat_message_id": str(message.id)}
    )
    await session.commit()


async def _load_history(
    session: AsyncSession, owner_id: uuid.UUID, project_id: uuid.UUID | None
) -> list[dict]:
    stmt = select(ChatMessage).where(ChatMessage.owner_id == owner_id)
    if project_id is None:
        stmt = stmt.where(ChatMessage.project_id.is_(None))
    else:
        stmt = stmt.where(ChatMessage.project_id == project_id)
    rows = (
        await session.execute(
            stmt.order_by(ChatMessage.created_at.desc()).limit(_HISTORY_LIMIT)
        )
    ).scalars().all()
    return [
        {"role": m.role, "content": m.content}
        for m in reversed(rows)
        if m.role in ("user", "assistant")
    ]


def _chat_response(
    session: AsyncSession,
    ctx: ChatContext,
    history: list[dict],
    message: str,
    *,
    owner_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> StreamingResponse:
    async def event_stream():
        final_content = ""
        tool_calls: list[dict] = []
        async for event in run_chat_stream(ctx, history, message):
            if event["type"] == "final":
                final_content = event.get("content", "")
                tool_calls = event.get("tool_calls", [])
            yield f"data: {json.dumps(event, default=str)}\n\n"

        await _save_message(
            session,
            owner_id=owner_id,
            project_id=project_id,
            role="assistant",
            content=final_content,
            tool_calls={"calls": tool_calls} if tool_calls else None,
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------- Project-scoped chat ----------
@router.get("/projects/{project_id}/chat", response_model=list[ChatMessageOut])
async def get_chat_history(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessage]:
    await get_owned_project(project_id, user, session)
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.project_id == project_id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()
    return list(rows)


@router.post("/projects/{project_id}/chat")
async def post_chat(
    project_id: uuid.UUID,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    project = await get_owned_project(project_id, user, session)

    history = await _load_history(session, user.id, project_id)
    await _save_message(
        session,
        owner_id=user.id,
        project_id=project_id,
        role="user",
        content=body.message,
    )

    ctx = ChatContext(
        session=session,
        project=project,
        user=user,
        currency=body.currency,
        overrides=body.overrides or {},
    )
    return _chat_response(
        session, ctx, history, body.message, owner_id=user.id, project_id=project_id
    )


# ---------- Global assistant chat (whole database, no project) ----------
@router.get("/chat", response_model=list[ChatMessageOut])
async def get_global_chat_history(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessage]:
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.owner_id == user.id,
                ChatMessage.project_id.is_(None),
            )
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()
    return list(rows)


@router.post("/chat")
async def post_global_chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    history = await _load_history(session, user.id, None)
    await _save_message(
        session,
        owner_id=user.id,
        project_id=None,
        role="user",
        content=body.message,
    )

    ctx = ChatContext(
        session=session,
        project=None,
        user=user,
        currency=body.currency,
        overrides=body.overrides or {},
    )
    return _chat_response(
        session, ctx, history, body.message, owner_id=user.id, project_id=None
    )
