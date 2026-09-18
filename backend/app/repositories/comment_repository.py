from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.issue_comment import IssueComment


def create_comment(db: Session, *, issue_id: UUID, author_id: UUID, body: str) -> IssueComment:
    comment = IssueComment(issue_id=issue_id, author_id=author_id, body=body)
    db.add(comment)
    db.flush()
    return comment


def list_comments_for_issue(db: Session, issue_id: UUID) -> List[IssueComment]:
    stmt = select(IssueComment).where(IssueComment.issue_id == issue_id).order_by(IssueComment.created_at)
    return list(db.execute(stmt).scalars().all())
