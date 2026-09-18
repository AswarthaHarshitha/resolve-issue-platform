from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import AIAnalysisStatus, IssuePriority, IssueStatus
from app.schemas.user import TeamPublic

if TYPE_CHECKING:
    from app.models.issue import Issue

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


class SLAStatusPublic(BaseModel):
    """Computed, not stored - see app/services/sla_service.py. Every field
    here is deterministically reconstructable from sla_records/
    sla_pause_intervals alone (DECISIONS.md D40), so this is always
    reproducible after a restart, never dependent on in-memory state."""

    first_response_deadline_at: datetime
    resolution_deadline_at: datetime
    effective_elapsed_seconds: int
    accumulated_pause_seconds: int
    is_paused: bool
    first_response_met: bool
    resolution_met: bool
    first_response_at_risk: bool
    first_response_breached: bool
    resolution_at_risk: bool
    resolution_breached: bool


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
    sla: Optional[SLAStatusPublic] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


def build_issue_public(issue: "Issue") -> IssuePublic:
    """The one place an Issue ORM object becomes an IssuePublic response -
    used by every route that returns an issue, so `sla` (computed, not a
    plain ORM attribute IssuePublic.model_validate could pick up on its own)
    is never forgotten on one endpoint but not another."""
    from app.services.sla_service import compute_sla_status

    public = IssuePublic.model_validate(issue)
    if issue.sla_record is not None:
        status = compute_sla_status(issue.sla_record)
        public.sla = SLAStatusPublic(
            first_response_deadline_at=status.first_response_deadline_at,
            resolution_deadline_at=status.resolution_deadline_at,
            effective_elapsed_seconds=status.effective_elapsed_seconds,
            accumulated_pause_seconds=status.accumulated_pause_seconds,
            is_paused=status.is_paused,
            first_response_met=status.first_response_met,
            resolution_met=status.resolution_met,
            first_response_at_risk=status.first_response_at_risk,
            first_response_breached=status.first_response_breached,
            resolution_at_risk=status.resolution_at_risk,
            resolution_breached=status.resolution_breached,
        )
    return public


class IssueListResponse(BaseModel):
    items: List[IssuePublic]
    total: int
    page: int
    page_size: int


class AssignmentUpdateRequest(BaseModel):
    """All fields optional: a RESOLVER self-assigning sends neither
    team_id nor resolver_id (the service fills in "my team" / "myself");
    an ADMIN reassigning sends whichever of the two is actually changing."""

    team_id: Optional[UUID] = None
    resolver_id: Optional[UUID] = None
    reason: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


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
