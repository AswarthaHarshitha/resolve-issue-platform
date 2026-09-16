"""POST /api/v1/auth/register - scenarios 1-8 from the Phase 3 spec."""

from app.core.security import verify_password
from app.models.user import User


def _register(client, **overrides):
    payload = {
        "email": "newuser@example.com",
        "password": "Sup3rSecret1",
        "full_name": "New User",
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload)


def test_valid_registration_succeeds(client):
    response = _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newuser@example.com"
    assert body["full_name"] == "New User"
    assert body["role"]["name"] == "USER"
    assert body["is_active"] is True


def test_password_is_hashed_and_plaintext_never_stored(client, db_session):
    _register(client, email="hashcheck@example.com")

    user = db_session.query(User).filter(User.email == "hashcheck@example.com").one()

    assert user.password_hash != "Sup3rSecret1"
    assert user.password_hash.startswith("$2b$")  # bcrypt hash prefix
    assert verify_password("Sup3rSecret1", user.password_hash)


def test_duplicate_email_is_rejected(client):
    _register(client, email="dupe@example.com")

    response = _register(client, email="dupe@example.com")

    assert response.status_code == 409


def test_duplicate_email_is_rejected_case_insensitively(client):
    """Email is normalized (lowercased) - registering with different casing
    of an already-used address must still be treated as a duplicate."""
    _register(client, email="CaseTest@Example.com")

    response = _register(client, email="casetest@example.com")

    assert response.status_code == 409


def test_invalid_email_rejected(client):
    response = _register(client, email="not-an-email")

    assert response.status_code == 422


def test_password_too_short_rejected(client):
    response = _register(client, email="shortpw@example.com", password="Ab1")

    assert response.status_code == 422


def test_password_without_digit_rejected(client):
    response = _register(client, email="nodigitpw@example.com", password="OnlyLetters")

    assert response.status_code == 422


def test_password_without_letter_rejected(client):
    response = _register(client, email="nolletterpw@example.com", password="12345678")

    assert response.status_code == 422


def test_public_registration_cannot_create_admin(client, db_session):
    """The request schema has no `role` field at all - sending one is either
    ignored (extra fields dropped) or rejected, but never honored."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "wannabeadmin@example.com",
            "password": "Sup3rSecret1",
            "full_name": "Wannabe Admin",
            "role": "ADMIN",
        },
    )

    assert response.status_code == 201
    user = db_session.query(User).filter(User.email == "wannabeadmin@example.com").one()
    assert user.role.name == "USER"


def test_default_role_is_user(client, db_session):
    _register(client, email="defaultrole@example.com")

    user = db_session.query(User).filter(User.email == "defaultrole@example.com").one()
    assert user.role.name == "USER"


def test_registration_response_never_includes_password_hash(client):
    response = _register(client, email="nohash@example.com")

    assert "password" not in response.text.lower()
    assert "password_hash" not in response.json()
