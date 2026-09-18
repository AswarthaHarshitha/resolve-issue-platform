"""PATCH /issues/{id}/assignment: append-only assignment history
(DECISIONS.md D7), admin reassignment vs. resolver self-assign
(DECISIONS.md D41)."""

import uuid

from app.models.issue_assignment import IssueAssignment
from tests.auth_helpers import auth_headers
from tests.factories import make_team, make_user_with_role


def _create_via_api(client, user):
    response = client.post(
        "/api/v1/issues", json={"title": "Needs assignment", "description": "Description text."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_admin_can_assign_a_team_to_an_unassigned_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner1@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin1@example.com")
    team = make_team(db_session, "Assign Team 1")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"team_id": str(team.id), "reason": "manual triage"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["current_team"]["id"] == str(team.id)


def test_admin_can_assign_a_resolver_belonging_to_the_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner2@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin2@example.com")
    team = make_team(db_session, "Assign Team 2")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver2@example.com", team=team)
    issue = _create_via_api(client, owner)

    client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin)
    )
    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["current_resolver"]["id"] == str(resolver.id)


def test_assignment_history_is_append_only(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin3@example.com")
    team_a = make_team(db_session, "Assign Team 3A")
    team_b = make_team(db_session, "Assign Team 3B")
    issue = _create_via_api(client, owner)

    client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin)
    )
    client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_b.id)}, headers=auth_headers(admin)
    )

    history = (
        db_session.query(IssueAssignment)
        .filter_by(issue_id=uuid.UUID(issue["id"]))
        .order_by(IssueAssignment.created_at)
        .all()
    )
    assert len(history) == 2
    assert history[0].team_id == team_a.id
    assert history[1].team_id == team_b.id


def test_resolver_can_self_assign_an_issue_on_their_own_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner4@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin4@example.com")
    team = make_team(db_session, "Assign Team 4")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver4@example.com", team=team)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin))

    response = client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={}, headers=auth_headers(resolver))

    assert response.status_code == 200
    assert response.json()["current_resolver"]["id"] == str(resolver.id)


def test_resolver_cannot_change_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner5@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin5@example.com")
    team_a = make_team(db_session, "Assign Team 5A")
    team_b = make_team(db_session, "Assign Team 5B")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver5@example.com", team=team_a)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin))

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_b.id)}, headers=auth_headers(resolver)
    )

    assert response.status_code == 403


def test_resolver_cannot_assign_someone_else(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner6@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin6@example.com")
    team = make_team(db_session, "Assign Team 6")
    resolver_a = make_user_with_role(db_session, "RESOLVER", "assign-resolver6a@example.com", team=team)
    resolver_b = make_user_with_role(db_session, "RESOLVER", "assign-resolver6b@example.com", team=team)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin))

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver_b.id)},
        headers=auth_headers(resolver_a),
    )

    assert response.status_code == 403


def test_resolver_cannot_self_assign_a_different_teams_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner7@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin7@example.com")
    team_a = make_team(db_session, "Assign Team 7A")
    team_b = make_team(db_session, "Assign Team 7B")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver7@example.com", team=team_b)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin))

    response = client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={}, headers=auth_headers(resolver))

    assert response.status_code == 403


def test_user_cannot_assign_issues(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner8@example.com")
    team = make_team(db_session, "Assign Team 8")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(owner)
    )

    assert response.status_code == 403


def test_admin_cannot_assign_a_resolver_from_a_different_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner10@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin10@example.com")
    team_a = make_team(db_session, "Assign Team 10A")
    team_b = make_team(db_session, "Assign Team 10B")
    resolver_b = make_user_with_role(db_session, "RESOLVER", "assign-resolver10b@example.com", team=team_b)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin))

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver_b.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 400


def test_cannot_assign_resolver_without_a_team_first(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner9@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin9@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver9@example.com")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 400
