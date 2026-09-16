"""Framework-agnostic password hashing and JWT helpers. No FastAPI imports
here on purpose - this module has no idea it's being used by a web API,
which keeps it trivially unit-testable and reusable.

JWT claim design (see DECISIONS.md D21): the token carries only `sub` (the
user's UUID as a string), `iat`, and `exp`. It deliberately does NOT carry
`role` - every protected request re-loads the user (and therefore their
current role and is_active state) from PostgreSQL, so a role change or
account deactivation takes effect immediately instead of waiting for the
token to expire. Embedding role in the token would only invite some future
code path to trust it directly instead of checking the database.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# bcrypt via passlib: a well-established, purpose-built password hash (not a
# general-purpose fast hash like SHA-256) with a built-in work factor and
# salt. See DECISIONS.md D26.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Raises jose.JWTError (or a subclass, e.g. ExpiredSignatureError) if the
    signature is invalid, the token is malformed, or it has expired. Callers
    must not treat a decoded payload as trustworthy without this having
    succeeded - this is the only function in the codebase that verifies a
    JWT's signature."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
