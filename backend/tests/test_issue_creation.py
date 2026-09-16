"""POST /api/v1/issues - creation flow. Business status must always be
OPEN/PENDING immediately after creation, regardless of anything AI-related
(there is no AI yet in Phase 4 - see DECISIONS.md, issue_service.py)."""

from app.models.enums import IssueStatus, StatusChangeTrigger
from app.models.issue_status_history import IssueStatusHistory
from tests.auth_helpers import auth_headers as _auth
from tests.factories import make_user_with_role


def test_authenticated_user_can_create_issue(client, db_session):
    user = make_user_with_role(db_session, "USER", "creator1@example.com")

    response = client.post(
        "/api/v1/issues",
        json={"title": "Wi-Fi outage in Block B", "description": "The Wi-Fi has stopped working."},
        headers=_auth(user),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["ai_analysis_status"] == "PENDING"
    assert body["owner"]["email"] == "creator1@example.com"
    assert body["priority"] is None
    assert body["category"] is None


def test_creation_requires_authentication(client):
    response = client.post(
        "/api/v1/issues", json={"title": "No auth", "description": "Should be rejected."}
    )

    assert response.status_code == 401


def test_creation_writes_a_system_create_status_history_row(client, db_session):
    user = make_user_with_role(db_session, "USER", "creator2@example.com")

    response = client.post(
        "/api/v1/issues",
        json={"title": "Broken printer", "description": "The printer on floor 3 is jammed."},
        headers=_auth(user),
    )
    issue_id = response.json()["id"]

    history = db_session.query(IssueStatusHistory).filter_by(issue_id=issue_id).all()
    assert len(history) == 1
    assert history[0].previous_status is None
    assert history[0].new_status == IssueStatus.OPEN
    assert history[0].trigger == StatusChangeTrigger.SYSTEM_CREATE
    assert history[0].changed_by_id == user.id


def test_empty_title_rejected(client, db_session):
    user = make_user_with_role(db_session, "USER", "creator3@example.com")

    response = client.post(
        "/api/v1/issues", json={"title": "   ", "description": "Valid description here."}, headers=_auth(user)
    )

    assert response.status_code == 422


def test_empty_description_rejected(client, db_session):
    user = make_user_with_role(db_session, "USER", "creator4@example.com")

    response = client.post(
        "/api/v1/issues", json={"title": "Valid title", "description": ""}, headers=_auth(user)
    )

    assert response.status_code == 422


def test_title_too_long_rejected(client, db_session):
    user = make_user_with_role(db_session, "USER", "creator5@example.com")

    response = client.post(
        "/api/v1/issues",
        json={"title": "x" * 201, "description": "Valid description."},
        headers=_auth(user),
    )

    assert response.status_code == 422


def test_resolver_and_admin_can_also_create_issues(client, db_session):
    """Issue creation isn't restricted to the USER role - any authenticated
    person may report an issue."""
    resolver = make_user_with_role(db_session, "RESOLVER", "creator-resolver@example.com")

    response = client.post(
        "/api/v1/issues",
        json={"title": "Resolver-reported issue", "description": "Found during triage."},
        headers=_auth(resolver),
    )

    assert response.status_code == 201
