"""Deterministic routing: category/priority/team/SLA decisions live here,
never in the AI (DECISIONS.md D4). Configuration-driven (routing_rules,
sla_rules), not a hardcoded if/else chain.

Missing configuration (no routing_rule or sla_rule for a category) is
treated as an operational gap, not a failure of the issue or the AI: the
issue still gets triaged (category/priority set) and keeps its AI-derived
classification even if nothing farther could be automated. Nothing is
silently dropped - an issue with no matching team simply stays unassigned
and visible, exactly as the original architecture review specified."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.enums import IssuePriority, IssueStatus, StatusChangeTrigger
from app.models.issue import Issue
from app.models.issue_assignment import IssueAssignment
from app.models.issue_status_history import IssueStatusHistory
from app.models.routing_rule import RoutingRule
from app.models.sla_record import SLARecord
from app.models.sla_rule import SLARule
from app.services.ai_validation import ValidatedSuggestion

# Deterministic priority escalation: certain keywords in the issue text
# always bump the AI's suggested priority up (never down) to at least HIGH.
# The AI's suggestion is a starting point; this rule is what actually
# decides the final priority for these cases, not the AI's judgment alone.
_ESCALATION_KEYWORDS = (
    "outage",
    "down",
    "cannot access",
    "can't access",
    "security breach",
    "data loss",
    "production down",
)
# Whole-word/phrase matching only - a naive substring check would make
# "dropdown" trip the "down" keyword, "showdown" trip it too, etc.
_ESCALATION_PATTERNS = tuple(re.compile(r"\b" + re.escape(keyword) + r"\b") for keyword in _ESCALATION_KEYWORDS)

_PRIORITY_ORDER = (IssuePriority.LOW, IssuePriority.MEDIUM, IssuePriority.HIGH, IssuePriority.CRITICAL)


def determine_final_priority(ai_priority: IssuePriority, issue_text: str) -> IssuePriority:
    text = issue_text.lower()
    if any(pattern.search(text) for pattern in _ESCALATION_PATTERNS):
        if _PRIORITY_ORDER.index(ai_priority) < _PRIORITY_ORDER.index(IssuePriority.HIGH):
            return IssuePriority.HIGH
    return ai_priority


def _find_routing_team(db: Session, category_id, sub_category_id) -> Optional[RoutingRule]:
    if sub_category_id is not None:
        specific = (
            db.query(RoutingRule)
            .filter(
                RoutingRule.category_id == category_id,
                RoutingRule.sub_category_id == sub_category_id,
                RoutingRule.is_active.is_(True),
            )
            .first()
        )
        if specific is not None:
            return specific

    return (
        db.query(RoutingRule)
        .filter(
            RoutingRule.category_id == category_id,
            RoutingRule.sub_category_id.is_(None),
            RoutingRule.is_active.is_(True),
        )
        .first()
    )


def _find_sla_rule(db: Session, category_id, priority: IssuePriority) -> Optional[SLARule]:
    return (
        db.query(SLARule)
        .filter(SLARule.category_id == category_id, SLARule.priority == priority, SLARule.is_active.is_(True))
        .first()
    )


def route_issue(db: Session, *, issue: Issue, validated: ValidatedSuggestion) -> None:
    """Mutates `issue` and adds any new rows to `db` - does not commit; the
    caller (ai_analysis_service) owns the transaction boundary.

    Only routes an issue that is still OPEN - defense in depth for the
    manual-reanalysis rule (DECISIONS.md D13): an issue already routed
    and/or hand-adjusted by a human must never be silently re-routed. The
    caller (ai_analysis_service) is what actually decides whether routing
    should be attempted at all; this is a second guard against calling it
    by mistake on an issue that already progressed past OPEN."""
    if issue.status != IssueStatus.OPEN:
        return

    final_priority = determine_final_priority(validated.priority, f"{issue.title} {issue.description}")

    previous_status = issue.status
    issue.category_id = validated.category_id
    issue.sub_category_id = validated.sub_category_id
    issue.priority = final_priority

    db.add(
        IssueStatusHistory(
            issue_id=issue.id,
            previous_status=previous_status,
            new_status=IssueStatus.TRIAGED,
            trigger=StatusChangeTrigger.AI_ROUTING,
            changed_by_id=None,
        )
    )
    issue.status = IssueStatus.TRIAGED

    routing_rule = _find_routing_team(db, validated.category_id, validated.sub_category_id)
    if routing_rule is not None:
        issue.current_team_id = routing_rule.team_id
        db.add(
            IssueAssignment(
                issue_id=issue.id,
                team_id=routing_rule.team_id,
                assigned_by_id=None,
                reason="AI-assisted routing",
            )
        )
        db.add(
            IssueStatusHistory(
                issue_id=issue.id,
                previous_status=IssueStatus.TRIAGED,
                new_status=IssueStatus.ASSIGNED,
                trigger=StatusChangeTrigger.AI_ROUTING,
                changed_by_id=None,
            )
        )
        issue.status = IssueStatus.ASSIGNED

    sla_rule = _find_sla_rule(db, validated.category_id, final_priority)
    if sla_rule is not None:
        started_at = datetime.now(timezone.utc)
        db.add(
            SLARecord(
                issue_id=issue.id,
                sla_rule_id=sla_rule.id,
                sla_started_at=started_at,
                first_response_deadline_at=started_at + timedelta(minutes=sla_rule.first_response_minutes),
                resolution_deadline_at=started_at + timedelta(minutes=sla_rule.resolution_minutes),
            )
        )
