"""Orchestrates one AI classification attempt end to end, running in a
FastAPI BackgroundTask with its own database session - never the
request-scoped session (DECISIONS.md D1, D3, D4, D14).

Flow: load issue -> PROCESSING -> call AIProvider -> validate -> (if the
issue is still OPEN) route -> COMPLETED. Any failure anywhere in that chain
is caught, recorded, and leaves ai_analysis_status=FAILED with the issue
otherwise untouched - never a crashed background task, never a fabricated
result (DECISIONS.md D5)."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.roles import RoleName
from app.db.session import SessionLocal
from app.models.ai_analysis_result import AIAnalysisResult
from app.models.enums import AIAnalysisResultStatus, AIAnalysisStatus
from app.models.issue import Issue
from app.models.user import User
from app.repositories import issue_repository
from app.services.ai_provider import AIProvider, AIProviderError, AIResponseFormatError, get_default_provider
from app.services.ai_validation import AIValidationError, validate_ai_suggestion
from app.services.issue_service import IssueAccessDeniedError, IssueNotFoundError, can_access_issue
from app.services.routing_service import route_issue

logger = logging.getLogger(__name__)


class ReanalyzeAccessDeniedError(Exception):
    pass


class ReanalyzeCooldownError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds


class ReanalyzeInProgressError(Exception):
    pass


def get_latest_analysis_result(db: Session, *, issue_id: UUID, current_user: User):
    """The most recent classification attempt for an issue, for display on
    the issue detail page - `None` if AI analysis hasn't completed (or
    failed) yet at all. Access-gated the same way as everything else on
    the issue."""
    issue = issue_repository.get_issue_by_id(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()
    if not can_access_issue(issue, current_user):
        raise IssueAccessDeniedError()

    return (
        db.query(AIAnalysisResult)
        .filter(AIAnalysisResult.issue_id == issue_id)
        .order_by(AIAnalysisResult.attempt_number.desc())
        .first()
    )


def _next_attempt_number(db: Session, issue_id: UUID) -> int:
    last = (
        db.query(AIAnalysisResult)
        .filter(AIAnalysisResult.issue_id == issue_id)
        .order_by(AIAnalysisResult.attempt_number.desc())
        .first()
    )
    return (last.attempt_number + 1) if last else 1


def run_ai_analysis(
    issue_id: UUID,
    provider: Optional[AIProvider] = None,
    session_factory: Optional[Callable[[], Session]] = None,
) -> None:
    """Entry point called from a FastAPI BackgroundTask (or directly by
    tests, with a fake provider and/or a session bound to the test engine
    injected via session_factory). Opens and closes its own session - never
    reuses one from a request. `session_factory` defaults to the real
    production SessionLocal; tests override it so this runs against
    resolve_test instead of silently no-op'ing against the dev database."""
    db = (session_factory or SessionLocal)()
    try:
        issue = db.get(Issue, issue_id)
        if issue is None:
            return  # Issue was deleted between scheduling and running; nothing to do.

        issue.ai_analysis_status = AIAnalysisStatus.PROCESSING
        db.commit()

        attempt_number = _next_attempt_number(db, issue_id)
        active_provider = provider or get_default_provider()

        try:
            raw_suggestion = active_provider.classify(title=issue.title, description=issue.description)
        except (AIProviderError, AIResponseFormatError) as exc:
            _record_failure(db, issue, attempt_number, raw=None, error_message=str(exc))
            return

        try:
            validated = validate_ai_suggestion(db, raw_suggestion)
        except AIValidationError as exc:
            _record_failure(db, issue, attempt_number, raw=raw_suggestion, error_message=str(exc))
            return

        route_issue(db, issue=issue, validated=validated)

        db.add(
            AIAnalysisResult(
                issue_id=issue.id,
                attempt_number=attempt_number,
                status=AIAnalysisResultStatus.COMPLETED,
                raw_category=raw_suggestion.category,
                raw_sub_category=raw_suggestion.sub_category,
                raw_priority=raw_suggestion.priority,
                summary=validated.summary,
                reasoning=validated.reasoning,
                matched_category_id=validated.category_id,
                matched_sub_category_id=validated.sub_category_id,
                matched_priority=validated.priority,
            )
        )
        issue.ai_analysis_status = AIAnalysisStatus.COMPLETED
        db.commit()
    except Exception:
        # Nothing gets this far in normal operation (each expected failure
        # mode is already caught above) - this is the last line of defense
        # so a truly unexpected error (e.g. a database hiccup) still leaves
        # the issue in a well-defined FAILED state instead of stuck at
        # PROCESSING forever with a crashed, silent background task.
        logger.exception("Unexpected error during AI analysis for issue %s", issue_id)
        db.rollback()
        try:
            issue = db.get(Issue, issue_id)
            if issue is not None:
                issue.ai_analysis_status = AIAnalysisStatus.FAILED
                db.commit()
        except Exception:
            logger.exception("Failed to mark issue %s as AI_ANALYSIS FAILED after an error", issue_id)
    finally:
        db.close()


def _record_failure(db: Session, issue: Issue, attempt_number: int, raw, error_message: str) -> None:
    db.add(
        AIAnalysisResult(
            issue_id=issue.id,
            attempt_number=attempt_number,
            status=AIAnalysisResultStatus.FAILED,
            raw_category=getattr(raw, "category", None),
            raw_sub_category=getattr(raw, "sub_category", None),
            raw_priority=getattr(raw, "priority", None),
            summary=getattr(raw, "summary", None),
            reasoning=getattr(raw, "reasoning", None),
            error_message=error_message,
        )
    )
    issue.ai_analysis_status = AIAnalysisStatus.FAILED
    db.commit()


def request_reanalysis(
    db: Session,
    *,
    issue_id: UUID,
    current_user: User,
    cooldown_seconds: int,
) -> Issue:
    """Validates the reanalyze request (DECISIONS.md D13) and flips the
    issue to PENDING so a caller (the API route) can schedule
    run_ai_analysis as a background task. Does not run the analysis itself
    - that always happens out-of-request, same as issue creation."""
    if current_user.role.name not in (RoleName.RESOLVER, RoleName.ADMIN):
        raise ReanalyzeAccessDeniedError()

    issue = issue_repository.get_issue_by_id_for_update(db, issue_id)
    if issue is None:
        raise IssueNotFoundError()

    if issue.ai_analysis_status == AIAnalysisStatus.PROCESSING:
        raise ReanalyzeInProgressError()

    last_attempt = (
        db.query(AIAnalysisResult)
        .filter(AIAnalysisResult.issue_id == issue_id)
        .order_by(AIAnalysisResult.created_at.desc())
        .first()
    )
    if last_attempt is not None:
        elapsed = datetime.now(timezone.utc) - last_attempt.created_at
        if elapsed < timedelta(seconds=cooldown_seconds):
            retry_after = cooldown_seconds - int(elapsed.total_seconds())
            raise ReanalyzeCooldownError(retry_after_seconds=max(retry_after, 1))

    issue.ai_analysis_status = AIAnalysisStatus.PENDING
    db.commit()
    db.refresh(issue)
    return issue
