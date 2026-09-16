from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import IssueStatus
from app.models.user import User
from app.schemas.issue import (
    IssueCreateRequest,
    IssueListResponse,
    IssuePublic,
    IssueStatusUpdateRequest,
)
from app.services import ai_analysis_service, issue_service
from app.services.ai_analysis_service import run_ai_analysis

router = APIRouter(prefix="/issues", tags=["issues"])
settings = get_settings()


@router.post("", response_model=IssuePublic, status_code=status.HTTP_201_CREATED)
def create_issue(
    payload: IssueCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IssuePublic:
    issue = issue_service.create_issue(
        db, owner=current_user, title=payload.title, description=payload.description
    )
    # Issue creation has already committed and will return successfully
    # regardless of what happens here - AI analysis runs after the response,
    # in its own DB session (DECISIONS.md D1, D3, D4).
    background_tasks.add_task(run_ai_analysis, issue.id)
    return issue


@router.get("", response_model=IssueListResponse)
def list_issues(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[IssueStatus] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IssueListResponse:
    items, total = issue_service.list_issues_for_user(
        db, current_user=current_user, page=page, page_size=page_size, status_filter=status_filter
    )
    return IssueListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{issue_id}", response_model=IssuePublic)
def get_issue(
    issue_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IssuePublic:
    try:
        return issue_service.get_issue_for_user(db, issue_id=issue_id, current_user=current_user)
    except issue_service.IssueNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    except issue_service.IssueAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this issue"
        )


@router.patch("/{issue_id}/status", response_model=IssuePublic)
def update_issue_status(
    issue_id: UUID,
    payload: IssueStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IssuePublic:
    try:
        return issue_service.transition_status(
            db,
            issue_id=issue_id,
            target_status=payload.status,
            current_user=current_user,
            note=payload.note,
        )
    except issue_service.IssueNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    except issue_service.IssueAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to change this issue's status",
        )
    except issue_service.InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{issue_id}/reanalyze", response_model=IssuePublic, status_code=status.HTTP_202_ACCEPTED)
def reanalyze_issue(
    issue_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IssuePublic:
    try:
        issue = ai_analysis_service.request_reanalysis(
            db,
            issue_id=issue_id,
            current_user=current_user,
            cooldown_seconds=settings.ai_reanalyze_cooldown_seconds,
        )
    except issue_service.IssueNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    except ai_analysis_service.ReanalyzeAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to trigger reanalysis on this issue",
        )
    except ai_analysis_service.ReanalyzeInProgressError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="AI analysis is already in progress for this issue"
        )
    except ai_analysis_service.ReanalyzeCooldownError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait {exc.retry_after_seconds} seconds before requesting another analysis",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    background_tasks.add_task(run_ai_analysis, issue.id)
    return issue
