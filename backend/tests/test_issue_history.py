"""GET /issues/{id}/history - the activity-timeline data source for the
issue detail page. Same access control as everything else (can_access_issue)."""

import uuid

from tests.auth_helpers import auth_headers
from tests.factories import make_user_with_role


def test_history_shows_creation_and_transitions_in_order(client, db_session):
    owner = make_user_with_role(db_session, "USER", "history-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "history-resolver1@example.com")
    response = client.post(
        "/api/v1/issues", json={"title": "History test", "description": "Description text."}, headers=auth_headers(owner)
    )
    issue_id = response.json()["id"]
    client.patch(f"/api/v1/issues/{issue_id}/status", json={"status": "TRIAGED"}, headers=auth_headers(resolver))

    history_response = client.get(f"/api/v1/issues/{issue_id}/history", headers=auth_headers(owner))

    assert history_response.status_code == 200
    rows = history_response.json()
    assert len(rows) == 2
    assert rows[0]["new_status"] == "OPEN"
    assert rows[0]["trigger"] == "SYSTEM_CREATE"
    assert rows[1]["new_status"] == "TRIAGED"
    assert rows[1]["trigger"] == "MANUAL"
    assert rows[1]["changed_by"]["email"] == "history-resolver1@example.com"


def test_history_requires_access(client, db_session):
    owner = make_user_with_role(db_session, "USER", "history-owner2@example.com")
    other = make_user_with_role(db_session, "USER", "history-other2@example.com")
    response = client.post(
        "/api/v1/issues", json={"title": "Private", "description": "Description text."}, headers=auth_headers(owner)
    )
    issue_id = response.json()["id"]

    history_response = client.get(f"/api/v1/issues/{issue_id}/history", headers=auth_headers(other))

    assert history_response.status_code == 403


def test_history_on_nonexistent_issue_returns_404(client, db_session):
    owner = make_user_with_role(db_session, "USER", "history-owner3@example.com")

    response = client.get(f"/api/v1/issues/{uuid.uuid4()}/history", headers=auth_headers(owner))

    assert response.status_code == 404
