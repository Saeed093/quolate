"""embed_chat_message job: store a semantic-search vector on a chat message."""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage
from app.jobs.registry import register
from app.llm.embeddings import embed_text

log = logging.getLogger("quolate.chat")

MIN_CONTENT_CHARS = 20  # skip trivial messages ("ok", "thanks")


@register("embed_chat_message")
async def embed_chat_message(session: AsyncSession, payload: dict) -> None:
    message_id = uuid.UUID(payload["chat_message_id"])
    message = (
        await session.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    ).scalar_one_or_none()
    if message is None or message.embedding is not None:
        return
    content = (message.content or "").strip()
    if len(content) < MIN_CONTENT_CHARS:
        return
    message.embedding = await asyncio.to_thread(embed_text, content[:8000])
    await session.commit()
