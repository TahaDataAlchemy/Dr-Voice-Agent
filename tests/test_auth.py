import uuid


def test_signup_login_me_flow(client):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/signup", json={"email": email, "password": "supersecret1", "full_name": "Test"})
    assert resp.status_code == 201, resp.text
    token = resp.json()["data"]["access_token"]
    assert resp.json()["data"]["user"]["email"] == email

    dup = client.post("/api/v1/auth/signup", json={"email": email, "password": "supersecret1"})
    assert dup.status_code == 409

    bad = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "unauthorized"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["data"]["email"] == email


def test_protected_endpoints_require_token(client):
    assert client.get("/api/v1/calls").status_code == 401
    assert client.get("/api/v1/dashboard/stats").status_code == 401
    assert client.get("/api/v1/calls", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_status_is_public(client):
    resp = client.get("/api/v1/dashboard/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["api"] == "up" and data["database"]["connected"] is True


def test_short_password_rejected(client):
    resp = client.post("/api/v1/auth/signup", json={"email": "x@example.com", "password": "short"})
    assert resp.status_code == 422
