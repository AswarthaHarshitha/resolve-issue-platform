"""GET /api/v1/issues/{id} and GET /api/v1/issues - ownership and
coarse-grained role access (DECISIONS.md D24: USER sees only their own
issues, RESOLVER/ADMIN see all issues - team-scoped narrowing is a later
phase, since team assignment doesn't exist until Phase 5's routing)."""

from tests.auth_helpers import auth_headers
from tests.factories import make_user_with_role


def _create_via_api(client, user, title="Sample issue", description="Sample description."):
    response = client.post(
        "/api/v1/issues", json={"title": title, "description": description}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_owner_can_view_their_own_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "owner1@example.com")
    issue = _create_via_api(client, owner)

    response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["id"] == issue["id"]


def test_other_user_cannot_view_someone_elses_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "owner2@example.com")
    other_user = make_user_with_role(db_session, "USER", "other-user@example.com")
    issue = _create_via_api(client, owner)

    response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(other_user))

    assert response.status_code == 403


def test_resolver_can_view_any_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "viewer-resolver@example.com")
    issue = _create_via_api(client, owner)

    response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(resolver))

    assert response.status_code == 200


def test_admin_can_view_any_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "owner4@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "viewer-admin@example.com")
    issue = _create_via_api(client, owner)

    response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(admin))

    assert response.status_code == 200


def test_nonexistent_issue_returns_404(client, db_session):
    user = make_user_with_role(db_session, "USER", "owner5@example.com")

    import uuid

    response = client.get(f"/api/v1/issues/{uuid.uuid4()}", headers=auth_headers(user))

    assert response.status_code == 404


def test_get_issue_requires_authentication(client, db_session):
    owner = make_user_with_role(db_session, "USER", "owner6@example.com")
    issue = _create_via_api(client, owner)

    response = client.get(f"/api/v1/issues/{issue['id']}")

    assert response.status_code == 401


def test_user_list_only_shows_own_issues(client, db_session):
    owner = make_user_with_role(db_session, "USER", "lister1@example.com")
    other_user = make_user_with_role(db_session, "USER", "lister1-other@example.com")
    _create_via_api(client, owner, title="Mine")
    _create_via_api(client, other_user, title="Not mine")

    response = client.get("/api/v1/issues", headers=auth_headers(owner))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Mine"


def test_resolver_list_shows_all_issues(client, db_session):
    owner_a = make_user_with_role(db_session, "USER", "lister2a@example.com")
    owner_b = make_user_with_role(db_session, "USER", "lister2b@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "lister2-resolver@example.com")
    _create_via_api(client, owner_a, title="Issue A")
    _create_via_api(client, owner_b, title="Issue B")

    response = client.get("/api/v1/issues", headers=auth_headers(resolver))

    assert response.status_code == 200
    assert response.json()["total"] >= 2


def test_list_pagination(client, db_session):
    user = make_user_with_role(db_session, "USER", "paginator@example.com")
    for i in range(5):
        _create_via_api(client, user, title=f"Paginated issue {i}")

    response = client.get("/api/v1/issues?page=1&page_size=2", headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2


def test_list_rejects_invalid_pagination_params(client, db_session):
    user = make_user_with_role(db_session, "USER", "bad-pagination@example.com")

    assert client.get("/api/v1/issues?page=0", headers=auth_headers(user)).status_code == 422
    assert client.get("/api/v1/issues?page_size=0", headers=auth_headers(user)).status_code == 422
    assert client.get("/api/v1/issues?page_size=101", headers=auth_headers(user)).status_code == 422


def test_list_status_filter(client, db_session):
    user = make_user_with_role(db_session, "USER", "filterer@example.com")
    _create_via_api(client, user, title="Still open")

    response = client.get("/api/v1/issues?status=OPEN", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["total"] >= 1

    response = client.get("/api/v1/issues?status=CLOSED", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["total"] == 0
