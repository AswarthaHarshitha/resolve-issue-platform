"""POST /issues/{id}/resolution/confirm and .../reject - the only path to
CLOSED (DECISIONS.md D9, D30, D41): only the issue's own submitter may
confirm or reject, and RESOLVED -> CLOSED is unreachable any other way."""

import uuid

from tests.auth_helpers import auth_headers
from tests.factories import make_user_with_role


def _resolved_issue(client, owner, resolver):
    response = client.post(
        "/api/v1/issues", json={"title": "Needs resolving", "description": "Description text."}, headers=auth_headers(owner)
    )
    issue_id = response.json()["id"]
    headers = auth_headers(resolver)
    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "RESOLVED"):
        r = client.patch(f"/api/v1/issues/{issue_id}/status", json={"status": target}, headers=headers)
        assert r.status_code == 200
    return issue_id


def test_owner_can_confirm_resolution(client, db_session):
    owner = make_user_with_role(db_session, "USER", "confirm-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver1@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"


def test_resolver_cannot_confirm_resolution(client, db_session):
    """The resolver who marked it RESOLVED cannot close it themselves -
    only the submitting user can (DECISIONS.md D9)."""
    owner = make_user_with_role(db_session, "USER", "confirm-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver2@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(resolver))

    assert response.status_code == 403


def test_admin_cannot_confirm_resolution_either(client, db_session):
    """No silent admin override in this phase - see the original
    architecture review's explicit scoping decision."""
    owner = make_user_with_role(db_session, "USER", "confirm-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "confirm-admin3@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(admin))

    assert response.status_code == 403


def test_cannot_confirm_an_issue_that_is_not_resolved(client, db_session):
    owner = make_user_with_role(db_session, "USER", "confirm-owner4@example.com")
    response = client.post(
        "/api/v1/issues", json={"title": "Still open", "description": "Description text."}, headers=auth_headers(owner)
    )
    issue_id = response.json()["id"]

    confirm_response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(owner))

    assert confirm_response.status_code == 400


def test_owner_can_reject_resolution_returning_to_in_progress(client, db_session):
    owner = make_user_with_role(db_session, "USER", "reject-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reject-resolver1@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(
        f"/api/v1/issues/{issue_id}/resolution/reject",
        json={"status": "IN_PROGRESS", "note": "Not actually fixed"},
        headers=auth_headers(owner),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


def test_other_user_cannot_reject_resolution(client, db_session):
    owner = make_user_with_role(db_session, "USER", "reject-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reject-resolver2@example.com")
    other_user = make_user_with_role(db_session, "USER", "reject-other2@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(
        f"/api/v1/issues/{issue_id}/resolution/reject",
        json={"status": "IN_PROGRESS"},
        headers=auth_headers(other_user),
    )

    assert response.status_code == 403


def test_resolver_can_act_again_after_rejection(client, db_session):
    """After a rejection, the issue is genuinely active again - a resolver
    can move it forward through the normal state machine."""
    owner = make_user_with_role(db_session, "USER", "reject-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reject-resolver3@example.com")
    issue_id = _resolved_issue(client, owner, resolver)
    client.post(
        f"/api/v1/issues/{issue_id}/resolution/reject", json={"status": "IN_PROGRESS"}, headers=auth_headers(owner)
    )

    response = client.patch(
        f"/api/v1/issues/{issue_id}/status", json={"status": "RESOLVED"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 200


def test_confirm_on_nonexistent_issue_returns_404(client, db_session):
    owner = make_user_with_role(db_session, "USER", "confirm-owner5@example.com")

    response = client.post(f"/api/v1/issues/{uuid.uuid4()}/resolution/confirm", headers=auth_headers(owner))

    assert response.status_code == 404


def test_generic_status_endpoint_still_cannot_reach_closed_after_resolution(client, db_session):
    """Belt-and-suspenders: even with a RESOLVED issue in hand, the generic
    transition endpoint (resolver/admin-only) still cannot skip the
    confirmation flow."""
    owner = make_user_with_role(db_session, "USER", "confirm-owner6@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver6@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.patch(
        f"/api/v1/issues/{issue_id}/status", json={"status": "CLOSED"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 400
