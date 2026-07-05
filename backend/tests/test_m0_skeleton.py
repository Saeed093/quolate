"""M0 skeleton tests: health, migrations apply clean, CORS for frontend origin."""
from __future__ import annotations

import psycopg
from alembic import command
from alembic.config import Config

from tests.conftest import _admin_dsn, _sync_url, _TEST_DB_URL


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_migrations_apply_clean():
    """upgrade head -> downgrade base -> upgrade head on a throwaway database."""
    scratch = "quolate_migtest"
    # Alembic uses the +psycopg (SQLAlchemy) URL; raw psycopg uses the plain DSN.
    alembic_url = _TEST_DB_URL.rsplit("/", 1)[0] + f"/{scratch}"
    raw_url = _sync_url(_TEST_DB_URL).rsplit("/", 1)[0] + f"/{scratch}"

    with psycopg.connect(_admin_dsn(_TEST_DB_URL), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        conn.execute(f'CREATE DATABASE "{scratch}"')

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", alembic_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

        with psycopg.connect(raw_url) as conn:
            row = conn.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'tenders'"
            ).fetchone()
            assert row[0] == 1
            # pgvector extension present
            ext = conn.execute(
                "SELECT count(*) FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            assert ext[0] == 1
    finally:
        with psycopg.connect(_admin_dsn(_TEST_DB_URL), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{scratch}"')


def test_cors_for_frontend_origin(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in (200, 204)
    assert (
        resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )
