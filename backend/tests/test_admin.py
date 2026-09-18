"""Admin CRUD for reference/config data (DECISIONS.md D42): admin-only
access, no hard deletes (is_active instead), and the real replacement for
manually inserting users into the database to provision resolvers/admins."""

import uuid

from tests.auth_helpers import auth_headers
from tests.factories import make_category, make_team, make_user_with_role


def test_non_admin_cannot_access_admin_endpoints(client, db_session):
    user = make_user_with_role(db_session, "USER", "admin-check-user@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "admin-check-resolver@example.com")

    assert client.get("/api/v1/admin/teams", headers=auth_headers(user)).status_code == 403
    assert client.get("/api/v1/admin/teams", headers=auth_headers(resolver)).status_code == 403


def test_admin_can_create_and_list_teams(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-teams1@example.com")

    create_response = client.post(
        "/api/v1/admin/teams", json={"name": "New Team A", "description": "desc"}, headers=auth_headers(admin)
    )
    assert create_response.status_code == 201

    list_response = client.get("/api/v1/admin/teams", headers=auth_headers(admin))
    assert list_response.status_code == 200
    assert any(t["name"] == "New Team A" for t in list_response.json())


def test_admin_can_deactivate_a_team(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-teams2@example.com")
    team = make_team(db_session, "Deactivate Me")

    response = client.patch(
        f"/api/v1/admin/teams/{team.id}", json={"is_active": False}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_duplicate_team_name_rejected(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-teams3@example.com")
    make_team(db_session, "Duplicate Team")

    response = client.post(
        "/api/v1/admin/teams", json={"name": "Duplicate Team"}, headers=auth_headers(admin)
    )

    assert response.status_code == 409


def test_admin_can_create_category_and_sub_category(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-cat1@example.com")

    category_response = client.post(
        "/api/v1/admin/categories", json={"name": "HR"}, headers=auth_headers(admin)
    )
    assert category_response.status_code == 201
    category_id = category_response.json()["id"]

    sub_response = client.post(
        f"/api/v1/admin/categories/{category_id}/sub-categories",
        json={"name": "Payroll"},
        headers=auth_headers(admin),
    )
    assert sub_response.status_code == 201
    assert any(s["name"] == "Payroll" for s in sub_response.json()["sub_categories"])


def test_sub_category_on_nonexistent_category_returns_404(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-cat2@example.com")

    response = client.post(
        f"/api/v1/admin/categories/{uuid.uuid4()}/sub-categories",
        json={"name": "X"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 404


def test_admin_can_create_routing_rule(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-route1@example.com")
    category = make_category(db_session, "Legal")
    team = make_team(db_session, "Legal Ops")

    response = client.post(
        "/api/v1/admin/routing-rules",
        json={"category_id": str(category.id), "team_id": str(team.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    assert response.json()["team"]["id"] == str(team.id)


def test_duplicate_routing_rule_rejected(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-route2@example.com")
    category = make_category(db_session, "Legal2")
    team = make_team(db_session, "Legal Ops 2")
    client.post(
        "/api/v1/admin/routing-rules",
        json={"category_id": str(category.id), "team_id": str(team.id)},
        headers=auth_headers(admin),
    )

    response = client.post(
        "/api/v1/admin/routing-rules",
        json={"category_id": str(category.id), "team_id": str(team.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 409


def test_admin_can_create_sla_rule(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-sla1@example.com")
    category = make_category(db_session, "Ops")

    response = client.post(
        "/api/v1/admin/sla-rules",
        json={
            "category_id": str(category.id),
            "priority": "HIGH",
            "first_response_minutes": 60,
            "resolution_minutes": 1440,
        },
        headers=auth_headers(admin),
    )

    assert response.status_code == 201


def test_sla_rule_rejects_resolution_shorter_than_first_response(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-sla2@example.com")
    category = make_category(db_session, "Ops2")

    response = client.post(
        "/api/v1/admin/sla-rules",
        json={
            "category_id": str(category.id),
            "priority": "HIGH",
            "first_response_minutes": 100,
            "resolution_minutes": 50,
        },
        headers=auth_headers(admin),
    )

    assert response.status_code == 400


def test_sla_rule_update_rejects_non_positive_minutes(client, db_session):
    """Phase 9 regression: SLARuleUpdateRequest was missing the same
    positive-minutes validator SLARuleCreateRequest already had, so an
    admin PATCH could set first_response_minutes/resolution_minutes to 0
    or a negative number - an impossible SLA value that would leave the
    deadline already in the past the instant the rule was applied."""
    admin = make_user_with_role(db_session, "ADMIN", "admin-sla3@example.com")
    category = make_category(db_session, "Ops3")

    create_response = client.post(
        "/api/v1/admin/sla-rules",
        json={
            "category_id": str(category.id),
            "priority": "HIGH",
            "first_response_minutes": 60,
            "resolution_minutes": 1440,
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    rule_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/admin/sla-rules/{rule_id}",
        json={"first_response_minutes": 0},
        headers=auth_headers(admin),
    )

    assert response.status_code == 422

    negative_response = client.patch(
        f"/api/v1/admin/sla-rules/{rule_id}",
        json={"resolution_minutes": -10},
        headers=auth_headers(admin),
    )

    assert negative_response.status_code == 422


def test_admin_can_promote_a_user_to_resolver_with_a_team(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-promote1@example.com")
    user = make_user_with_role(db_session, "USER", "admin-promote-target1@example.com")
    team = make_team(db_session, "Promotion Team")

    response = client.patch(
        f"/api/v1/admin/users/{user.id}",
        json={"role": "RESOLVER", "team_id": str(team.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["role"]["name"] == "RESOLVER"
    assert response.json()["team"]["id"] == str(team.id)


def test_promoting_to_resolver_without_a_team_rejected(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-promote2@example.com")
    user = make_user_with_role(db_session, "USER", "admin-promote-target2@example.com")

    response = client.patch(
        f"/api/v1/admin/users/{user.id}", json={"role": "RESOLVER"}, headers=auth_headers(admin)
    )

    assert response.status_code == 400


def test_demoting_a_resolver_clears_their_team(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-demote1@example.com")
    team = make_team(db_session, "Demotion Team")
    resolver = make_user_with_role(db_session, "RESOLVER", "admin-demote-target1@example.com", team=team)

    response = client.patch(
        f"/api/v1/admin/users/{resolver.id}", json={"role": "USER"}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["team"] is None


def test_admin_can_disable_a_user(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-disable1@example.com")
    user = make_user_with_role(db_session, "USER", "admin-disable-target1@example.com")

    response = client.patch(
        f"/api/v1/admin/users/{user.id}", json={"is_active": False}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_invalid_role_rejected(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "admin-invalidrole1@example.com")
    user = make_user_with_role(db_session, "USER", "admin-invalidrole-target1@example.com")

    response = client.patch(
        f"/api/v1/admin/users/{user.id}", json={"role": "SUPERUSER"}, headers=auth_headers(admin)
    )

    assert response.status_code == 400
