from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import IssueStatus
from app.models.issue import Issue
from app.models.issue_status_history import IssueStatusHistory
from app.models.sla_record import SLARecord

# build_issue_public touches every one of these relationships (directly, or
# via compute_sla_status's sla_record.pause_intervals) for every issue it
# serializes. Without eager loading, GET /issues would issue one extra
# lazy-load query per relationship per issue - up to ~600 extra round trips
# for a single max-page-size (100) request (Phase 9 performance finding).
_ISSUE_LIST_EAGER_OPTIONS = (
    selectinload(Issue.owner),
    selectinload(Issue.category),
    selectinload(Issue.sub_category),
    selectinload(Issue.current_team),
    selectinload(Issue.current_resolver),
    selectinload(Issue.sla_record).selectinload(SLARecord.pause_intervals),
)


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
    team_scope: Optional[UUID] = None,
    include_unassigned_for_team_scope: bool = False,
) -> Tuple[List[Issue], int]:
    filters = []
    if owner_id is not None:
        filters.append(Issue.owner_id == owner_id)
    if status_filter is not None:
        filters.append(Issue.status == status_filter)
    if team_scope is not None or include_unassigned_for_team_scope:
        # Mirrors issue_service.can_access_issue exactly: a resolver's list
        # must show precisely what they're also allowed to open individually.
        if include_unassigned_for_team_scope:
            filters.append(or_(Issue.current_team_id.is_(None), Issue.current_team_id == team_scope))
        else:
            filters.append(Issue.current_team_id == team_scope)

    count_stmt = select(func.count()).select_from(Issue)
    for condition in filters:
        count_stmt = count_stmt.where(condition)
    total = db.execute(count_stmt).scalar_one()

    stmt = select(Issue).options(*_ISSUE_LIST_EAGER_OPTIONS)
    for condition in filters:
        stmt = stmt.where(condition)
    stmt = stmt.order_by(Issue.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(db.execute(stmt).scalars().all())

    return items, total


def list_status_history(db: Session, issue_id: UUID) -> List[IssueStatusHistory]:
    stmt = (
        select(IssueStatusHistory)
        .where(IssueStatusHistory.issue_id == issue_id)
        .order_by(IssueStatusHistory.created_at)
    )
    return list(db.execute(stmt).scalars().all())
