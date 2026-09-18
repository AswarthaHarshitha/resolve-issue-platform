"""Assignment/reassignment (DECISIONS.md D7, D41). issue_assignments is
append-only - every change inserts a new row; issues.current_team_id/
current_resolver_id are a denormalized pointer to the latest one, updated
in the same transaction so they can never disagree with the history table.

An ADMIN may reassign an issue to any team and/or resolver. A RESOLVER may
only self-assign (pick up an issue already on their own team) - they can
neither reassign to a different team nor assign a different resolver.
Assignment is deliberately independent of status: reassigning an issue does
not itself change its business status."""

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.roles import RoleName
from app.models.issue import Issue
from app.models.issue_assignment import IssueAssignment
from app.models.user import User
from app.repositories import issue_repository


class AssignmentAccessDeniedError(Exception):
    pass


class InvalidAssignmentError(Exception):
    pass


def update_assignment(
    db: Session,
    *,
    issue_id: UUID,
    current_user: User,
    team_id: Optional[UUID],
    resolver_id: Optional[UUID],
    reason: Optional[str],
) -> Issue:
    from app.services.issue_service import IssueNotFoundError

    issue = issue_repository.get_issue_by_id_for_update(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()

    if current_user.role.name == RoleName.ADMIN:
        final_team_id = team_id if team_id is not None else issue.current_team_id
        final_resolver_id = resolver_id
    elif current_user.role.name == RoleName.RESOLVER:
        if team_id is not None and team_id != issue.current_team_id:
            raise AssignmentAccessDeniedError("Resolvers cannot change an issue's team")
        if resolver_id is not None and resolver_id != current_user.id:
            raise AssignmentAccessDeniedError("Resolvers can only assign themselves")
        if issue.current_team_id is None or issue.current_team_id != current_user.team_id:
            raise AssignmentAccessDeniedError("You can only pick up issues assigned to your own team")
        final_team_id = issue.current_team_id
        final_resolver_id = current_user.id
    else:
        raise AssignmentAccessDeniedError()

    if final_team_id is None:
        raise InvalidAssignmentError("An issue must have a team before it can have a resolver")

    if final_resolver_id is not None:
        resolver = db.get(User, final_resolver_id)
        if (
            resolver is None
            or resolver.role.name != RoleName.RESOLVER
            or resolver.team_id != final_team_id
        ):
            raise InvalidAssignmentError("The assigned resolver must belong to the issue's team")

    issue.current_team_id = final_team_id
    issue.current_resolver_id = final_resolver_id
    db.add(
        IssueAssignment(
            issue_id=issue.id,
            team_id=final_team_id,
            resolver_id=final_resolver_id,
            assigned_by_id=current_user.id,
            reason=reason,
        )
    )
    db.commit()
    db.refresh(issue)
    return issue
