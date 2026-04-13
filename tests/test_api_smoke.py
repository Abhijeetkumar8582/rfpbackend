"""Smoke tests: app loads, public routes respond, auth rejects bad credentials."""

from __future__ import annotations


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_openapi_json_available(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    data = r.json()
    assert data.get("openapi") or data.get("swagger") is not None or "paths" in data
    assert "/api/v1/auth/login" in data.get("paths", {})


def test_auth_login_rejects_unknown_user(client):
    r = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent_smoke_test@example.com",
            "password": "wrong",
        },
    )
    assert r.status_code == 401
    assert "detail" in r.json()


def test_search_answer_requires_auth(client):
    r = client.post(
        "/api/v1/search/answer",
        json={
            "query_text": "test",
            "project_id": "PROJ-2026-001",
            "k": 3,
        },
    )
    assert r.status_code == 401
