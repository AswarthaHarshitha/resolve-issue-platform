from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.roles import RoleName
from app.schemas.auth import TokenResponse
from app.schemas.user import TeamPublic


class InviteCreateRequest(BaseModel):
    """Admin-only. Deliberately restricted to RESOLVER/ADMIN - USER accounts
    are never created through an invite, only self-registration
    (DECISIONS.md D23, D52)."""

    email: EmailStr
    role: str
    team_id: Optional[UUID] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in (RoleName.RESOLVER, RoleName.ADMIN):
            raise ValueError("An invite may only grant RESOLVER or ADMIN - USER is self-registration-only")
        return value


class InvitePublic(BaseModel):
    """Returned once, at creation, to the inviting admin - `activation_url`
    is the only place the raw token ever appears. Never returned again by
    any later read of this invite (there is no GET-by-id for invites)."""

    id: UUID
    email: str
    role: str
    team: Optional[TeamPublic] = None
    expires_at: datetime
    activation_url: str


class InviteListItemPublic(BaseModel):
    """The admin-facing pending-invites list - never includes the token or
    activation_url (those were only ever shown once, at creation)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime


class InviteActivateRequest(BaseModel):
    token: str
    password: str
    full_name: str

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
        # Same rule as RegisterRequest.password (app/schemas/auth.py) -
        # deliberately not re-importing across modules for one shared
        # constant; both enforce the identical policy independently.
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if len(value) > 72:
            raise ValueError("Password must be at most 72 characters long")
        return value


class InviteActivateResponse(TokenResponse):
    """Activation immediately authenticates the new account - same shape as
    a normal login response, so the frontend can send the person straight
    to their dashboard without a second round trip."""
