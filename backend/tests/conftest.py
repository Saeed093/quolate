"""Pytest fixtures. Runs against a dedicated test database on the same Postgres.

Environment is configured BEFORE importing any app module so the module-level
engine binds to the test database and the LLM uses the mock client.
"""
from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urlsplit

import pytest

# psycopg async requires the selector loop on Windows (not ProactorEventLoop).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Configure environment before importing the app ---
_DEFAULT_TEST_DB = "postgresql+psycopg://quolate:quolate@localhost:5433/quolate_test"
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DB)
os.environ["DATABASE_URL"] = _TEST_DB_URL
os.environ["LLM_BASE_URL"] = "mock"
os.environ["RUN_WORKER"] = "0"
os.environ.setdefault("JWT_SECRET", "test-secret")


def _sync_url(url: str) -> str:
    # psycopg3 sync uses the same DSN sans the sqlalchemy driver prefix.
    return url.replace("postgresql+psycopg://", "postgresql://")


def _admin_dsn(url: str) -> str:
    parts = urlsplit(_sync_url(url))
    # Connect to the maintenance 'postgres' db to create/drop test dbs.
    return f"postgresql://{parts.username}:{parts.password}@{parts.hostname}:{parts.port or 5432}/postgres"


def _db_name(url: str) -> str:
    return urlsplit(_sync_url(url)).path.lstrip("/")


def _create_database_if_missing(url: str) -> None:
    import psycopg

    name = _db_name(url)
    with psycopg.connect(_admin_dsn(url), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')


def _run_migrations(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    # Keep the +psycopg driver so SQLAlchemy uses psycopg3 (sync), not psycopg2.
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    _create_database_if_missing(_TEST_DB_URL)
    _run_migrations(_TEST_DB_URL)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_tables(_prepare_database):
    """Truncate all data tables between tests for isolation."""
    import psycopg

    yield
    tables = [
        "saved_filters",
        "project_library_documents",
        "library_document_embeddings",
        "library_documents",
        "tender_embeddings",
        "tender_documents",
        "tenders",
        "tender_sources",
        "document_embeddings",
        "jobs",
        "chat_messages",
        "quotes",
        "extracted_fields",
        "documents",
        "suppliers",
        "bom_items",
        "projects",
        "users",
    ]
    with psycopg.connect(_sync_url(_TEST_DB_URL), autocommit=True) as conn:
        conn.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")


@pytest.fixture(autouse=True)
def _reset_mock_llm():
    from app.llm.mock import reset_mock

    reset_mock()
    yield
    reset_mock()


@pytest.fixture
def auth_client(client):
    """A TestClient with a registered+logged-in user and helper to add token."""
    email = "user@example.com"
    password = "password123"
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": "User"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": password})
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
