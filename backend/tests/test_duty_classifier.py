"""HS code auto-classification: classifier core, endpoint, and chat tools.

LLM calls are mocked via `queue_responses` (see `app/llm/mock.py`) -- no real
network calls happen in this module.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.chat.tools import ChatContext, _tool_calculate_duty, _tool_classify_hs_code
from app.db.models import User
from app.db.session import SessionLocal
from app.duty.classifier import ClassificationInputError, classify_hs_code
from app.llm.json_enforce import SchemaEnforceError
from app.llm.mock import queue_responses
from tests.test_duty_engine import MOBILE, _AS_OF, _seed_common, _seed_mobile

_VALID_RESPONSE = json.dumps(
    {
        "product_summary": "Android smartphone, 6GB RAM",
        "candidates": [
            {
                "hs_code": MOBILE,
                "description": "Smartphones and other cellular phones",
                "confidence": 0.92,
                "reasoning": "Matches known ingested code for mobile handsets.",
            },
            {
                "hs_code": "8517.13.00",
                "description": "Smartphones (alternate heading)",
                "confidence": 0.3,
                "reasoning": "Less likely alternate classification.",
            },
        ],
    }
)


async def _get_user(email: str = "user@example.com") -> User:
    async with SessionLocal() as session:
        return (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one()


# ---------- classify_hs_code() from raw text ----------
def test_classify_from_text_parses_ranked_candidates():
    queue_responses(_VALID_RESPONSE)

    async def _run():
        async with SessionLocal() as session:
            return await classify_hs_code(
                session, text="A 6.5-inch android smartphone with 6GB RAM and dual SIM."
            )

    result = asyncio.run(_run())
    assert result.product_summary == "Android smartphone, 6GB RAM"
    assert len(result.candidates) == 2
    assert result.candidates[0].hs_code == MOBILE
    assert result.candidates[0].confidence == pytest.approx(0.92)
    assert result.disclaimer


def test_classify_requires_text_or_document():
    async def _run():
        async with SessionLocal() as session:
            await classify_hs_code(session)

    with pytest.raises(ClassificationInputError):
        asyncio.run(_run())


# ---------- classify_hs_code() from a library document ----------
def test_classify_from_library_document_reextracts_text_and_classifies(auth_client):
    resp = auth_client.post(
        "/library/documents",
        files=[
            (
                "files",
                (
                    "spec.txt",
                    b"Product: Android smartphone, 6.5in display, 6GB RAM, dual SIM.",
                    "text/plain",
                ),
            )
        ],
    )
    doc_id = resp.json()["created"][0]["id"]

    queue_responses(_VALID_RESPONSE)

    async def _run():
        user = await _get_user()
        async with SessionLocal() as session:
            return await classify_hs_code(
                session,
                library_document_id=uuid.UUID(doc_id),
                owner_id=user.id,
            )

    result = asyncio.run(_run())
    assert result.candidates[0].hs_code == MOBILE


def test_classify_from_document_scopes_by_owner(auth_client):
    resp = auth_client.post(
        "/library/documents",
        files=[("files", ("spec.txt", b"A widget", "text/plain"))],
    )
    doc_id = resp.json()["created"][0]["id"]

    async def _run():
        async with SessionLocal() as session:
            await classify_hs_code(
                session,
                library_document_id=uuid.UUID(doc_id),
                owner_id=uuid.uuid4(),  # not the actual owner
            )

    with pytest.raises(ClassificationInputError):
        asyncio.run(_run())


def test_classify_document_requires_owner_id():
    async def _run():
        async with SessionLocal() as session:
            await classify_hs_code(session, library_document_id=uuid.uuid4())

    with pytest.raises(ClassificationInputError):
        asyncio.run(_run())


# ---------- Malformed LLM JSON ----------
def test_classify_malformed_json_raises_clean_error_not_crash():
    queue_responses("not json at all, sorry", "still not json")

    async def _run():
        async with SessionLocal() as session:
            await classify_hs_code(session, text="some product")

    with pytest.raises(SchemaEnforceError):
        asyncio.run(_run())


# ---------- POST /duty-calc/classify ----------
def test_classify_endpoint_success(auth_client):
    queue_responses(_VALID_RESPONSE)
    resp = auth_client.post("/duty-calc/classify", json={"text": "an android smartphone"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"][0]["hs_code"] == MOBILE
    assert body["disclaimer"]


def test_classify_endpoint_requires_exactly_one_of_text_or_document(auth_client):
    resp = auth_client.post("/duty-calc/classify", json={})
    assert resp.status_code == 422

    resp2 = auth_client.post(
        "/duty-calc/classify",
        json={"text": "a phone", "library_document_id": str(uuid.uuid4())},
    )
    assert resp2.status_code == 422


def test_classify_endpoint_requires_auth(client):
    resp = client.post("/duty-calc/classify", json={"text": "a phone"})
    assert resp.status_code == 401


def test_classify_endpoint_malformed_llm_output_returns_502(auth_client):
    queue_responses("garbage", "still garbage")
    resp = auth_client.post("/duty-calc/classify", json={"text": "a phone"})
    assert resp.status_code == 502


# ---------- Chat tools: calculate_duty + classify_hs_code ----------
def test_chat_tool_calculate_duty_returns_full_breakdown(auth_client):
    async def _run():
        async with SessionLocal() as session:
            await _seed_common(session)
            await _seed_mobile(session)
            await session.commit()
            user = await _get_user()
            ctx = ChatContext(session=session, project=None, user=user)
            return await _tool_calculate_duty(
                ctx,
                hs_code=MOBILE,
                declared_value_usd=1000,
                exchange_rate=280,
                importer_category="commercial_importer",
                atl_status="atl",
                as_of_date=_AS_OF.isoformat(),
            )

    result = asyncio.run(_run())
    assert result["hs_code"] == MOBILE
    assert Decimal(str(result["total_landed_pkr"])) == Decimal("407118.88")
    levy_types = {l["levy_type"] for l in result["levies"]}
    assert levy_types == {"CD", "ACD", "RD", "FED", "ST", "WHT_148"}
    assert result["disclaimer"]


def test_chat_tool_calculate_duty_handles_invalid_date(auth_client):
    async def _run():
        async with SessionLocal() as session:
            user = await _get_user()
            ctx = ChatContext(session=session, project=None, user=user)
            return await _tool_calculate_duty(
                ctx,
                hs_code=MOBILE,
                declared_value_usd=1000,
                exchange_rate=280,
                as_of_date="not-a-date",
            )

    result = asyncio.run(_run())
    assert "error" in result


def test_chat_tool_classify_hs_code_returns_candidates(auth_client):
    queue_responses(_VALID_RESPONSE)

    async def _run():
        async with SessionLocal() as session:
            user = await _get_user()
            ctx = ChatContext(session=session, project=None, user=user)
            return await _tool_classify_hs_code(
                ctx, product_description="an android smartphone"
            )

    result = asyncio.run(_run())
    assert result["candidates"][0]["hs_code"] == MOBILE
    assert result["disclaimer"]


def test_chat_tool_classify_hs_code_handles_malformed_llm_output(auth_client):
    queue_responses("garbage", "still garbage")

    async def _run():
        async with SessionLocal() as session:
            user = await _get_user()
            ctx = ChatContext(session=session, project=None, user=user)
            return await _tool_classify_hs_code(ctx, product_description="a phone")

    result = asyncio.run(_run())
    assert "error" in result
