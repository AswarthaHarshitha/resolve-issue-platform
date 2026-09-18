"""Issue comments, including the CRITICAL SPECIAL RULE (Phase 7 spec,
DECISIONS.md D11, D41): when the issue's own owner comments while it is
WAITING_FOR_USER, the backend atomically transitions it back to
IN_PROGRESS and closes the SLA pause - in the same transaction as the
comment insert, under the same row lock used for every other transition.
A resolver, admin, or anyone else commenting never triggers this - only
the submitting user's own reply does."""

from typing import List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import IssueStatus, StatusChangeTrigger
from app.models.issue import Issue
from app.models.issue_comment import IssueComment
from app.models.issue_status_history import IssueStatusHistory
from app.models.user import User
from app.repositories import comment_repository, issue_repository
from app.services import sla_service
from app.services.issue_service import IssueAccessDeniedError, IssueNotFoundError, can_access_issue


def add_comment(db: Session, *, issue_id: UUID, author: User, body: str) -> Tuple[IssueComment, Issue]:
    # Locked read: the WAITING_FOR_USER check below must see the issue's
    # true current state, not a value read before a concurrent transition
    # (DECISIONS.md D12) - the same guarantee every other issue mutation gets.
    issue = issue_repository.get_issue_by_id_for_update(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()
    if not can_access_issue(issue, author):
        raise IssueAccessDeniedError()

    comment = comment_repository.create_comment(db, issue_id=issue.id, author_id=author.id, body=body)

    if issue.status == IssueStatus.WAITING_FOR_USER and author.id == issue.owner_id:
        previous_status = issue.status
        issue.status = IssueStatus.IN_PROGRESS
        if issue.sla_record is not None:
            sla_service.close_pause(db, issue.sla_record)
        db.add(
            IssueStatusHistory(
                issue_id=issue.id,
                previous_status=previous_status,
                new_status=IssueStatus.IN_PROGRESS,
                trigger=StatusChangeTrigger.AUTO_USER_REPLY,
                changed_by_id=author.id,
            )
        )

    db.commit()
    db.refresh(comment)
    db.refresh(issue)
    return comment, issue


def list_comments(db: Session, *, issue_id: UUID, current_user: User) -> List[IssueComment]:
    issue = issue_repository.get_issue_by_id(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()
    if not can_access_issue(issue, current_user):
        raise IssueAccessDeniedError()
    return comment_repository.list_comments_for_issue(db, issue_id)
