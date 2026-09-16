"""Scenarios 21-27: role-based access control, tested with real HTTP
requests against the temporary /_rbac-demo endpoints (app/api/routes/
rbac_demo.py) - the only protected endpoints that exist in Phase 3."""

from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import get_settings
from tests.factories import make_user_with_role

settings = get_settings()


def _token_for(user):
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "iat": int(now.timestamp()), "exp": now + timedelta(minutes=60)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _auth(user):
    return {"Authorization": f"Bearer {_token_for(user)}"}


def test_user_can_access_user_only_endpoint(client, db_session):
    user = make_user_with_role(db_session, "USER", "rbac-user1@example.com")

    response = client.get("/api/v1/_rbac-demo/user-only", headers=_auth(user))

    assert response.status_code == 200


def test_user_cannot_access_resolver_endpoint(client, db_session):
    user = make_user_with_role(db_session, "USER", "rbac-user2@example.com")

    response = client.get("/api/v1/_rbac-demo/resolver-only", headers=_auth(user))

    assert response.status_code == 403


def test_user_cannot_access_admin_endpoint(client, db_session):
    user = make_user_with_role(db_session, "USER", "rbac-user3@example.com")

    response = client.get("/api/v1/_rbac-demo/admin-only", headers=_auth(user))

    assert response.status_code == 403


def test_resolver_can_access_resolver_endpoint(client, db_session):
    resolver = make_user_with_role(db_session, "RESOLVER", "rbac-resolver1@example.com")

    response = client.get("/api/v1/_rbac-demo/resolver-only", headers=_auth(resolver))

    assert response.status_code == 200


def test_resolver_cannot_access_admin_endpoint(client, db_session):
    """RESOLVER must not implicitly receive ADMIN permissions."""
    resolver = make_user_with_role(db_session, "RESOLVER", "rbac-resolver2@example.com")

    response = client.get("/api/v1/_rbac-demo/admin-only", headers=_auth(resolver))

    assert response.status_code == 403


def test_resolver_cannot_access_user_only_endpoint(client, db_session):
    """Role checks are exact-match, not a hierarchy - a RESOLVER is not
    automatically also a USER for authorization purposes."""
    resolver = make_user_with_role(db_session, "RESOLVER", "rbac-resolver3@example.com")

    response = client.get("/api/v1/_rbac-demo/user-only", headers=_auth(resolver))

    assert response.status_code == 403


def test_admin_can_access_admin_endpoint(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "rbac-admin1@example.com")

    response = client.get("/api/v1/_rbac-demo/admin-only", headers=_auth(admin))

    assert response.status_code == 200


def test_admin_permissions_are_not_implicitly_granted_to_others(client, db_session):
    """Explicit corollary of scenario 26: USER and RESOLVER must both still
    be rejected from the admin-only endpoint (covered individually above);
    this test asserts ADMIN itself does not get resolver-only access for
    free either - every allowed role must be explicitly listed."""
    admin = make_user_with_role(db_session, "ADMIN", "rbac-admin2@example.com")

    response = client.get("/api/v1/_rbac-demo/resolver-only", headers=_auth(admin))

    assert response.status_code == 403


def test_require_any_role_accepts_either_listed_role(client, db_session):
    resolver = make_user_with_role(db_session, "RESOLVER", "rbac-either1@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "rbac-either2@example.com")

    resolver_response = client.get("/api/v1/_rbac-demo/resolver-or-admin", headers=_auth(resolver))
    admin_response = client.get("/api/v1/_rbac-demo/resolver-or-admin", headers=_auth(admin))

    assert resolver_response.status_code == 200
    assert admin_response.status_code == 200


def test_require_any_role_rejects_role_not_listed(client, db_session):
    user = make_user_with_role(db_session, "USER", "rbac-either3@example.com")

    response = client.get("/api/v1/_rbac-demo/resolver-or-admin", headers=_auth(user))

    assert response.status_code == 403


def test_unauthorized_request_is_rejected_server_side(client):
    """Scenario 27: no Authorization header at all - the request never even
    reaches a role check, it's rejected at authentication."""
    response = client.get("/api/v1/_rbac-demo/admin-only")

    assert response.status_code == 401
