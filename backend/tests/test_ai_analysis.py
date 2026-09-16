"""AI classification pipeline: validation, deterministic routing, and the
architectural guarantee that AI is an advisor, never an authority
(DECISIONS.md D4-D6, D13, D29-D32)."""

from app.models.ai_analysis_result import AIAnalysisResult
from app.models.enums import AIAnalysisResultStatus, AIAnalysisStatus, IssuePriority, IssueStatus
from app.services.ai_analysis_service import run_ai_analysis
from app.services.ai_provider import AISuggestion
from tests.auth_helpers import auth_headers
from tests.factories import (
    make_category,
    make_issue,
    make_sla_rule,
    make_sub_category,
    make_team,
    make_user_with_role,
)
from tests.fake_ai_provider import FakeAIProvider


def _make_routing_rule(db_session, category, team):
    from app.models.routing_rule import RoutingRule

    rule = RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id)
    db_session.add(rule)
    db_session.flush()
    return rule


def test_valid_ai_response_completes_and_routes_the_issue(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "ai-owner1@example.com")
    category = make_category(db_session, "IT")
    sub_category = make_sub_category(db_session, category, "Network")
    team = make_team(db_session, "IT Support")
    _make_routing_rule(db_session, category, team)
    make_sla_rule(db_session, category, priority=IssuePriority.HIGH, first_response_minutes=60, resolution_minutes=1440)
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(
        suggestion=AISuggestion(
            category="IT",
            sub_category="Network",
            priority="HIGH",
            summary="Network is down for several users.",
            reasoning="Multiple users affected, matches IT/Network.",
        )
    )

    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.COMPLETED
    assert issue.status == IssueStatus.ASSIGNED
    assert issue.category_id == category.id
    assert issue.sub_category_id == sub_category.id
    assert issue.priority == IssuePriority.HIGH
    assert issue.current_team_id == team.id
    assert issue.sla_record is not None

    results = db_session.query(AIAnalysisResult).filter_by(issue_id=issue.id).all()
    assert len(results) == 1
    assert results[0].status == AIAnalysisResultStatus.COMPLETED
    assert results[0].matched_category_id == category.id


def test_provider_failure_leaves_issue_valid_and_marks_failed(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "ai-owner2@example.com")
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(raise_provider_error=True)
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.FAILED
    assert issue.status == IssueStatus.OPEN  # untouched - issue remains fully usable
    assert issue.category_id is None

    result = db_session.query(AIAnalysisResult).filter_by(issue_id=issue.id).one()
    assert result.status == AIAnalysisResultStatus.FAILED
    assert "outage" in result.error_message.lower() or "provider" in result.error_message.lower()


def test_malformed_ai_response_marks_failed_without_fabricating_a_result(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "ai-owner3@example.com")
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(raise_format_error=True)
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.FAILED
    assert issue.category_id is None
    assert issue.priority is None


def test_unknown_category_marks_failed_never_fabricates_a_match(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "ai-owner4@example.com")
    make_category(db_session, "IT")  # the only real category
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(
        suggestion=AISuggestion(
            category="Plumbing",  # does not exist
            sub_category=None,
            priority="HIGH",
            summary="Pipe burst.",
            reasoning="Water damage risk.",
        )
    )
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.FAILED
    assert issue.category_id is None
    assert issue.status == IssueStatus.OPEN

    result = db_session.query(AIAnalysisResult).filter_by(issue_id=issue.id).one()
    assert result.status == AIAnalysisResultStatus.FAILED
    assert result.raw_category == "Plumbing"
    assert "unknown category" in result.error_message.lower()


def test_unknown_sub_category_degrades_to_category_only_not_a_hard_failure(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "ai-owner5@example.com")
    category = make_category(db_session, "IT")
    make_sub_category(db_session, category, "Network")
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(
        suggestion=AISuggestion(
            category="IT",
            sub_category="Nonexistent Sub",
            priority="MEDIUM",
            summary="Some issue.",
            reasoning="Reasoning here.",
        )
    )
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.COMPLETED
    assert issue.category_id == category.id
    assert issue.sub_category_id is None


def test_invalid_priority_marks_failed(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "ai-owner6@example.com")
    make_category(db_session, "IT")
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(
        suggestion=AISuggestion(
            category="IT",
            sub_category=None,
            priority="SUPER_URGENT",  # not a real priority
            summary="Something.",
            reasoning="Something else.",
        )
    )
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.FAILED


def test_deterministic_priority_escalation_overrides_ai_suggestion(db_session, ai_session_factory):
    """The AI suggests LOW, but the description contains an escalation
    keyword - the backend's deterministic rule wins, not the AI's opinion
    (DECISIONS.md D4)."""
    owner = make_user_with_role(db_session, "USER", "ai-owner7@example.com")
    make_category(db_session, "IT")
    issue = make_issue(
        db_session, owner, title="Production down", description="Production is down, total outage."
    )
    db_session.commit()

    provider = FakeAIProvider(
        suggestion=AISuggestion(
            category="IT", sub_category=None, priority="LOW", summary="Outage.", reasoning="Outage detected."
        )
    )
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.priority == IssuePriority.HIGH  # escalated from LOW, not what the AI said


def test_no_matching_routing_rule_leaves_issue_triaged_but_unassigned(db_session, ai_session_factory):
    """No routing_rule configured for this category - the issue is still
    triaged (category/priority set) but has no team. Not silently dropped:
    it's a fully visible, valid TRIAGED issue."""
    owner = make_user_with_role(db_session, "USER", "ai-owner8@example.com")
    make_category(db_session, "IT")  # no routing_rule for it
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(
        suggestion=AISuggestion(
            category="IT", sub_category=None, priority="MEDIUM", summary="s", reasoning="r"
        )
    )
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.COMPLETED
    assert issue.status == IssueStatus.TRIAGED
    assert issue.current_team_id is None


def test_no_matching_sla_rule_still_completes_without_an_sla_record(db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "ai-owner9@example.com")
    make_category(db_session, "IT")  # no sla_rule for it
    issue = make_issue(db_session, owner)
    db_session.commit()

    provider = FakeAIProvider(
        suggestion=AISuggestion(
            category="IT", sub_category=None, priority="MEDIUM", summary="s", reasoning="r"
        )
    )
    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.COMPLETED
    assert issue.sla_record is None


def test_ai_suggestion_has_no_authority_over_authorization_or_team_assignment(db_session, ai_session_factory):
    """Structural proof, not just a runtime check: AISuggestion has no
    role/permission/team field at all - there is nothing in the AI's
    response shape capable of setting who is authorized or which team owns
    the issue directly. Only RoutingService (via routing_rules) can."""
    assert not hasattr(AISuggestion, "team")
    assert not hasattr(AISuggestion, "team_id")
    assert not hasattr(AISuggestion, "role")
    assert set(AISuggestion.model_fields.keys()) == {
        "category",
        "sub_category",
        "priority",
        "summary",
        "reasoning",
    }


def test_issue_stays_usable_and_commentable_while_ai_analysis_is_failed(client, db_session, ai_session_factory):
    """D2: ai_analysis_status is independent of the business lifecycle - a
    FAILED analysis must not block normal use of the issue over the API."""
    owner = make_user_with_role(db_session, "USER", "ai-owner10@example.com")
    issue = make_issue(db_session, owner)
    db_session.commit()

    run_ai_analysis(issue.id, provider=FakeAIProvider(raise_provider_error=True), session_factory=ai_session_factory)
    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.FAILED

    response = client.get(f"/api/v1/issues/{issue.id}", headers=auth_headers(owner))
    assert response.status_code == 200
    assert response.json()["status"] == "OPEN"
