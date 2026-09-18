"""Dashboard summary metrics - every number here comes from a real query
against persisted data, never a placeholder (project rule: "no fake
numbers, use real persisted data"). Scoped by role exactly like issue
listing (DECISIONS.md D41): a USER's numbers are their own issues; a
RESOLVER's are their team's plus unassigned; an ADMIN's are global."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.roles import RoleName
from app.models.enums import AIAnalysisStatus, IssuePriority, IssueStatus
from app.models.issue import Issue
from app.models.sla_record import SLARecord
from app.models.team import Team
from app.models.user import User
from app.services.sla_service import compute_sla_status

_OPEN_STATUSES = (
    IssueStatus.OPEN,
    IssueStatus.TRIAGED,
    IssueStatus.ASSIGNED,
    IssueStatus.IN_PROGRESS,
    IssueStatus.WAITING_FOR_USER,
)


@dataclass
class DashboardSummary:
    open_requests: int
    high_priority: int
    sla_at_risk: int
    resolved_today: int


def _scope_filters(current_user: User):
    if current_user.role.name == RoleName.ADMIN:
        return []
    if current_user.role.name == RoleName.RESOLVER:
        return [or_(Issue.current_team_id.is_(None), Issue.current_team_id == current_user.team_id)]
    return [Issue.owner_id == current_user.id]


def _open_issues_with_sla_in_scope(db: Session, current_user: User) -> List[Issue]:
    """Shared by the at-risk count (get_summary) and the at-risk list
    (get_at_risk_issues) so the two can never disagree about which issues
    qualify."""
    stmt = select(Issue).join(SLARecord).where(Issue.status.in_(_OPEN_STATUSES))
    for condition in _scope_filters(current_user):
        stmt = stmt.where(condition)
    return list(db.execute(stmt).scalars().all())


def get_summary(db: Session, current_user: User) -> DashboardSummary:
    scope = _scope_filters(current_user)

    open_stmt = select(func.count()).select_from(Issue).where(Issue.status.in_(_OPEN_STATUSES))
    for condition in scope:
        open_stmt = open_stmt.where(condition)
    open_requests = db.execute(open_stmt).scalar_one()

    high_priority_stmt = (
        select(func.count())
        .select_from(Issue)
        .where(Issue.status.in_(_OPEN_STATUSES))
        .where(Issue.priority.in_((IssuePriority.HIGH, IssuePriority.CRITICAL)))
    )
    for condition in scope:
        high_priority_stmt = high_priority_stmt.where(condition)
    high_priority = db.execute(high_priority_stmt).scalar_one()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_today_stmt = (
        select(func.count()).select_from(Issue).where(Issue.resolved_at.is_not(None)).where(Issue.resolved_at >= today_start)
    )
    for condition in scope:
        resolved_today_stmt = resolved_today_stmt.where(condition)
    resolved_today = db.execute(resolved_today_stmt).scalar_one()

    # "At risk" requires the pause-aware computation, not a plain column
    # comparison - done in Python over the (small, MVP-scale) set of open
    # issues that actually have an SLA record. Documented as a scale
    # consideration, not silently pretended to be free at any volume.
    issues_with_sla = _open_issues_with_sla_in_scope(db, current_user)
    sla_at_risk = sum(1 for issue in issues_with_sla if _is_at_risk_or_breached(issue))

    return DashboardSummary(
        open_requests=open_requests,
        high_priority=high_priority,
        sla_at_risk=sla_at_risk,
        resolved_today=resolved_today,
    )


def _is_at_risk_or_breached(issue: Issue) -> bool:
    status = compute_sla_status(issue.sla_record)
    return (
        status.first_response_at_risk
        or status.first_response_breached
        or status.resolution_at_risk
        or status.resolution_breached
    )


def get_at_risk_issues(db: Session, current_user: User, limit: int = 10) -> List[Issue]:
    """The actual list behind the summary's sla_at_risk count - a
    prioritized worklist, not just a number (project UI spec: "SLA At Risk
    -> prioritized list")."""
    issues = _open_issues_with_sla_in_scope(db, current_user)
    at_risk = [issue for issue in issues if _is_at_risk_or_breached(issue)]
    at_risk.sort(key=lambda issue: issue.sla_record.resolution_deadline_at)
    return at_risk[:limit]


@dataclass
class DashboardBreakdown:
    status_counts: Dict[str, int] = field(default_factory=dict)
    priority_counts: Dict[str, int] = field(default_factory=dict)
    ai_analysis_failures: int = 0
    team_workload: Dict[str, int] = field(default_factory=dict)


def get_breakdown(db: Session, current_user: User) -> DashboardBreakdown:
    """Status/priority distribution and AI-failure count for the resolver
    and admin dashboards - team workload only for ADMIN, since it spans
    every team by definition."""
    scope = _scope_filters(current_user)

    status_stmt = select(Issue.status, func.count()).group_by(Issue.status)
    for condition in scope:
        status_stmt = status_stmt.where(condition)
    status_counts = {row[0].value: row[1] for row in db.execute(status_stmt).all()}

    priority_stmt = (
        select(Issue.priority, func.count()).where(Issue.status.in_(_OPEN_STATUSES)).group_by(Issue.priority)
    )
    for condition in scope:
        priority_stmt = priority_stmt.where(condition)
    priority_counts = {(row[0].value if row[0] else "UNSET"): row[1] for row in db.execute(priority_stmt).all()}

    ai_failures_stmt = select(func.count()).select_from(Issue).where(Issue.ai_analysis_status == AIAnalysisStatus.FAILED)
    for condition in scope:
        ai_failures_stmt = ai_failures_stmt.where(condition)
    ai_failures = db.execute(ai_failures_stmt).scalar_one()

    team_workload: Dict[str, int] = {}
    if current_user.role.name == RoleName.ADMIN:
        workload_stmt = (
            select(Team.name, func.count())
            .join(Issue, Issue.current_team_id == Team.id)
            .where(Issue.status.in_(_OPEN_STATUSES))
            .group_by(Team.name)
        )
        team_workload = {row[0]: row[1] for row in db.execute(workload_stmt).all()}

    return DashboardBreakdown(
        status_counts=status_counts,
        priority_counts=priority_counts,
        ai_analysis_failures=ai_failures,
        team_workload=team_workload,
    )
