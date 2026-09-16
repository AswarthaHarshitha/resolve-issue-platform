"""POST /api/v1/issues/{id}/reanalyze - manual recovery from a FAILED/stuck
analysis (DECISIONS.md D13, D14): access control, cooldown, in-progress
conflict, and the scope rule that reanalysis on an already-routed issue only
records a fresh suggestion without re-routing."""

from datetime import datetime, timedelta, timezone

from app.models.ai_analysis_result import AIAnalysisResult
from app.models.enums import AIAnalysisResultStatus, AIAnalysisStatus, IssuePriority, IssueStatus
from app.services.ai_analysis_service import run_ai_analysis
from app.services.ai_provider import AISuggestion
from tests.auth_helpers import auth_headers
from tests.factories import make_category, make_issue, make_user_with_role
from tests.fake_ai_provider import FakeAIProvider


def _create_via_api(client, user):
    response = client.post(
        "/api/v1/issues", json={"title": "Sample issue", "description": "Sample description."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_user_cannot_trigger_reanalysis(client, db_session):
    owner = make_user_with_role(db_session, "USER", "reanalyze-owner1@example.com")
    issue = _create_via_api(client, owner)

    response = client.post(f"/api/v1/issues/{issue['id']}/reanalyze", headers=auth_headers(owner))

    assert response.status_code == 403


def test_resolver_can_trigger_reanalysis(client, db_session):
    owner = make_user_with_role(db_session, "USER", "reanalyze-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reanalyze-resolver1@example.com")
    issue = _create_via_api(client, owner)

    response = client.post(f"/api/v1/issues/{issue['id']}/reanalyze", headers=auth_headers(resolver))

    assert response.status_code == 202
    assert response.json()["ai_analysis_status"] == "PENDING"


def test_reanalyze_nonexistent_issue_returns_404(client, db_session):
    import uuid

    resolver = make_user_with_role(db_session, "RESOLVER", "reanalyze-resolver2@example.com")

    response = client.post(f"/api/v1/issues/{uuid.uuid4()}/reanalyze", headers=auth_headers(resolver))

    assert response.status_code == 404


def test_reanalyze_rejected_while_already_processing(client, db_session):
    owner = make_user_with_role(db_session, "USER", "reanalyze-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reanalyze-resolver3@example.com")
    issue = _create_via_api(client, owner)

    import uuid as uuid_module

    from app.models.issue import Issue

    db_session.query(Issue).filter(Issue.id == uuid_module.UUID(issue["id"])).update(
        {"ai_analysis_status": AIAnalysisStatus.PROCESSING}
    )
    db_session.flush()

    response = client.post(f"/api/v1/issues/{issue['id']}/reanalyze", headers=auth_headers(resolver))

    assert response.status_code == 409


def test_reanalyze_blocked_immediately_after_a_recent_attempt(client, db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "reanalyze-owner4@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reanalyze-resolver4@example.com")
    issue = _create_via_api(client, owner)
    db_session.commit()

    import uuid as uuid_module

    issue_id = uuid_module.UUID(issue["id"])
    run_ai_analysis(issue_id, provider=FakeAIProvider(raise_provider_error=True), session_factory=ai_session_factory)

    response = client.post(f"/api/v1/issues/{issue['id']}/reanalyze", headers=auth_headers(resolver))
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_reanalyze_succeeds_once_cooldown_has_elapsed(client, db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "reanalyze-owner4b@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reanalyze-resolver4b@example.com")
    issue = _create_via_api(client, owner)
    db_session.commit()

    import uuid as uuid_module

    issue_id = uuid_module.UUID(issue["id"])
    run_ai_analysis(issue_id, provider=FakeAIProvider(raise_provider_error=True), session_factory=ai_session_factory)

    # Backdate the recorded attempt past the cooldown window rather than
    # sleeping in the test.
    attempt = db_session.query(AIAnalysisResult).filter_by(issue_id=issue_id).one()
    attempt.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    response = client.post(f"/api/v1/issues/{issue['id']}/reanalyze", headers=auth_headers(resolver))
    assert response.status_code == 202


def test_reanalyze_preserves_prior_attempts_as_history(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "reanalyze-owner5@example.com")
    make_category(db_session, "IT")
    issue = make_issue(db_session, owner)
    db_session.commit()

    run_ai_analysis(
        issue.id,
        provider=FakeAIProvider(raise_format_error=True),
        session_factory=ai_session_factory,
    )
    run_ai_analysis(
        issue.id,
        provider=FakeAIProvider(
            suggestion=AISuggestion(category="IT", sub_category=None, priority="LOW", summary="s", reasoning="r")
        ),
        session_factory=ai_session_factory,
    )

    results = (
        db_session.query(AIAnalysisResult)
        .filter_by(issue_id=issue.id)
        .order_by(AIAnalysisResult.attempt_number)
        .all()
    )
    assert len(results) == 2
    assert results[0].attempt_number == 1
    assert results[0].status == AIAnalysisResultStatus.FAILED
    assert results[1].attempt_number == 2
    assert results[1].status == AIAnalysisResultStatus.COMPLETED


def test_reanalyze_on_already_routed_issue_does_not_re_route(db_session, ai_session_factory):
    """DECISIONS.md D13 scope rule: once an issue has progressed past OPEN
    (already routed, possibly hand-adjusted), reanalysis only records a
    fresh AI opinion - it must not silently change the team/priority a
    human may already be acting on."""
    from tests.factories import make_sub_category, make_team
    from app.models.routing_rule import RoutingRule

    owner = make_user_with_role(db_session, "USER", "reanalyze-owner6@example.com")
    category = make_category(db_session, "IT")
    make_sub_category(db_session, category, "Network")
    team = make_team(db_session, "IT Support")
    db_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
    # Deliberately avoids escalation keywords (e.g. "outage") so the
    # priority this test asserts on reflects the AI's suggestion, not
    # RoutingService's deterministic escalation rule (covered separately in
    # test_ai_analysis.py::test_deterministic_priority_escalation_overrides_ai_suggestion).
    issue = make_issue(
        db_session, owner, title="Minor UI glitch", description="A dropdown shows extra whitespace."
    )
    db_session.commit()

    # First analysis routes the issue normally.
    run_ai_analysis(
        issue.id,
        provider=FakeAIProvider(
            suggestion=AISuggestion(
                category="IT", sub_category=None, priority="LOW", summary="s", reasoning="r"
            )
        ),
        session_factory=ai_session_factory,
    )
    db_session.refresh(issue)
    assert issue.status == IssueStatus.ASSIGNED
    assert issue.priority == IssuePriority.LOW
    original_team_id = issue.current_team_id

    # A human then manually progresses the issue further.
    issue.status = IssueStatus.IN_PROGRESS
    db_session.commit()

    # Reanalysis now suggests a totally different, higher priority.
    issue.ai_analysis_status = AIAnalysisStatus.PENDING
    db_session.commit()
    run_ai_analysis(
        issue.id,
        provider=FakeAIProvider(
            suggestion=AISuggestion(
                category="IT", sub_category=None, priority="CRITICAL", summary="s2", reasoning="r2"
            )
        ),
        session_factory=ai_session_factory,
    )

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.COMPLETED
    # Nothing about the routed/human-progressed state changed:
    assert issue.status == IssueStatus.IN_PROGRESS
    assert issue.priority == IssuePriority.LOW
    assert issue.current_team_id == original_team_id

    # But the fresh suggestion IS recorded for a human to review.
    results = db_session.query(AIAnalysisResult).filter_by(issue_id=issue.id).order_by(
        AIAnalysisResult.attempt_number
    ).all()
    assert len(results) == 2
    assert results[1].matched_priority == IssuePriority.CRITICAL
