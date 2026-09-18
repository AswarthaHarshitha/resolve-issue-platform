"""Phase 9 regression: build_issue_public() must freeze the SLA clock at
issue.resolved_at once an issue is RESOLVED/CLOSED, not keep evaluating
resolution_breached/effective_elapsed_seconds against the live wall clock.

Before this fix, compute_sla_status was always called with now=None (i.e.
"right now") regardless of issue status - an issue resolved comfortably
within its SLA would eventually render as breached purely because more real
time passed while it sat RESOLVED, waiting for the owner's confirmation.
resolved_at is None for every still-open issue, so the fix (passing
now=issue.resolved_at) is a no-op for them; these tests target exactly the
RESOLVED/CLOSED case."""

from datetime import datetime, timedelta, timezone

from app.models.sla_record import SLARecord
from app.schemas.issue import build_issue_public
from tests.factories import make_category, make_issue, make_sla_rule, make_user_with_role


def _resolved_issue_with_sla(db_session, *, resolution_minutes, minutes_to_resolve):
    owner = make_user_with_role(db_session, "USER", f"freeze-{id(object())}@example.com")
    category = make_category(db_session, f"Freeze-{id(object())}")
    sla_rule = make_sla_rule(
        db_session, category, first_response_minutes=5, resolution_minutes=resolution_minutes
    )
    issue = make_issue(db_session, owner, category=category)

    # Started far enough in the past that, under the pre-fix behavior (using
    # the real current time), the resolution deadline would already have
    # passed - proving the freeze, not just a coincidence of timing.
    started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(
        SLARecord(
            issue_id=issue.id,
            sla_rule_id=sla_rule.id,
            sla_started_at=started_at,
            first_response_deadline_at=started_at + timedelta(minutes=5),
            resolution_deadline_at=started_at + timedelta(minutes=resolution_minutes),
        )
    )
    issue.resolved_at = started_at + timedelta(minutes=minutes_to_resolve)
    db_session.flush()
    db_session.refresh(issue)
    return issue


def test_issue_resolved_within_sla_does_not_become_breached_over_time(db_session):
    issue = _resolved_issue_with_sla(db_session, resolution_minutes=10, minutes_to_resolve=3)

    public = build_issue_public(issue)

    assert public.sla is not None
    assert public.sla.resolution_breached is False
    assert public.sla.resolution_at_risk is False
    # Frozen at the 3-minute mark, not the ~60 minutes of real elapsed time
    # since sla_started_at.
    assert public.sla.effective_elapsed_seconds == 3 * 60


def test_issue_resolved_after_deadline_still_shows_breached_once_frozen(db_session):
    issue = _resolved_issue_with_sla(db_session, resolution_minutes=10, minutes_to_resolve=15)

    public = build_issue_public(issue)

    assert public.sla is not None
    assert public.sla.resolution_breached is True
    assert public.sla.effective_elapsed_seconds == 15 * 60


def test_still_open_issue_sla_uses_live_wall_clock_not_frozen(db_session):
    """resolved_at is None for an open issue, so build_issue_public must
    keep behaving exactly as before the fix - no regression for the
    still-in-progress case."""
    owner = make_user_with_role(db_session, "USER", f"freeze-open-{id(object())}@example.com")
    category = make_category(db_session, f"Freeze-open-{id(object())}")
    sla_rule = make_sla_rule(db_session, category, first_response_minutes=5, resolution_minutes=1440)
    issue = make_issue(db_session, owner, category=category)
    started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.add(
        SLARecord(
            issue_id=issue.id,
            sla_rule_id=sla_rule.id,
            sla_started_at=started_at,
            first_response_deadline_at=started_at + timedelta(minutes=5),
            resolution_deadline_at=started_at + timedelta(minutes=1440),
        )
    )
    db_session.flush()
    db_session.refresh(issue)

    public = build_issue_public(issue)

    assert public.sla is not None
    assert public.sla.effective_elapsed_seconds >= 60  # ~1 minute of real elapsed time, not frozen at 0
