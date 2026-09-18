import re
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.user import UserPublic

_PASSWORD_MIN_LENGTH = 8
# bcrypt only uses the first 72 bytes of input - reject longer passwords
# explicitly rather than silently ignoring the rest of what the user typed.
_PASSWORD_MAX_LENGTH = 72


class RegisterRequest(BaseModel):
    """Deliberately has no `role` field. Public registration always creates
    a USER account (see app/services/auth_service.py) - there is nothing
    here for a client to send that the backend could even be tempted to
    trust (DECISIONS.md D23)."""

    email: EmailStr
    password: str
    full_name: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name must not be empty")
        if len(value) > 200:
            raise ValueError("full_name must be at most 200 characters")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < _PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters long")
        if len(value) > _PASSWORD_MAX_LENGTH:
            raise ValueError(f"Password must be at most {_PASSWORD_MAX_LENGTH} characters long")
        if not re.search(r"[A-Za-z]", value):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", value):
            raise ValueError("Password must contain at least one digit")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Which of the three frontend entry points (/student-login,
    # /resolver-login, /admin-login) this request came from - a UX gate
    # only, never trusted as proof of role. Omitted entirely by the plain
    # /auth/login callers (existing tests, direct API use). See
    # DECISIONS.md D50.
    login_context: Optional[Literal["student", "resolver", "admin"]] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
