"""M5 tender module tests. Adapters use saved snapshots; LLM is mocked."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.auth.security import hash_password
from app.db.models import SavedFilter, Tender, TenderSource, User
from app.db.session import SessionLocal
from app.llm.embeddings import embed_text
from app.llm.mock import queue_responses
from app.tenders.adapters.base import NoticeData
from app.tenders.adapters.generic import GenericAdapter
from app.tenders.adapters.ppra_federal import PpraFederalAdapter
from app.tenders.classifier import classify_tender
from app.tenders.correlation import correlate_embedding
from app.tenders.notifications import count_saved_filter_matches
from app.tenders.scraper import pull_source, upsert_notice

_FIXTURES = Path(__file__).parent / "fixtures" / "tenders"

_CLASSIFY = json.dumps(
    {"org_type": "federal", "category": "goods", "sector_tags": ["defense"]}
)


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


async def _make_user_and_source(
    session, *, adapter: str = "ppra_federal", email: str = "m5@example.com"
) -> tuple[User, TenderSource]:
    user = User(email=email, password_hash=hash_password("password123"))
    session.add(user)
    await session.flush()
    source = TenderSource(
        owner_id=user.id,
        name="Test Source",
        base_url="http://example.test/tenders",
        adapter=adapter,
        enabled=True,
    )
    session.add(source)
    await session.flush()
    return user, source


# ---------- Adapters ----------
def test_ppra_federal_adapter_parses_snapshot():
    adapter = PpraFederalAdapter("http://ppra.org.pk")
    refs = adapter.parse_listing(_fixture("ppra_federal_listing.html"))
    assert len(refs) == 3
    nos = [r.tender_no for r in refs]
    assert "TS-2026-001" in nos
    titles = " ".join((r.title or "") for r in refs)
    assert "Thermal" in titles
    # Detail link captured for click-through / detail fetch.
    assert any(r.detail_url for r in refs)


def test_generic_adapter_extracts_notices_from_arbitrary_listing():
    queue_responses(
        json.dumps(
            {
                "notices": [
                    {
                        "tender_no": "DPN/2026/44",
                        "title": "Supply of laboratory reagents",
                        "organization": "District Health Office, Multan",
                        "closing_date": "30 June 2026",
                        "city": "Multan",
                    },
                    {
                        "tender_no": "DPN/2026/45",
                        "title": "Repair and maintenance of school buildings",
                        "organization": "Education Department",
                        "closing_date": "02 July 2026",
                        "city": "Multan",
                    },
                ]
            }
        )
    )
    adapter = GenericAdapter("http://district.test")
    refs = adapter.parse_listing(_fixture("generic_listing.html"))
    assert len(refs) == 2
    assert refs[0].tender_no == "DPN/2026/44"
    assert "laboratory" in (refs[0].title or "").lower()


# ---------- Classification ----------
def test_classifier_maps_to_controlled_vocab_only():
    queue_responses(
        json.dumps(
            {
                "org_type": "provincial",
                "category": "goods",
                "sector_tags": ["medical", "aliens", "IT", "not_a_tag"],
            }
        )
    )
    result = classify_tender(
        "Medical equipment procurement", "hospital beds and IT", "Health Department"
    )
    assert result["org_type"] == "provincial"
    assert result["category"] == "goods"
    assert result["sector_tags"] == ["medical", "it"]  # invalid tags dropped


# ---------- Scraper: dedup + corrigendum + fail-soft ----------
def test_dedup_on_source_and_tender_no():
    async def _run() -> int:
        async with SessionLocal() as session:
            _, source = await _make_user_and_source(session)
            queue_responses(_CLASSIFY, _CLASSIFY)
            await upsert_notice(
                session,
                source,
                NoticeData(tender_no="D-1", title="Supply of pumps", raw_text="pumps"),
            )
            await upsert_notice(
                session,
                source,
                NoticeData(
                    tender_no="D-1", title="Supply of pumps (v2)", raw_text="pumps v2"
                ),
            )
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Tender)
                    .where(Tender.source_id == source.id)
                )
            ).scalar_one()
            return count

    assert asyncio.run(_run()) == 1


def test_corrigendum_links_to_original():
    async def _run():
        async with SessionLocal() as session:
            _, source = await _make_user_and_source(session)
            queue_responses(_CLASSIFY, _CLASSIFY)
            await upsert_notice(
                session,
                source,
                NoticeData(
                    tender_no="T-100",
                    title="Supply of generators",
                    raw_text="Supply of generators",
                ),
            )
            _, corr = await upsert_notice(
                session,
                source,
                NoticeData(
                    tender_no="T-100-C",
                    title="Corrigendum to tender T-100",
                    raw_text="Corrigendum to tender T-100 closing date extended",
                    corrigendum_of_tender_no="T-100",
                ),
            )
            original = (
                await session.execute(
                    select(Tender).where(
                        Tender.source_id == source.id, Tender.tender_no == "T-100"
                    )
                )
            ).scalar_one()
            return corr.corrigendum_of, original.id

    corr_of, original_id = asyncio.run(_run())
    assert corr_of == original_id


def test_adapter_failure_marks_source_not_crash_worker():
    class BoomAdapter:
        default_org_type = "other"

        def list_notices(self, since=None):
            raise RuntimeError("portal down")

    async def _run():
        async with SessionLocal() as session:
            _, source = await _make_user_and_source(session)
            result = await pull_source(
                session, source, adapter=BoomAdapter(), delay=0
            )
            return result, source.last_status

    result, last_status = asyncio.run(_run())
    assert result["status"] == "failed"
    assert last_status == "failed"


# ---------- Saved filters + notifications ----------
def test_saved_filter_matches_new_tender_creates_notification():
    async def _run() -> int:
        async with SessionLocal() as session:
            user, source = await _make_user_and_source(session)
            session.add(
                Tender(
                    source_id=source.id,
                    tender_no="G-1",
                    title="Supply of medical goods",
                    organization="Health Dept",
                    org_type="provincial",
                    category="goods",
                    sector_tags=["medical"],
                    city="Lahore",
                )
            )
            session.add(
                SavedFilter(
                    owner_id=user.id, name="Goods", criteria={"category": "goods"}
                )
            )
            # A non-matching filter should not inflate the count.
            session.add(
                SavedFilter(
                    owner_id=user.id, name="Works", criteria={"category": "works"}
                )
            )
            await session.flush()
            return await count_saved_filter_matches(session, user.id)

    assert asyncio.run(_run()) == 1


# ---------- Correlation ----------
def _upload_quote_with_snippet(auth_client, pid, supplier, snippet, line_no):
    queue_responses(
        json.dumps(
            {
                "supplier_name": supplier,
                "currency": "USD",
                "fields": [
                    {
                        "bom_line_no": line_no,
                        "field_type": "unit_price",
                        "value_num": 100.0,
                        "value_text": snippet,
                        "currency": "USD",
                        "confidence": 0.95,
                        "source_snippet": snippet,
                    }
                ],
            }
        )
    )
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", (f"{supplier}.txt", snippet.encode(), "text/plain"))],
    )
    from app.jobs.worker import drain

    asyncio.run(drain())


def test_correlation_returns_semantically_similar_quotes(auth_client):
    pid = auth_client.post("/projects", json={"name": "P"}).json()["id"]
    line = auth_client.post(f"/projects/{pid}/bom", json={"part_name": "Item"}).json()[
        "line_no"
    ]
    _upload_quote_with_snippet(
        auth_client, pid, "ThermalCo", "thermal imaging camera surveillance", line
    )
    _upload_quote_with_snippet(
        auth_client, pid, "ChairCo", "office chair furniture wooden", line
    )

    async def _run():
        async with SessionLocal() as session:
            user = (
                await session.execute(
                    select(User).where(User.email == "user@example.com")
                )
            ).scalar_one()
            emb = embed_text("thermal imaging camera")
            return await correlate_embedding(session, user.id, emb, top_k=5)

    matches = asyncio.run(_run())
    assert matches
    assert matches[0]["supplier"] == "ThermalCo"
    assert matches[0]["similarity"] > 0


# ---------- Live smoke (excluded from default run) ----------
@pytest.mark.live
@pytest.mark.parametrize(
    "adapter_cls,url",
    [
        (PpraFederalAdapter, "https://www.ppra.org.pk/"),
    ],
)
def test_adapter_live_smoke(adapter_cls, url):
    adapter = adapter_cls(url)
    refs = adapter.list_notices()
    assert isinstance(refs, list)
