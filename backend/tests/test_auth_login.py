"""POST /api/v1/auth/login - scenarios 9-12 from the Phase 3 spec, plus the
attack-review question of whether an unknown email produces a different
response from a wrong password (it must not), and the login_context UX gate
(DECISIONS.md D50) added for the separate student/resolver/admin login
entry points - a gate on *which door* an account may sign in through, never
a substitute for the real per-request RBAC that still governs every API
call after login."""

from tests.factories import make_team, make_user_with_role


def test_valid_credentials_succeed(client, db_session):
    make_user_with_role(db_session, "USER", "login-ok@example.com", password="CorrectHorse1")

    response = client.post(
        "/api/v1/auth/login", json={"email": "login-ok@example.com", "password": "CorrectHorse1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "login-ok@example.com"
    assert "password" not in response.text.lower()


def test_incorrect_password_fails(client, db_session):
    make_user_with_role(db_session, "USER", "wrongpw@example.com", password="CorrectHorse1")

    response = client.post(
        "/api/v1/auth/login", json={"email": "wrongpw@example.com", "password": "WrongPassword1"}
    )

    assert response.status_code == 401


def test_nonexistent_account_fails(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "WhoKnows1"}
    )

    assert response.status_code == 401


def test_unknown_email_and_wrong_password_give_identical_responses(client, db_session):
    """Attack-review Q10: the login response must not reveal whether the
    email exists at all."""
    make_user_with_role(db_session, "USER", "enumcheck@example.com", password="CorrectHorse1")

    wrong_password_response = client.post(
        "/api/v1/auth/login", json={"email": "enumcheck@example.com", "password": "WrongOne1"}
    )
    unknown_email_response = client.post(
        "/api/v1/auth/login", json={"email": "never-registered@example.com", "password": "WrongOne1"}
    )

    assert wrong_password_response.status_code == unknown_email_response.status_code == 401
    assert wrong_password_response.json() == unknown_email_response.json()


def test_disabled_account_fails_even_with_correct_password(client, db_session):
    make_user_with_role(
        db_session, "USER", "disabled@example.com", password="CorrectHorse1", is_active=False
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": "disabled@example.com", "password": "CorrectHorse1"}
    )

    assert response.status_code == 401
    assert "disabled" in response.json()["detail"].lower()


def test_disabled_account_with_wrong_password_gets_generic_message_not_disabled_hint(client, db_session):
    """An attacker without the correct password must not learn that an
    account exists AND is disabled - only a caller who already proved they
    know the password may be told that."""
    make_user_with_role(
        db_session, "USER", "disabled-wrongpw@example.com", password="CorrectHorse1", is_active=False
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "disabled-wrongpw@example.com", "password": "TotallyWrong1"},
    )

    assert response.status_code == 401
    assert "disabled" not in response.json()["detail"].lower()


def test_login_context_matching_the_accounts_real_role_succeeds(client, db_session):
    make_user_with_role(db_session, "USER", "ctx-student@example.com", password="CorrectHorse1")
    team = make_team(db_session, "Context Team")
    make_user_with_role(db_session, "RESOLVER", "ctx-resolver@example.com", password="CorrectHorse1", team=team)
    make_user_with_role(db_session, "ADMIN", "ctx-admin@example.com", password="CorrectHorse1")

    student = client.post(
        "/api/v1/auth/login",
        json={"email": "ctx-student@example.com", "password": "CorrectHorse1", "login_context": "student"},
    )
    resolver = client.post(
        "/api/v1/auth/login",
        json={"email": "ctx-resolver@example.com", "password": "CorrectHorse1", "login_context": "resolver"},
    )
    admin = client.post(
        "/api/v1/auth/login",
        json={"email": "ctx-admin@example.com", "password": "CorrectHorse1", "login_context": "admin"},
    )

    assert student.status_code == 200
    assert resolver.status_code == 200
    assert admin.status_code == 200


def test_login_context_mismatched_with_the_accounts_real_role_is_rejected(client, db_session):
    """A RESOLVER attempting to sign in through the student/USER-only door
    (and every other mismatched combination) must be rejected - the
    selected login context is never trusted, only the real database role."""
    team = make_team(db_session, "Context Team 2")
    make_user_with_role(db_session, "USER", "ctx-mismatch-user@example.com", password="CorrectHorse1")
    make_user_with_role(
        db_session, "RESOLVER", "ctx-mismatch-resolver@example.com", password="CorrectHorse1", team=team
    )
    make_user_with_role(db_session, "ADMIN", "ctx-mismatch-admin@example.com", password="CorrectHorse1")

    attempts = [
        ("ctx-mismatch-user@example.com", "resolver"),
        ("ctx-mismatch-user@example.com", "admin"),
        ("ctx-mismatch-resolver@example.com", "student"),
        ("ctx-mismatch-resolver@example.com", "admin"),
        ("ctx-mismatch-admin@example.com", "student"),
        ("ctx-mismatch-admin@example.com", "resolver"),
    ]
    for email, wrong_context in attempts:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "CorrectHorse1", "login_context": wrong_context},
        )
        assert response.status_code == 401, f"{email} via {wrong_context} should be rejected"


def test_login_context_mismatch_gives_the_identical_generic_response_as_wrong_password(client, db_session):
    """A mismatched context must not be distinguishable from a wrong
    password - otherwise it becomes a side channel for probing an
    account's real role or its very existence."""
    make_user_with_role(db_session, "USER", "ctx-generic@example.com", password="CorrectHorse1")

    wrong_context_response = client.post(
        "/api/v1/auth/login",
        json={"email": "ctx-generic@example.com", "password": "CorrectHorse1", "login_context": "admin"},
    )
    wrong_password_response = client.post(
        "/api/v1/auth/login",
        json={"email": "ctx-generic@example.com", "password": "WrongPassword1"},
    )

    assert wrong_context_response.status_code == wrong_password_response.status_code == 401
    assert wrong_context_response.json() == wrong_password_response.json()


def test_omitted_login_context_behaves_exactly_as_before(client, db_session):
    """The plain /auth/login path (every existing test/API client) must be
    completely unaffected by this addition."""
    make_user_with_role(db_session, "ADMIN", "ctx-omitted@example.com", password="CorrectHorse1")

    response = client.post(
        "/api/v1/auth/login", json={"email": "ctx-omitted@example.com", "password": "CorrectHorse1"}
    )

    assert response.status_code == 200
