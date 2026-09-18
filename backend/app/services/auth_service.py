"""Registration and login business logic. Deliberately framework-agnostic -
raises small domain exceptions instead of HTTPException, so the API layer
(app/api/routes/auth.py) owns the HTTP-status/error-message mapping and this
module stays testable without spinning up FastAPI."""

from typing import Optional

from sqlalchemy.orm import Session

from app.core.roles import RoleName
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories import role_repository, user_repository

# Maps a frontend "which door did you sign in through" hint to the one
# database role that entry point is meant for. This is a UX gate only, not
# an authorization mechanism - every request after login is still
# independently authorized by the existing per-request role/team checks
# (require_role, can_access_issue, etc.) regardless of what login_context
# was used. The context itself is never trusted as proof of anything; it
# only narrows *which* accounts are allowed to complete a login through a
# given entry point, and the check is against the real, freshly-loaded
# database role - never anything the client asserts about itself.
LOGIN_CONTEXT_ROLES = {
    "student": RoleName.USER,
    "resolver": RoleName.RESOLVER,
    "admin": RoleName.ADMIN,
}


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


def authenticate_user(db: Session, *, email: str, password: str, login_context: Optional[str] = None) -> User:
    """Checks identity (email + password) before ever looking at is_active,
    so a wrong password against a disabled account still gets the same
    generic failure as a wrong password against an active one - only a
    caller who has already proven they know the correct password learns
    that the account is disabled. See DECISIONS.md D21.

    `login_context` ("student"/"resolver"/"admin") is an optional UX gate
    (DECISIONS.md D50): if given, the account's real database role must
    match what that entry point is for, or authentication fails with the
    exact same InvalidCredentialsError a wrong password would raise - never
    a distinct error, so a mismatched context can't be used to fingerprint
    whether an email is registered or what role it actually has. A caller
    that omits login_context (the plain, role-agnostic /auth/login path
    every existing test and API client uses) is unaffected."""
    user = user_repository.get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()
    if login_context is not None and user.role.name != LOGIN_CONTEXT_ROLES.get(login_context):
        raise InvalidCredentialsError()
    if not user.is_active:
        raise AccountDisabledError()
    return user


def issue_access_token(user: User) -> str:
    return create_access_token(subject=str(user.id))
