from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import IssueStatus
from app.models.issue import Issue


def create_issue(db: Session, *, owner_id: UUID, title: str, description: str) -> Issue:
    issue = Issue(owner_id=owner_id, title=title, description=description)
    db.add(issue)
    db.flush()
    return issue


def get_issue_by_id(db: Session, issue_id: UUID) -> Optional[Issue]:
    return db.get(Issue, issue_id)


def get_issue_by_id_for_update(db: Session, issue_id: UUID) -> Optional[Issue]:
    """Locks the row for the duration of the caller's transaction
    (`SELECT ... FOR UPDATE`), so a concurrent transition request on the same
    issue blocks until this one commits or rolls back, and then reads
    whatever state this one actually left behind - never a stale value read
    before this transaction started. See DECISIONS.md D12."""
    stmt = select(Issue).where(Issue.id == issue_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def list_issues(
    db: Session,
    *,
    owner_id: Optional[UUID],
    status_filter: Optional[IssueStatus],
    page: int,
    page_size: int,
) -> Tuple[List[Issue], int]:
    filters = []
    if owner_id is not None:
        filters.append(Issue.owner_id == owner_id)
    if status_filter is not None:
        filters.append(Issue.status == status_filter)

    count_stmt = select(func.count()).select_from(Issue)
    for condition in filters:
        count_stmt = count_stmt.where(condition)
    total = db.execute(count_stmt).scalar_one()

    stmt = select(Issue)
    for condition in filters:
        stmt = stmt.where(condition)
    stmt = stmt.order_by(Issue.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(db.execute(stmt).scalars().all())

    return items, total
