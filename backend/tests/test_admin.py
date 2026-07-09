"""Admin console API: login, authorization, and compliance document downloads."""
from __future__ import annotations

import uuid


def _admin_headers(client) -> dict:
    from app.config import settings

    resp = client.post(
        "/admin/login",
        json={
            "username": settings.admin_username,
            "password": settings.admin_password,
        },
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_admin_login_rejects_wrong_credentials(client):
    resp = client.post(
        "/admin/login", json={"username": "admin@quolate.com", "password": "nope"}
    )
    assert resp.status_code == 401


def test_admin_endpoints_reject_user_token(auth_client):
    # auth_client carries a regular user token — not enough for admin routes.
    assert auth_client.get("/admin/users").status_code == 401


def test_admin_users_lists_registered_users(auth_client):
    resp = auth_client.get("/admin/users", headers=_admin_headers(auth_client))
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "user@example.com" in emails


def test_admin_download_library_document(auth_client):
    content = b"library compliance file body"
    up = auth_client.post(
        "/library/documents",
        files=[("files", ("compliance.txt", content, "text/plain"))],
    )
    assert up.status_code == 200
    doc_id = auth_client.get("/library/documents").json()[0]["id"]

    resp = auth_client.get(
        f"/admin/library-documents/{doc_id}/file",
        headers=_admin_headers(auth_client),
    )
    assert resp.status_code == 200
    assert resp.content == content
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition and "compliance.txt" in disposition


def test_admin_download_project_document(auth_client):
    content = b"Widget A price 12.50 USD"
    pid = auth_client.post("/projects", json={"name": "P"}).json()["id"]
    up = auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("quote.txt", content, "text/plain"))],
    )
    assert up.status_code == 201
    doc_id = auth_client.get(f"/projects/{pid}/documents").json()[0]["id"]

    resp = auth_client.get(
        f"/admin/documents/{doc_id}/file", headers=_admin_headers(auth_client)
    )
    assert resp.status_code == 200
    assert resp.content == content
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition and "quote.txt" in disposition


def test_admin_download_requires_admin_token(auth_client):
    doc_id = uuid.uuid4()
    assert auth_client.get(f"/admin/documents/{doc_id}/file").status_code == 401
    assert (
        auth_client.get(f"/admin/library-documents/{doc_id}/file").status_code == 401
    )


def test_admin_download_unknown_document_404(client):
    headers = _admin_headers(client)
    doc_id = uuid.uuid4()
    assert (
        client.get(f"/admin/documents/{doc_id}/file", headers=headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/admin/library-documents/{doc_id}/file", headers=headers
        ).status_code
        == 404
    )
