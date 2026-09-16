"""Registration and login business logic. Deliberately framework-agnostic -
raises small domain exceptions instead of HTTPException, so the API layer
(app/api/routes/auth.py) owns the HTTP-status/error-message mapping and this
module stays testable without spinning up FastAPI."""

from sqlalchemy.orm import Session

from app.core.roles import RoleName
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories import role_repository, user_repository


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AccountDisabledError(Exception):
    pass


def register_user(db: Session, *, email: str, password: str, full_name: str) -> User:
    """Always creates a USER account. There is no code path here that can
    create a RESOLVER or ADMIN - see DECISIONS.md D23."""
    if user_repository.get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError()

    default_role = role_repository.get_role_by_name(db, RoleName.USER)
    if default_role is None:
        # Would mean the seed migration (DECISIONS.md D16) never ran - a
        # deployment/ops problem, not a condition the API can recover from.
        raise RuntimeError("Default USER role is not seeded in the database")

    user = user_repository.create_user(
        db,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role_id=default_role.id,
    )
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    """Checks identity (email + password) before ever looking at is_active,
    so a wrong password against a disabled account still gets the same
    generic failure as a wrong password against an active one - only a
    caller who has already proven they know the correct password learns
    that the account is disabled. See DECISIONS.md D21."""
    user = user_repository.get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()
    if not user.is_active:
        raise AccountDisabledError()
    return user


def issue_access_token(user: User) -> str:
    return create_access_token(subject=str(user.id))
