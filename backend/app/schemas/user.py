from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RolePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str


class TeamPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class UserPublic(BaseModel):
    """Safe user representation for API responses. Deliberately excludes
    password_hash and anything else internal - this is the only shape a
    User is ever allowed to leave the backend in."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    is_active: bool
    role: RolePublic
    team: Optional[TeamPublic] = None
    created_at: datetime
