"""Team-scoped resolver access (DECISIONS.md D41, narrowing D29): a RESOLVER
may act on an issue only if it's unassigned or assigned to their own team -
never another team's issue. ADMIN is unaffected (sees/acts on everything)."""

from tests.auth_helpers import auth_headers
from tests.factories import make_team, make_user_with_role


def _create_via_api(client, user):
    response = client.post(
        "/api/v1/issues", json={"title": "Team scoping test", "description": "Description text."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def _assign_to_team(client, admin, issue_id, team):
    response = client.patch(
        f"/api/v1/issues/{issue_id}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin)
    )
    assert response.status_code == 200


def test_resolver_can_view_unassigned_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "team-owner1@example.com")
    team = make_team(db_session, "Scope Team 1")
    resolver = make_user_with_role(db_session, "RESOLVER", "team-resolver1@example.com", team=team)
    issue = _create_via_api(client, owner)

    response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(resolver))

    assert response.status_code == 200


def test_resolver_can_view_and_act_on_their_own_teams_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "team-owner2@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "team-admin2@example.com")
    team = make_team(db_session, "Scope Team 2")
    resolver = make_user_with_role(db_session, "RESOLVER", "team-resolver2@example.com", team=team)
    issue = _create_via_api(client, owner)
    _assign_to_team(client, admin, issue["id"], team)

    view_response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(resolver))
    transition_response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "TRIAGED"}, headers=auth_headers(resolver)
    )

    assert view_response.status_code == 200
    assert transition_response.status_code == 200


def test_resolver_cannot_view_a_different_teams_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "team-owner3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "team-admin3@example.com")
    team_a = make_team(db_session, "Scope Team 3A")
    team_b = make_team(db_session, "Scope Team 3B")
    resolver_b = make_user_with_role(db_session, "RESOLVER", "team-resolver3b@example.com", team=team_b)
    issue = _create_via_api(client, owner)
    _assign_to_team(client, admin, issue["id"], team_a)

    response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(resolver_b))

    assert response.status_code == 403


def test_resolver_cannot_transition_a_different_teams_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "team-owner4@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "team-admin4@example.com")
    team_a = make_team(db_session, "Scope Team 4A")
    team_b = make_team(db_session, "Scope Team 4B")
    resolver_b = make_user_with_role(db_session, "RESOLVER", "team-resolver4b@example.com", team=team_b)
    issue = _create_via_api(client, owner)
    _assign_to_team(client, admin, issue["id"], team_a)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "TRIAGED"}, headers=auth_headers(resolver_b)
    )

    assert response.status_code == 403


def test_resolver_with_no_team_cannot_view_a_teams_issue(client, db_session):
    """A resolver who hasn't been assigned to any team yet is treated the
    same as being on a "different" team - they can still see unassigned
    issues, but not ones already routed to a specific team."""
    owner = make_user_with_role(db_session, "USER", "team-owner5@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "team-admin5@example.com")
    team = make_team(db_session, "Scope Team 5")
    resolver_no_team = make_user_with_role(db_session, "RESOLVER", "team-resolver5@example.com")
    issue = _create_via_api(client, owner)
    _assign_to_team(client, admin, issue["id"], team)

    response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(resolver_no_team))

    assert response.status_code == 403


def test_admin_can_view_and_act_on_any_teams_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "team-owner6@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "team-admin6@example.com")
    team = make_team(db_session, "Scope Team 6")
    issue = _create_via_api(client, owner)
    _assign_to_team(client, admin, issue["id"], team)

    view_response = client.get(f"/api/v1/issues/{issue['id']}", headers=auth_headers(admin))
    transition_response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "TRIAGED"}, headers=auth_headers(admin)
    )

    assert view_response.status_code == 200
    assert transition_response.status_code == 200


def test_resolver_list_shows_own_team_and_unassigned_but_not_other_teams(client, db_session):
    owner = make_user_with_role(db_session, "USER", "team-owner7@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "team-admin7@example.com")
    team_a = make_team(db_session, "Scope Team 7A")
    team_b = make_team(db_session, "Scope Team 7B")
    resolver_a = make_user_with_role(db_session, "RESOLVER", "team-resolver7a@example.com", team=team_a)

    own_team_issue = _create_via_api(client, owner)
    _assign_to_team(client, admin, own_team_issue["id"], team_a)

    other_team_issue = _create_via_api(client, owner)
    _assign_to_team(client, admin, other_team_issue["id"], team_b)

    unassigned_issue = _create_via_api(client, owner)

    response = client.get("/api/v1/issues", headers=auth_headers(resolver_a))

    assert response.status_code == 200
    visible_ids = {item["id"] for item in response.json()["items"]}
    assert own_team_issue["id"] in visible_ids
    assert unassigned_issue["id"] in visible_ids
    assert other_team_issue["id"] not in visible_ids
