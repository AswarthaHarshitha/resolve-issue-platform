"""JWT validation (scenarios 13-17) and GET /api/v1/auth/me (scenarios 18-20)
from the Phase 3 spec, plus two attack-review checks: a tampered role claim
inside an otherwise validly-signed token, and a token whose signature uses
the correct algorithm but the wrong secret."""

import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import get_settings
from tests.factories import make_user_with_role

settings = get_settings()


def _make_token(sub, secret=None, algorithm=None, exp_delta=timedelta(minutes=60), extra_claims=None):
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "iat": int(now.timestamp()), "exp": now + exp_delta}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret or settings.jwt_secret_key, algorithm=algorithm or settings.jwt_algorithm)


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_valid_jwt_returns_current_user(client, db_session):
    user = make_user_with_role(db_session, "USER", "valid-token@example.com")

    response = client.get("/api/v1/auth/me", headers=_auth_header(_make_token(str(user.id))))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "valid-token@example.com"
    assert body["role"]["name"] == "USER"
    assert "password_hash" not in body


def test_me_includes_team_when_user_has_one(client, db_session):
    from tests.factories import make_team

    team = make_team(db_session, "IT Support")
    user = make_user_with_role(db_session, "RESOLVER", "withteam@example.com", team=team)

    response = client.get("/api/v1/auth/me", headers=_auth_header(_make_token(str(user.id))))

    assert response.status_code == 200
    assert response.json()["team"]["name"] == "IT Support"


def test_nonexistent_user_fails(client):
    """Scenario 19: a validly-signed token for a user id that doesn't exist
    (equivalent to the user having been deleted) must fail authentication."""
    response = client.get("/api/v1/auth/me", headers=_auth_header(_make_token(str(uuid.uuid4()))))

    assert response.status_code == 401


def test_inactive_user_cannot_use_protected_endpoint(client, db_session):
    """Scenario 20. The token is still validly signed and unexpired - what
    makes this request fail is the fresh database lookup in
    get_current_user finding is_active=False, exactly the behavior
    DECISIONS.md D21 exists to guarantee."""
    user = make_user_with_role(db_session, "USER", "goesinactive@example.com")
    token = _make_token(str(user.id))

    user.is_active = False
    db_session.flush()

    response = client.get("/api/v1/auth/me", headers=_auth_header(token))

    assert response.status_code == 401


def test_expired_jwt_fails(client, db_session):
    user = make_user_with_role(db_session, "USER", "expired-token@example.com")
    token = _make_token(str(user.id), exp_delta=timedelta(minutes=-5))

    response = client.get("/api/v1/auth/me", headers=_auth_header(token))

    assert response.status_code == 401


def test_malformed_jwt_fails(client):
    response = client.get("/api/v1/auth/me", headers=_auth_header("not-a-real-token"))

    assert response.status_code == 401


def test_invalid_signature_fails(client, db_session):
    user = make_user_with_role(db_session, "USER", "badsig@example.com")
    token = _make_token(str(user.id), secret="a-completely-different-secret")

    response = client.get("/api/v1/auth/me", headers=_auth_header(token))

    assert response.status_code == 401


def test_missing_authorization_header_fails(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_invalid_authorization_scheme_fails(client, db_session):
    user = make_user_with_role(db_session, "USER", "badscheme@example.com")
    token = _make_token(str(user.id))

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Token {token}"})

    assert response.status_code == 401


def test_tampered_role_claim_inside_a_validly_signed_token_is_ignored(client, db_session):
    """Even if a token somehow carries a role claim (our own tokens never do
    - DECISIONS.md D21), the backend never reads it: role always comes from
    a fresh database lookup of the user identified by `sub`, not from the
    token payload."""
    user = make_user_with_role(db_session, "USER", "roleclaim@example.com")
    token = _make_token(str(user.id), extra_claims={"role": "ADMIN"})

    me_response = client.get("/api/v1/auth/me", headers=_auth_header(token))
    admin_response = client.get("/api/v1/_rbac-demo/admin-only", headers=_auth_header(token))

    assert me_response.status_code == 200
    assert me_response.json()["role"]["name"] == "USER"
    assert admin_response.status_code == 403
