from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import IssuePriority
from app.schemas.issue import CategoryPublic, SubCategoryPublic
from app.schemas.user import TeamPublic


class TeamCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TeamAdminPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime


class CategoryCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value


class CategoryUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SubCategoryPublicAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool


class CategoryAdminPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str]
    is_active: bool
    sub_categories: list[SubCategoryPublicAdmin] = []


class SubCategoryCreateRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value


class SubCategoryUpdateRequest(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


class RoutingRuleCreateRequest(BaseModel):
    category_id: UUID
    sub_category_id: Optional[UUID] = None
    team_id: UUID


class RoutingRuleUpdateRequest(BaseModel):
    team_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class RoutingRuleAdminPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: CategoryPublic
    sub_category: Optional[SubCategoryPublic] = None
    team: TeamPublic
    is_active: bool


class SLARuleCreateRequest(BaseModel):
    category_id: UUID
    priority: IssuePriority
    first_response_minutes: int
    resolution_minutes: int

    @field_validator("first_response_minutes", "resolution_minutes")
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be a positive number of minutes")
        return value


class SLARuleUpdateRequest(BaseModel):
    first_response_minutes: Optional[int] = None
    resolution_minutes: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("first_response_minutes", "resolution_minutes")
    @classmethod
    def validate_positive(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError("must be a positive number of minutes")
        return value


class SLARuleAdminPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: CategoryPublic
    priority: IssuePriority
    first_response_minutes: int
    resolution_minutes: int
    is_active: bool


class UserAdminUpdateRequest(BaseModel):
    """No `role`/`team_id` string-typos silently accepted - role is
    validated against the real roles table, not just any string (DECISIONS.md D42)."""

    role: Optional[str] = None
    team_id: Optional[UUID] = None
    is_active: Optional[bool] = None
