"""POST/GET /issues/{id}/comments, and the CRITICAL SPECIAL RULE (Phase 7
spec, DECISIONS.md D11/D41): the issue owner's own comment while
WAITING_FOR_USER atomically resumes the issue to IN_PROGRESS and closes the
SLA pause; anyone else's comment never does."""

import uuid

from app.models.enums import IssueStatus, StatusChangeTrigger
from app.models.issue_status_history import IssueStatusHistory
from tests.auth_helpers import auth_headers
from tests.factories import make_user_with_role


def _create_via_api(client, user, title="Sample issue"):
    response = client.post(
        "/api/v1/issues", json={"title": title, "description": "Sample description."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_owner_can_comment_on_their_own_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "comment-owner1@example.com")
    issue = _create_via_api(client, owner)

    response = client.post(
        f"/api/v1/issues/{issue['id']}/comments", json={"body": "Any update?"}, headers=auth_headers(owner)
    )

    assert response.status_code == 201
    assert response.json()["body"] == "Any update?"
    assert response.json()["author"]["email"] == "comment-owner1@example.com"


def test_other_user_cannot_comment_on_someone_elses_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "comment-owner2@example.com")
    other = make_user_with_role(db_session, "USER", "comment-other1@example.com")
    issue = _create_via_api(client, owner)

    response = client.post(
        f"/api/v1/issues/{issue['id']}/comments", json={"body": "Not mine"}, headers=auth_headers(other)
    )

    assert response.status_code == 403


def test_admin_can_comment_on_any_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "comment-owner3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "comment-admin1@example.com")
    issue = _create_via_api(client, owner)

    response = client.post(
        f"/api/v1/issues/{issue['id']}/comments", json={"body": "Admin note"}, headers=auth_headers(admin)
    )

    assert response.status_code == 201


def test_empty_comment_rejected(client, db_session):
    owner = make_user_with_role(db_session, "USER", "comment-owner4@example.com")
    issue = _create_via_api(client, owner)

    response = client.post(
        f"/api/v1/issues/{issue['id']}/comments", json={"body": "   "}, headers=auth_headers(owner)
    )

    assert response.status_code == 422


def test_list_comments_returns_in_chronological_order(client, db_session):
    owner = make_user_with_role(db_session, "USER", "comment-owner5@example.com")
    issue = _create_via_api(client, owner)
    client.post(f"/api/v1/issues/{issue['id']}/comments", json={"body": "First"}, headers=auth_headers(owner))
    client.post(f"/api/v1/issues/{issue['id']}/comments", json={"body": "Second"}, headers=auth_headers(owner))

    response = client.get(f"/api/v1/issues/{issue['id']}/comments", headers=auth_headers(owner))

    assert response.status_code == 200
    bodies = [c["body"] for c in response.json()]
    assert bodies == ["First", "Second"]


def test_list_comments_requires_access(client, db_session):
    owner = make_user_with_role(db_session, "USER", "comment-owner6@example.com")
    other = make_user_with_role(db_session, "USER", "comment-other2@example.com")
    issue = _create_via_api(client, owner)

    response = client.get(f"/api/v1/issues/{issue['id']}/comments", headers=auth_headers(other))

    assert response.status_code == 403


def test_comment_on_nonexistent_issue_returns_404(client, db_session):
    user = make_user_with_role(db_session, "USER", "comment-owner7@example.com")

    response = client.post(
        f"/api/v1/issues/{uuid.uuid4()}/comments", json={"body": "hi"}, headers=auth_headers(user)
    )

    assert response.status_code == 404


def _issue_waiting_for_user(client, db_session, owner, resolver):
    issue = _create_via_api(client, owner)
    headers = auth_headers(resolver)
    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "WAITING_FOR_USER"):
        response = client.patch(f"/api/v1/issues/{issue['id']}/status", json={"status": target}, headers=headers)
        assert response.status_code == 200
    return issue


def test_owner_comment_while_waiting_for_user_auto_resumes_to_in_progress(client, db_session):
    owner = make_user_with_role(db_session, "USER", "auto-resume-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "auto-resume-resolver1@example.com")
    issue = _issue_waiting_for_user(client, db_session, owner, resolver)

    response = client.post(
        f"/api/v1/issues/{issue['id']}/comments", json={"body": "I'm back online now."}, headers=auth_headers(owner)
    )
    assert response.status_code == 201

    issue_check = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(owner))
    assert issue_check.json()["status"] == "IN_PROGRESS"

    history = (
        db_session.query(IssueStatusHistory)
        .filter_by(issue_id=uuid.UUID(issue["id"]))
        .order_by(IssueStatusHistory.created_at)
        .all()
    )
    auto_resume_rows = [h for h in history if h.trigger == StatusChangeTrigger.AUTO_USER_REPLY]
    assert len(auto_resume_rows) == 1
    assert auto_resume_rows[0].previous_status == IssueStatus.WAITING_FOR_USER
    assert auto_resume_rows[0].new_status == IssueStatus.IN_PROGRESS
    assert auto_resume_rows[0].changed_by_id == uuid.UUID(str(owner.id))


def test_resolver_comment_while_waiting_for_user_does_not_auto_resume(client, db_session):
    owner = make_user_with_role(db_session, "USER", "auto-resume-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "auto-resume-resolver2@example.com")
    issue = _issue_waiting_for_user(client, db_session, owner, resolver)

    response = client.post(
        f"/api/v1/issues/{issue['id']}/comments",
        json={"body": "Still working on it."},
        headers=auth_headers(resolver),
    )
    assert response.status_code == 201

    issue_check = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(resolver))
    assert issue_check.json()["status"] == "WAITING_FOR_USER"


def test_admin_comment_while_waiting_for_user_does_not_auto_resume(client, db_session):
    owner = make_user_with_role(db_session, "USER", "auto-resume-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "auto-resume-resolver3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "auto-resume-admin1@example.com")
    issue = _issue_waiting_for_user(client, db_session, owner, resolver)

    client.post(
        f"/api/v1/issues/{issue['id']}/comments", json={"body": "Admin checking in."}, headers=auth_headers(admin)
    )

    issue_check = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(resolver))
    assert issue_check.json()["status"] == "WAITING_FOR_USER"


def test_owner_comment_while_not_waiting_for_user_does_not_change_status(client, db_session):
    owner = make_user_with_role(db_session, "USER", "auto-resume-owner4@example.com")
    issue = _create_via_api(client, owner)  # still OPEN

    client.post(f"/api/v1/issues/{issue['id']}/comments", json={"body": "hello"}, headers=auth_headers(owner))

    issue_check = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(owner))
    assert issue_check.json()["status"] == "OPEN"
