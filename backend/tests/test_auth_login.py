"""POST /api/v1/auth/login - scenarios 9-12 from the Phase 3 spec, plus the
attack-review question of whether an unknown email produces a different
response from a wrong password (it must not)."""

from tests.factories import make_user_with_role


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
