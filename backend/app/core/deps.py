"""Reusable FastAPI authentication/authorization dependencies. Every
protected endpoint in the app should depend on get_current_user (directly or
via require_role/require_any_role) rather than re-implementing token
handling - this is the one place JWT validation and the active-user check
happen.

Phase 3 only implements role-level RBAC (require_role/require_any_role).
Resource-level authorization (e.g. "a USER may only access their own
issues," "a RESOLVER may only access issues assigned to their team") has no
resources to check yet - issue endpoints don't exist until a later phase -
so it's deliberately not built here. See DECISIONS.md D24.
"""

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.repositories import user_repository

# tokenUrl is only used to populate Swagger UI's "Authorize" flow; login
# itself is a plain JSON endpoint, not an OAuth2 password-grant form.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Validates the JWT's signature and expiration, then re-loads the user
    from PostgreSQL on every call - role and is_active are always read fresh
    from the database, never trusted from the token (DECISIONS.md D21). An
    inactive or since-deleted user fails here, which means every endpoint
    depending on this function automatically rejects disabled accounts."""
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise _CREDENTIALS_ERROR

    raw_subject = payload.get("sub")
    if raw_subject is None:
        raise _CREDENTIALS_ERROR

    try:
        user_id = UUID(raw_subject)
    except ValueError:
        raise _CREDENTIALS_ERROR

    user = user_repository.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR

    return user


def require_any_role(*role_names: str):
    """Factory: returns a dependency that requires the current user's role
    to be one of `role_names`. RESOLVER does not implicitly gain ADMIN
    permissions and vice versa - every allowed role must be listed
    explicitly by whoever declares the endpoint."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.name not in role_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency


def require_role(role_name: str):
    return require_any_role(role_name)
