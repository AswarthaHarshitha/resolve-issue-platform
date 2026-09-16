from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import AIAnalysisStatus, IssuePriority, IssueStatus
from app.schemas.user import TeamPublic

_TITLE_MAX_LENGTH = 200
_DESCRIPTION_MAX_LENGTH = 5000


class UserSummary(BaseModel):
    """Minimal user shape for nesting inside an issue (owner/current_resolver) -
    intentionally lighter than UserPublic since role/is_active aren't relevant
    in this context."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: str


class CategoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class SubCategoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class IssueCreateRequest(BaseModel):
    title: str
    description: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be empty")
        if len(value) > _TITLE_MAX_LENGTH:
            raise ValueError(f"title must be at most {_TITLE_MAX_LENGTH} characters")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be empty")
        if len(value) > _DESCRIPTION_MAX_LENGTH:
            raise ValueError(f"description must be at most {_DESCRIPTION_MAX_LENGTH} characters")
        return value


class IssuePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    status: IssueStatus
    ai_analysis_status: AIAnalysisStatus
    priority: Optional[IssuePriority] = None
    category: Optional[CategoryPublic] = None
    sub_category: Optional[SubCategoryPublic] = None
    owner: UserSummary
    current_team: Optional[TeamPublic] = None
    current_resolver: Optional[UserSummary] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class IssueListResponse(BaseModel):
    items: List[IssuePublic]
    total: int
    page: int
    page_size: int


class IssueStatusUpdateRequest(BaseModel):
    """Only the target status is accepted - never a client-supplied "current"
    status. The service layer loads the real current status under a row
    lock and validates against that, never anything the client claims
    (DECISIONS.md D12)."""

    status: IssueStatus
    note: Optional[str] = None

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None
