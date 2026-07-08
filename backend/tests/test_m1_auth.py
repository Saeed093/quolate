"""M1 tests: auth roundtrip, wrong password, owner isolation, BOM TSV paste."""
from __future__ import annotations


def _register_and_login(client, email: str, password: str = "password123") -> str:
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": "T"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_register_login_roundtrip(client):
    r = client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "password123"},
    )
    assert r.status_code == 201
    assert r.json()["email"] == "a@example.com"

    login = client.post(
        "/auth/login", json={"email": "a@example.com", "password": "password123"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"


def test_wrong_password_401(client):
    client.post(
        "/auth/register",
        json={"email": "b@example.com", "password": "password123"},
    )
    resp = client.post(
        "/auth/login", json={"email": "b@example.com", "password": "wrongpass"}
    )
    assert resp.status_code == 401


def test_user_cannot_read_others_project(client):
    token_a = _register_and_login(client, "owner@example.com")
    created = client.post(
        "/projects",
        json={"name": "Secret"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    token_b = _register_and_login(client, "intruder@example.com")
    resp = client.get(
        f"/projects/{project_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 404

    # And B's project list must not include A's project.
    listing = client.get(
        "/projects", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert all(p["id"] != project_id for p in listing.json())


def test_delete_project_removes_all_associated_data(auth_client):
    import asyncio
    import json

    from app.jobs.worker import drain
    from app.llm.mock import queue_responses

    pid = auth_client.post("/projects", json={"name": "To Delete"}).json()["id"]
    auth_client.post(f"/projects/{pid}/bom", json={"part_name": "Widget"})
    queue_responses(
        json.dumps(
            {
                "supplier_name": "ACME",
                "line_items": [{"line_no": 1, "part_name": "Widget", "unit_price": 9}],
                "fields": [
                    {
                        "bom_line_no": 1,
                        "field_type": "unit_price",
                        "value_num": 9,
                        "confidence": 0.9,
                        "source_snippet": "Widget 9",
                    }
                ],
            }
        )
    )
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("q.txt", b"Widget 9 USD", "text/plain"))],
    )
    assert asyncio.run(drain()) >= 1

    resp = auth_client.delete(f"/projects/{pid}")
    assert resp.status_code == 204
    assert auth_client.get(f"/projects/{pid}").status_code == 404
    assert auth_client.get(f"/projects/{pid}/bom").status_code == 404
    assert auth_client.get(f"/projects/{pid}/documents").status_code == 404


def test_bom_tsv_paste_parses_quantities_and_prices(auth_client):
    project = auth_client.post("/projects", json={"name": "P"}).json()
    pid = project["id"]

    tsv = (
        "Part\tSpec\tQty\tTarget Price\tNotes\n"
        "Thermal Camera\t640x480, 25mm\t10\t$1,250.50\turgent\n"
        "Tripod\tAluminium\t5\tUSD 45\t\n"
    )
    resp = auth_client.post(
        f"/projects/{pid}/bom/paste", json={"text": tsv}
    )
    assert resp.status_code == 201
    items = resp.json()
    assert len(items) == 2

    cam = items[0]
    assert cam["part_name"] == "Thermal Camera"
    assert cam["spec_requirement"] == "640x480, 25mm"
    assert float(cam["quantity"]) == 10
    assert float(cam["target_price"]) == 1250.50
    assert cam["notes"] == "urgent"
    assert cam["line_no"] == 1

    tripod = items[1]
    assert float(tripod["quantity"]) == 5
    assert float(tripod["target_price"]) == 45
    assert tripod["notes"] is None
