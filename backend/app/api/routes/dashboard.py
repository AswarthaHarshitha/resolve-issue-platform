from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardBreakdownPublic, DashboardSummaryPublic
from app.schemas.issue import IssuePublic, build_issue_public
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryPublic)
def get_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardSummaryPublic:
    return dashboard_service.get_summary(db, current_user)


@router.get("/at-risk-issues", response_model=list[IssuePublic])
def get_at_risk_issues(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[IssuePublic]:
    issues = dashboard_service.get_at_risk_issues(db, current_user, limit=limit)
    return [build_issue_public(issue) for issue in issues]


@router.get("/breakdown", response_model=DashboardBreakdownPublic)
def get_breakdown(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardBreakdownPublic:
    return dashboard_service.get_breakdown(db, current_user)
