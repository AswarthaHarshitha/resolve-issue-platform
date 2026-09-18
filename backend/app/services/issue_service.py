"""Issue creation, retrieval, and status-transition business logic.

Authorization (DECISIONS.md D29, narrowed in D41): a USER may only see/act
on their own issues. An ADMIN may see/act on any issue. A RESOLVER may
see/act on an issue only if it is unassigned (current_team_id is NULL - so
nothing is ever invisible while waiting to be routed/picked up) or assigned
to their own team - never another team's issue.
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
from app.services import sla_service
from app.services.status_transition_rules import is_transition_allowed


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


def can_access_issue(issue: Issue, user: User) -> bool:
    """The one place issue-level authorization is decided - reused by
    viewing, commenting, and transitioning, so the rule can't drift between
    them (DECISIONS.md D41)."""
    if user.role.name == RoleName.ADMIN:
        return True
    if user.role.name == RoleName.RESOLVER:
        # Unassigned issues stay visible to every resolver (so someone can
        # notice and pick them up - "not silently dropped," per the
        # original architecture review); an issue assigned to a specific
        # team is only visible to that team's resolvers.
        return issue.current_team_id is None or issue.current_team_id == user.team_id
    return issue.owner_id == user.id


def get_issue_for_user(db: Session, *, issue_id: UUID, current_user: User) -> Issue:
    issue = issue_repository.get_issue_by_id(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()
    if not can_access_issue(issue, current_user):
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
    if current_user.role.name == RoleName.ADMIN:
        owner_id, team_scope = None, None
    elif current_user.role.name == RoleName.RESOLVER:
        # Their own team's issues, plus anything still unassigned - matches
        # can_access_issue exactly, so "what I can list" and "what I can
        # open" never disagree.
        owner_id, team_scope = None, current_user.team_id
    else:
        owner_id, team_scope = current_user.id, None

    return issue_repository.list_issues(
        db,
        owner_id=owner_id,
        team_scope=team_scope,
        include_unassigned_for_team_scope=current_user.role.name == RoleName.RESOLVER,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )


def transition_status(
    db: Session,
    *,
    issue_id: UUID,
    target_status: IssueStatus,
    current_user: User,
    note: Optional[str] = None,
) -> Issue:
    if current_user.role.name not in (RoleName.RESOLVER, RoleName.ADMIN):
        raise IssueAccessDeniedError()

    issue = issue_repository.get_issue_by_id_for_update(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()

    if not can_access_issue(issue, current_user):
        raise IssueAccessDeniedError()

    if not is_transition_allowed(issue.status, target_status):
        raise InvalidStatusTransitionError(issue.status, target_status)

    previous_status = issue.status
    issue.status = target_status
    if target_status == IssueStatus.RESOLVED:
        issue.resolved_at = datetime.now(timezone.utc)

    # SLA pause/resume is atomic with the status change that causes it - it
    # happens inside the same row-locked transaction as the transition
    # itself, so the two can never drift apart (DECISIONS.md D40).
    if issue.sla_record is not None:
        if target_status == IssueStatus.WAITING_FOR_USER:
            sla_service.open_pause(db, issue.sla_record)
        elif previous_status == IssueStatus.WAITING_FOR_USER and target_status == IssueStatus.IN_PROGRESS:
            sla_service.close_pause(db, issue.sla_record)

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


def confirm_resolution(db: Session, *, issue_id: UUID, current_user: User) -> Issue:
    """The only path to CLOSED (DECISIONS.md D9, D30) - the issue's own
    owner, and only the owner, may confirm. A resolver/admin marking an
    issue RESOLVED (via transition_status) never closes it by itself."""
    issue = issue_repository.get_issue_by_id_for_update(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()
    if issue.owner_id != current_user.id:
        raise IssueAccessDeniedError()
    if issue.status != IssueStatus.RESOLVED:
        raise InvalidStatusTransitionError(issue.status, IssueStatus.CLOSED)

    previous_status = issue.status
    issue.status = IssueStatus.CLOSED
    issue.closed_at = datetime.now(timezone.utc)
    db.add(
        IssueStatusHistory(
            issue_id=issue.id,
            previous_status=previous_status,
            new_status=IssueStatus.CLOSED,
            trigger=StatusChangeTrigger.MANUAL,
            changed_by_id=current_user.id,
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def reject_resolution(db: Session, *, issue_id: UUID, current_user: User, note: Optional[str] = None) -> Issue:
    """The owner disagrees the issue is actually resolved - returns it to
    IN_PROGRESS (an active state a resolver can act on again) rather than
    leaving it stuck at RESOLVED with nowhere to go. Only the owner may
    reject, for the same reason only the owner may confirm."""
    issue = issue_repository.get_issue_by_id_for_update(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()
    if issue.owner_id != current_user.id:
        raise IssueAccessDeniedError()
    if issue.status != IssueStatus.RESOLVED:
        raise InvalidStatusTransitionError(issue.status, IssueStatus.IN_PROGRESS)

    previous_status = issue.status
    issue.status = IssueStatus.IN_PROGRESS
    issue.resolved_at = None
    db.add(
        IssueStatusHistory(
            issue_id=issue.id,
            previous_status=previous_status,
            new_status=IssueStatus.IN_PROGRESS,
            trigger=StatusChangeTrigger.MANUAL,
            changed_by_id=current_user.id,
            note=note,
        )
    )
    db.commit()
    db.refresh(issue)
    return issue
