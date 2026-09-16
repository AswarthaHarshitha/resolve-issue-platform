"""Issue creation, retrieval, and status-transition business logic.

Authorization here is deliberately coarse-grained for Phase 4: a USER may
only see their own issues; a RESOLVER or ADMIN may see and transition any
issue. There is no team-scoped restriction yet because there is nothing to
scope by - routing (which sets an issue's current_team_id) doesn't exist
until Phase 5, and Phase 7 is where resolver access gets narrowed to "only
issues assigned to my team." This is a documented, intentional simplification
(DECISIONS.md D24), not an oversight.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.roles import RoleName
from app.models.enums import IssueStatus, StatusChangeTrigger
from app.models.issue import Issue
from app.models.issue_status_history import IssueStatusHistory
from app.models.user import User
from app.repositories import issue_repository
from app.services.status_transition_rules import is_transition_allowed

_STAFF_ROLES = (RoleName.RESOLVER, RoleName.ADMIN)


class IssueNotFoundError(Exception):
    pass


class IssueAccessDeniedError(Exception):
    pass


class InvalidStatusTransitionError(Exception):
    def __init__(self, current: IssueStatus, target: IssueStatus):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value} to {target.value}")


def create_issue(db: Session, *, owner: User, title: str, description: str) -> Issue:
    """Creates the issue, commits, and returns - full stop. Triggering AI
    analysis as a background task is added in Phase 5 once an AIProvider
    exists to call; there is nothing to fabricate or stub out here in the
    meantime (issue.ai_analysis_status already defaults to PENDING via the
    column default from Phase 2)."""
    issue = issue_repository.create_issue(db, owner_id=owner.id, title=title, description=description)
    db.add(
        IssueStatusHistory(
            issue_id=issue.id,
            previous_status=None,
            new_status=IssueStatus.OPEN,
            trigger=StatusChangeTrigger.SYSTEM_CREATE,
            changed_by_id=owner.id,
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def _can_view_issue(issue: Issue, user: User) -> bool:
    if user.role.name in _STAFF_ROLES:
        return True
    return issue.owner_id == user.id


def get_issue_for_user(db: Session, *, issue_id: UUID, current_user: User) -> Issue:
    issue = issue_repository.get_issue_by_id(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()
    if not _can_view_issue(issue, current_user):
        raise IssueAccessDeniedError()
    return issue


def list_issues_for_user(
    db: Session,
    *,
    current_user: User,
    page: int,
    page_size: int,
    status_filter: Optional[IssueStatus],
) -> Tuple[List[Issue], int]:
    # A USER's results are forced to their own issues regardless of what a
    # client might otherwise try to request - there is no "owner_id" query
    # parameter a USER can pass to see someone else's issues.
    owner_id = None if current_user.role.name in _STAFF_ROLES else current_user.id
    return issue_repository.list_issues(
        db, owner_id=owner_id, status_filter=status_filter, page=page, page_size=page_size
    )


def transition_status(
    db: Session,
    *,
    issue_id: UUID,
    target_status: IssueStatus,
    current_user: User,
    note: Optional[str] = None,
) -> Issue:
    if current_user.role.name not in _STAFF_ROLES:
        raise IssueAccessDeniedError()

    issue = issue_repository.get_issue_by_id_for_update(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()

    if not is_transition_allowed(issue.status, target_status):
        raise InvalidStatusTransitionError(issue.status, target_status)

    previous_status = issue.status
    issue.status = target_status
    if target_status == IssueStatus.RESOLVED:
        issue.resolved_at = datetime.now(timezone.utc)

    db.add(
        IssueStatusHistory(
            issue_id=issue.id,
            previous_status=previous_status,
            new_status=target_status,
            trigger=StatusChangeTrigger.MANUAL,
            changed_by_id=current_user.id,
            note=note,
        )
    )
    db.commit()
    db.refresh(issue)
    return issue
