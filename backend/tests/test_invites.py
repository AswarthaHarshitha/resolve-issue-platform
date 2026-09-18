"""POST/GET /admin/invites and POST /auth/activate (DECISIONS.md D52): an
admin invites an email to become a RESOLVER/ADMIN; the account is not
created until the invited person visits the one-time link and sets their
own password. The admin never chooses or sees that password."""

import uuid

from tests.auth_helpers import auth_headers
from tests.factories import make_team, make_user_with_role


def _extract_token(activation_url: str) -> str:
    return activation_url.split("token=")[1]


def test_non_admin_cannot_create_invites(client, db_session):
    user = make_user_with_role(db_session, "USER", "invite-check-user@example.com")

    response = client.post(
        "/api/v1/admin/invites",
        json={"email": "invitee1@example.com", "role": "RESOLVER"},
        headers=auth_headers(user),
    )

    assert response.status_code == 403


def test_admin_can_invite_a_resolver_with_a_team(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin1@example.com")
    team = make_team(db_session, "Invite Team 1")

    response = client.post(
        "/api/v1/admin/invites",
        json={"email": "invitee2@example.com", "role": "RESOLVER", "team_id": str(team.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "invitee2@example.com"
    assert body["role"] == "RESOLVER"
    assert body["team"]["name"] == "Invite Team 1"
    assert "token=" in body["activation_url"]


def test_resolver_invite_without_a_team_is_rejected(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin2@example.com")

    response = client.post(
        "/api/v1/admin/invites", json={"email": "invitee3@example.com", "role": "RESOLVER"}, headers=auth_headers(admin)
    )

    assert response.status_code == 400


def test_invite_cannot_grant_user_role(client, db_session):
    """USER is self-registration-only (DECISIONS.md D23) - not reachable
    through the invite mechanism at all, even by an admin."""
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin3@example.com")

    response = client.post(
        "/api/v1/admin/invites", json={"email": "invitee4@example.com", "role": "USER"}, headers=auth_headers(admin)
    )

    assert response.status_code == 422  # rejected by request validation, never reaches the service


def test_cannot_invite_an_already_registered_email(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin4@example.com")
    make_user_with_role(db_session, "USER", "already-here@example.com")

    response = client.post(
        "/api/v1/admin/invites", json={"email": "already-here@example.com", "role": "ADMIN"}, headers=auth_headers(admin)
    )

    assert response.status_code == 400


def test_activation_creates_the_account_with_the_invited_role_and_team(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin5@example.com")
    team = make_team(db_session, "Invite Team 5")

    invite_response = client.post(
        "/api/v1/admin/invites",
        json={"email": "invitee5@example.com", "role": "RESOLVER", "team_id": str(team.id)},
        headers=auth_headers(admin),
    )
    token = _extract_token(invite_response.json()["activation_url"])

    activate_response = client.post(
        "/api/v1/auth/activate",
        json={"token": token, "password": "BrandNewPass1", "full_name": "Newly Activated"},
    )

    assert activate_response.status_code == 200
    body = activate_response.json()
    assert body["user"]["email"] == "invitee5@example.com"
    assert body["user"]["role"]["name"] == "RESOLVER"
    assert body["user"]["team"]["name"] == "Invite Team 5"
    assert body["user"]["full_name"] == "Newly Activated"
    assert body["access_token"]  # activation immediately authenticates

    # The password chosen at activation actually works for a normal login.
    login_response = client.post(
        "/api/v1/auth/login", json={"email": "invitee5@example.com", "password": "BrandNewPass1"}
    )
    assert login_response.status_code == 200


def test_activation_token_is_single_use(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin6@example.com")

    invite_response = client.post(
        "/api/v1/admin/invites", json={"email": "invitee6@example.com", "role": "ADMIN"}, headers=auth_headers(admin)
    )
    token = _extract_token(invite_response.json()["activation_url"])

    first = client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "FirstPass1", "full_name": "First"}
    )
    second = client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "SecondPass1", "full_name": "Second"}
    )

    assert first.status_code == 200
    assert second.status_code == 400


def test_activation_with_an_unknown_token_is_rejected(client):
    response = client.post(
        "/api/v1/auth/activate",
        json={"token": "not-a-real-token", "password": "WhateverPass1", "full_name": "Nobody"},
    )

    assert response.status_code == 400


def test_activation_does_not_grant_a_client_supplied_role(client, db_session):
    """The activation request body has no role field at all - the created
    account's role always comes from the invite the admin created, never
    from anything the person completing activation could submit."""
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin7@example.com")
    team = make_team(db_session, "Invite Team 7")

    invite_response = client.post(
        "/api/v1/admin/invites",
        json={"email": "invitee7@example.com", "role": "RESOLVER", "team_id": str(team.id)},
        headers=auth_headers(admin),
    )
    token = _extract_token(invite_response.json()["activation_url"])

    activate_response = client.post(
        "/api/v1/auth/activate",
        json={
            "token": token,
            "password": "BrandNewPass1",
            "full_name": "Sneaky",
            "role": "ADMIN",  # unexpected field - must be silently ignored, never trusted
        },
    )

    assert activate_response.status_code == 200
    assert activate_response.json()["user"]["role"]["name"] == "RESOLVER"


def test_admin_can_list_pending_invites(client, db_session):
    admin = make_user_with_role(db_session, "ADMIN", "invite-admin8@example.com")
    client.post(
        "/api/v1/admin/invites", json={"email": "invitee8@example.com", "role": "ADMIN"}, headers=auth_headers(admin)
    )

    response = client.get("/api/v1/admin/invites", headers=auth_headers(admin))

    assert response.status_code == 200
    emails = [item["email"] for item in response.json()]
    assert "invitee8@example.com" in emails


def test_activate_nonexistent_issue_route_requires_no_auth_header(client):
    """The activation endpoint is deliberately public/unauthenticated (like
    register) - it must not require a Bearer token to even attempt it."""
    response = client.post(
        "/api/v1/auth/activate", json={"token": str(uuid.uuid4()), "password": "WhateverPass1", "full_name": "X"}
    )

    assert response.status_code != 401
