"""POST /api/v1/auth/logout - tests the stateless MVP strategy actually
documented in DECISIONS.md D22, rather than pretending a different one is in
place: the endpoint requires a valid token and confirms the request
succeeded, but issues no server-side revocation, so the same token
legitimately still works afterward."""

from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import get_settings
from tests.factories import make_user_with_role

settings = get_settings()


def _token_for(user):
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "iat": int(now.timestamp()), "exp": now + timedelta(minutes=60)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_logout_requires_authentication(client):
    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 401


def test_logout_succeeds_for_an_authenticated_user(client, db_session):
    user = make_user_with_role(db_session, "USER", "logout1@example.com")
    token = _token_for(user)

    response = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 204


def test_logout_does_not_invalidate_the_token_stateless_mvp_tradeoff(client, db_session):
    """Documents the actual, known limitation rather than claiming
    server-side invalidation that isn't implemented (DECISIONS.md D22):
    the same access token still authenticates successfully after logout."""
    user = make_user_with_role(db_session, "USER", "logout2@example.com")
    token = _token_for(user)
    headers = {"Authorization": f"Bearer {token}"}

    logout_response = client.post("/api/v1/auth/logout", headers=headers)
    me_response_after_logout = client.get("/api/v1/auth/me", headers=headers)

    assert logout_response.status_code == 204
    assert me_response_after_logout.status_code == 200
