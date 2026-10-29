from datetime import timedelta

import pytest
from sqlalchemy import func, select, update


def test_register_me_logout_and_login(client_factory, register):
    client = client_factory()
    auth = register(client, " Creator@Example.Com ")
    assert auth["user"]["email"] == "creator@example.com"
    assert auth["workspace"]["role"] == "owner"
    assert set(auth) == {"user", "workspace", "csrf_token"}
    cookie = client.cookies.get("vt_session")
    assert cookie and cookie not in str(auth)
    assert client.get("/api/auth/me").json() == auth
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]})
    assert response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    response = client.post(
        "/api/auth/login", json={"email": "CREATOR@example.com", "password": "correct-horse-123"}
    )
    assert response.status_code == 200
    assert response.json()["user"]["id"] == auth["user"]["id"]
    assert client.cookies.get("vt_session") != cookie
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()


def test_duplicate_email_is_atomic_and_password_is_argon2(client_factory, register):
    client = client_factory()
    auth = register(client)
    response = client.post(
        "/api/auth/register",
        json={"email": "CREATOR@example.com", "password": "correct-horse-123", "name": "Dup"},
    )
    assert response.status_code == 409
    from videotranslate.models.core import AuthSession, Membership, User, Workspace

    with client.app.state.session_factory() as db:
        for model in (User, Workspace, Membership):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        session = db.scalar(select(AuthSession))
        assert session.token_hash != client.cookies.get("vt_session")
        assert session.csrf_hash != auth["csrf_token"]
        assert session.expires_at.tzinfo is not None
        assert len(session.token_hash) == 64


@pytest.mark.parametrize("password", ["ab3!s", "x" * 129])
def test_password_length_and_validation_redacts_input(client_factory, password):
    client = client_factory()
    response = client.post(
        "/api/auth/register",
        json={"email": "valid@example.com", "password": password, "name": "Creator"},
    )
    assert response.status_code == 422
    assert password not in response.text
    assert set(response.json()["error"]) == {"code", "message", "retryable", "details"}
    assert "input" not in response.text


def test_generic_wrong_login(client_factory, register):
    client = client_factory()
    register(client)
    wrong = client.post(
        "/api/auth/login", json={"email": "creator@example.com", "password": "incorrect-password"}
    )
    missing = client.post(
        "/api/auth/login", json={"email": "missing@example.com", "password": "incorrect-password"}
    )
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    assert "incorrect-password" not in wrong.text


@pytest.mark.parametrize("mode", ["expired", "revoked"])
def test_session_expiry_and_revocation(client_factory, register, mode):
    client = client_factory()
    register(client)
    from videotranslate.models.core import AuthSession, utcnow

    with client.app.state.session_factory.begin() as db:
        field = (
            {"expires_at": utcnow() - timedelta(seconds=1)}
            if mode == "expired"
            else {"revoked_at": utcnow()}
        )
        db.execute(update(AuthSession).values(**field))
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("token", [None, "wrong"])
def test_logout_requires_csrf(client_factory, register, token):
    client = client_factory()
    register(client)
    response = client.post(
        "/api/auth/logout", headers={} if token is None else {"X-CSRF-Token": token}
    )
    assert response.status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def test_csrf_recovery_rejects_cookie_tampering(client_factory, register):
    client = client_factory()
    register(client)
    client.cookies.set("vt_csrf", "tampered", domain="testserver.local", path="/")
    assert client.get("/api/auth/me").status_code == 403


def test_login_throttle_is_persistent_and_ignores_forwarded_ip(client_factory, register):
    client = client_factory(login_max_attempts=2)
    register(client)
    for i in range(2):
        response = client.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
            json={"email": "creator@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401
    response = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "8.8.8.8"},
        json={"email": "creator@example.com", "password": "correct-horse-123"},
    )
    assert response.status_code == 429
    assert response.json()["error"]["retryable"]
    from videotranslate.models.core import LoginAttempt

    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LoginAttempt)) <= 4
    # A new app using the same database observes the lockout.
    same_db = client.app.state.settings.database_url.get_secret_value()
    restarted = client_factory(database_url=same_db, login_max_attempts=2)
    assert (
        restarted.post(
            "/api/auth/login",
            json={"email": "creator@example.com", "password": "correct-horse-123"},
        ).status_code
        == 429
    )


def test_error_responses_do_not_leak_secrets_or_headers(client_factory, register):
    client = client_factory()
    auth = register(client)
    response = client.post(
        "/api/auth/login",
        json={"email": {"secret": "do-not-return"}, "password": "super-secret-password"},
    )
    assert response.status_code == 422
    for secret in (
        "do-not-return",
        "super-secret-password",
        "password_hash",
        "token_hash",
        client.cookies.get("vt_session"),
        auth["csrf_token"],
    ):
        assert secret not in response.text
    assert client.get("/api/missing").json()["error"]["code"] == "NOT_FOUND"


def test_logout_revokes_cookie_even_if_it_is_replayed(client_factory, register):
    client = client_factory()
    auth = register(client)
    old_session = client.cookies.get("vt_session")
    client.post("/api/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]})
    replay = client.get(
        "/api/auth/me",
        headers={"Cookie": f"vt_session={old_session}; vt_csrf={auth['csrf_token']}"},
    )
    assert replay.status_code == 401


def test_csrf_requires_matching_cookie_and_header(client_factory, register):
    client = client_factory()
    auth = register(client)
    # A valid header alone is insufficient if the paired cookie is missing or tampered.
    session = client.cookies.get("vt_session")
    client.cookies.clear()
    for suffix in ("", "; vt_csrf=tampered"):
        response = client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": auth["csrf_token"], "Cookie": f"vt_session={session}{suffix}"},
        )
        assert response.status_code == 403


def test_unexpected_database_errors_are_contained_before_server_logging(client_factory, register):
    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from videotranslate.models.core import User

    existing = client_factory()

    def fail_insert(_mapper, _connection, _target):
        raise RuntimeError("private-provider-token-never-log")

    event.listen(User, "before_insert", fail_insert)
    try:
        # If the application rethrows, real ASGI servers log its raw exception traceback.
        with TestClient(existing.app, raise_server_exceptions=True) as client:
            response = client.post(
                "/api/auth/register",
                json={
                    "email": "failure@example.com",
                    "password": "correct-horse-123",
                    "name": "Creator",
                },
            )
    finally:
        event.remove(User, "before_insert", fail_insert)
    assert response.status_code == 500
    assert "private-provider-token" not in response.text
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_identity_responses_are_not_cached(client_factory, register):
    client = client_factory()
    register(client)
    response = client.get("/api/auth/me")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_successful_login_cannot_erase_prior_failed_attempts(client_factory, register):
    client = client_factory(login_max_attempts=2)
    register(client)
    bad = {"email": "creator@example.com", "password": "incorrect-password"}
    good = {"email": "creator@example.com", "password": "correct-horse-123"}
    assert client.post("/api/auth/login", json=bad).status_code == 401
    assert client.post("/api/auth/login", json=good).status_code == 200
    assert client.post("/api/auth/login", json=bad).status_code == 401
    # Known valid credentials must not become a way to reset a brute-force budget.
    assert client.post("/api/auth/login", json=good).status_code == 429


def test_non_ascii_csrf_header_is_rejected_without_server_error(client_factory, register):
    client = client_factory()
    register(client)
    response = client.post("/api/auth/logout", headers={b"X-CSRF-Token": b"\xff"})
    assert response.status_code == 403
