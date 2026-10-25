import uuid

import pytest

from tests.conftest import PASSWORD, register


def test_register_login_and_me(client):
    headers = register(client, "alice@test.com", "Alice Martin")
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["email"] == "alice@test.com" and me["full_name"] == "Alice Martin"


def test_duplicate_email_rejected_case_insensitive(client):
    register(client, "alice@test.com")
    r = client.post("/api/auth/register", json={"email": "ALICE@test.com", "password": PASSWORD, "full_name": "X"})
    assert r.status_code == 400


@pytest.mark.parametrize("password", ["short", "x" * 73])
def test_password_length_rules(client, password):
    r = client.post("/api/auth/register", json={"email": "a@test.com", "password": password, "full_name": "A"})
    assert r.status_code == 422


def test_login_is_case_insensitive_on_email(client):
    register(client, "alice@test.com")
    r = client.post("/api/auth/login", json={"email": "Alice@Test.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"


def test_wrong_password_then_rate_limit(client):
    register(client, "alice@test.com")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "alice@test.com", "password": "mauvais-mdp"}).status_code == 401
    # le 6e essai est bloqué, même avec le BON mot de passe
    assert client.post("/api/auth/login", json={"email": "alice@test.com", "password": PASSWORD}).status_code == 429


def test_swagger_form_login(client):
    register(client, "alice@test.com")
    r = client.post("/api/auth/token", data={"username": "alice@test.com", "password": PASSWORD})
    assert r.status_code == 200 and "access_token" in r.json()


def test_invalid_token_rejected(client):
    assert client.get("/api/meetings/", headers={"Authorization": "Bearer abc"}).status_code == 401


_ID = str(uuid.uuid4())
PROTECTED = [
    ("GET", "/api/auth/me"), ("GET", "/api/meetings/"), ("POST", "/api/meetings/create"),
    ("POST", "/api/meetings/upload"), ("GET", f"/api/meetings/{_ID}"), ("GET", f"/api/meetings/{_ID}/segments"),
    ("GET", "/api/tasks/"), ("GET", f"/api/tasks/meeting/{_ID}"), ("PATCH", f"/api/tasks/{_ID}"),
    ("GET", "/api/team/"), ("POST", "/api/team/"), ("GET", "/api/team/members"), ("GET", f"/api/team/{_ID}"),
    ("POST", f"/api/team/{_ID}/members"), ("DELETE", f"/api/team/{_ID}/members/{_ID}"),
    ("POST", "/api/rag/ask"), ("POST", "/api/rag/search"), ("GET", "/api/rag/status"),
    ("POST", "/api/rag/reindex"), ("POST", f"/api/rag/reindex/{_ID}"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_route_requires_authentication(client, method, path):
    assert client.request(method, path).status_code == 401


def test_health_endpoints_are_public(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["database"] == "ok"
