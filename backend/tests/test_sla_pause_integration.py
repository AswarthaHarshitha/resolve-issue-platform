"""SLA pause/resume wired into real status transitions (DECISIONS.md D40):
entering WAITING_FOR_USER opens a pause, leaving it closes one, atomically
with the status change itself - exercised over the actual PATCH endpoint,
not by calling sla_service directly."""

import threading
import uuid

from app.models.sla_pause_interval import SLAPauseInterval
from app.models.sla_record import SLARecord
from tests.auth_helpers import auth_headers
from tests.factories import make_category, make_sla_rule, make_user_with_role
from tests.fake_ai_provider import FakeAIProvider
from app.services.ai_analysis_service import run_ai_analysis
from app.services.ai_provider import AISuggestion


def _routed_issue(client, db_session, ai_session_factory, owner):
    """Creates and routes an issue via the real pipeline, ending ASSIGNED
    with a real sla_records row - the state every pause test starts from."""
    from app.models.routing_rule import RoutingRule
    from tests.factories import make_team

    category = make_category(db_session, f"Cat-{uuid.uuid4().hex[:8]}")
    team = make_team(db_session, f"Team-{uuid.uuid4().hex[:8]}")
    db_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
    make_sla_rule(db_session, category, first_response_minutes=60, resolution_minutes=1440)
    db_session.commit()

    response = client.post(
        "/api/v1/issues",
        json={"title": "Needs SLA tracking", "description": "Description text."},
        headers=auth_headers(owner),
    )
    issue_id = uuid.UUID(response.json()["id"])

    # make_sla_rule() defaults to priority=HIGH - match it here so routing
    # actually finds an sla_rule and creates an sla_records row.
    run_ai_analysis(
        issue_id,
        provider=FakeAIProvider(
            suggestion=AISuggestion(
                category=category.name, sub_category=None, priority="HIGH", summary="s", reasoning="r"
            )
        ),
        session_factory=ai_session_factory,
    )
    return issue_id


def _advance_to_in_progress(client, resolver, issue_id):
    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS"):
        response = client.patch(
            f"/api/v1/issues/{issue_id}/status", json={"status": target}, headers=auth_headers(resolver)
        )
        # TRIAGED/ASSIGNED may already have happened via AI routing - a 400
        # here just means the issue was already past that state, which is
        # fine for this helper's purpose (getting to IN_PROGRESS).
        assert response.status_code in (200, 400)


def test_entering_waiting_for_user_opens_a_pause(client, db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "sla-pause-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "sla-pause-resolver1@example.com")
    issue_id = _routed_issue(client, db_session, ai_session_factory, owner)
    _advance_to_in_progress(client, resolver, issue_id)

    response = client.patch(
        f"/api/v1/issues/{issue_id}/status", json={"status": "WAITING_FOR_USER"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 200
    assert response.json()["sla"]["is_paused"] is True

    record = db_session.query(SLARecord).filter_by(issue_id=issue_id).one()
    open_intervals = [p for p in record.pause_intervals if p.resumed_at is None]
    assert len(open_intervals) == 1


def test_leaving_waiting_for_user_closes_the_pause_and_accumulates_duration(client, db_session, ai_session_factory):
    owner = make_user_with_role(db_session, "USER", "sla-pause-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "sla-pause-resolver2@example.com")
    issue_id = _routed_issue(client, db_session, ai_session_factory, owner)
    _advance_to_in_progress(client, resolver, issue_id)

    client.patch(f"/api/v1/issues/{issue_id}/status", json={"status": "WAITING_FOR_USER"}, headers=auth_headers(resolver))

    # Backdate the pause's start so the closed duration is deterministically
    # checkable rather than racing real wall-clock time in the test.
    from datetime import timedelta

    record = db_session.query(SLARecord).filter_by(issue_id=issue_id).one()
    open_interval = next(p for p in record.pause_intervals if p.resumed_at is None)
    open_interval.paused_at = open_interval.paused_at - timedelta(minutes=5)
    db_session.commit()

    response = client.patch(
        f"/api/v1/issues/{issue_id}/status", json={"status": "IN_PROGRESS"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 200
    assert response.json()["sla"]["is_paused"] is False

    db_session.refresh(record)
    assert record.accumulated_pause_seconds >= 5 * 60
    closed_intervals = [p for p in record.pause_intervals if p.resumed_at is not None]
    assert len(closed_intervals) == 1


def test_multiple_pause_cycles_accumulate(client, db_session, ai_session_factory):
    """Two full WAITING_FOR_USER cycles in quick succession - real
    (sub-second) durations, not backdated: the point of this test is that
    the *count* and non-overlap hold across repeated cycles, not exact
    duration (covered precisely by tests/test_sla_service.py's unit tests
    using constructed timestamps instead of real wall-clock time)."""
    owner = make_user_with_role(db_session, "USER", "sla-pause-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "sla-pause-resolver3@example.com")
    issue_id = _routed_issue(client, db_session, ai_session_factory, owner)
    _advance_to_in_progress(client, resolver, issue_id)

    for _ in range(2):
        response = client.patch(
            f"/api/v1/issues/{issue_id}/status", json={"status": "WAITING_FOR_USER"}, headers=auth_headers(resolver)
        )
        assert response.status_code == 200
        response = client.patch(
            f"/api/v1/issues/{issue_id}/status", json={"status": "IN_PROGRESS"}, headers=auth_headers(resolver)
        )
        assert response.status_code == 200

    record = db_session.query(SLARecord).filter_by(issue_id=issue_id).one()
    assert record.accumulated_pause_seconds >= 0
    assert len(record.pause_intervals) == 2
    assert all(p.resumed_at is not None for p in record.pause_intervals)
    # Each cycle's interval must be genuinely separate, not overlapping -
    # the exclusion constraint (D19) would have rejected the second WRITE
    # outright if it did, which is exactly what this test is verifying.
    intervals = sorted(record.pause_intervals, key=lambda p: p.paused_at)
    assert intervals[0].resumed_at <= intervals[1].paused_at


def test_pause_intervals_never_overlap_even_across_cycles(client, db_session, ai_session_factory):
    """DECISIONS.md D19's exclusion constraint is exercised for real here,
    not just in the Phase 2 schema tests: each WAITING_FOR_USER cycle must
    produce a genuinely separate, non-overlapping interval."""
    owner = make_user_with_role(db_session, "USER", "sla-pause-owner4@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "sla-pause-resolver4@example.com")
    issue_id = _routed_issue(client, db_session, ai_session_factory, owner)
    _advance_to_in_progress(client, resolver, issue_id)

    client.patch(f"/api/v1/issues/{issue_id}/status", json={"status": "WAITING_FOR_USER"}, headers=auth_headers(resolver))
    client.patch(f"/api/v1/issues/{issue_id}/status", json={"status": "IN_PROGRESS"}, headers=auth_headers(resolver))
    client.patch(f"/api/v1/issues/{issue_id}/status", json={"status": "WAITING_FOR_USER"}, headers=auth_headers(resolver))

    record = db_session.query(SLARecord).filter_by(issue_id=issue_id).one()
    intervals = sorted(record.pause_intervals, key=lambda p: p.paused_at)
    assert len(intervals) == 2
    assert intervals[0].resumed_at <= intervals[1].paused_at


def test_concurrent_waiting_for_user_entry_opens_exactly_one_pause(test_engine):
    """Two resolvers simultaneously try to move the same IN_PROGRESS issue
    into WAITING_FOR_USER. Uses real committed data and two genuinely
    separate connections (like test_issue_status_transitions.py's
    concurrency test) - the SAVEPOINT-isolated db_session fixture can't
    give two threads a real race to serialize. Only one request can
    actually succeed; the other, evaluated against the real state the
    first left behind, correctly rejects the now-invalid
    IN_PROGRESS -> WAITING_FOR_USER transition (the issue is already
    WAITING_FOR_USER by the time it runs). Exactly one pause interval is
    ever opened - the row lock backing D12/D31 prevents a double-open
    before the database's own exclusion constraint (D19) would even need
    to."""
    from sqlalchemy.orm import Session

    from app.models.category import Category
    from app.models.enums import IssuePriority, IssueStatus
    from app.models.role import Role
    from app.models.routing_rule import RoutingRule
    from app.models.sla_rule import SLARule
    from app.models.team import Team
    from app.models.user import User as UserModel
    from app.services import issue_service
    from app.services.ai_validation import ValidatedSuggestion
    from app.services.issue_service import InvalidStatusTransitionError
    from app.services.routing_service import route_issue

    setup_engine = test_engine
    with Session(bind=setup_engine) as setup_session:
        user_role = setup_session.query(Role).filter_by(name="USER").one()
        resolver_role = setup_session.query(Role).filter_by(name="RESOLVER").one()

        owner = UserModel(
            email="sla-race-owner@example.com", password_hash="x", full_name="Owner", role_id=user_role.id
        )
        resolver = UserModel(
            email="sla-race-resolver@example.com", password_hash="x", full_name="Resolver", role_id=resolver_role.id
        )
        category = Category(name=f"RaceCat-{uuid.uuid4().hex[:8]}")
        team = Team(name=f"RaceTeam-{uuid.uuid4().hex[:8]}")
        setup_session.add_all([owner, resolver, category, team])
        setup_session.flush()

        setup_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
        setup_session.add(
            SLARule(
                category_id=category.id,
                priority=IssuePriority.HIGH,
                first_response_minutes=60,
                resolution_minutes=1440,
            )
        )
        setup_session.flush()

        issue = issue_service.create_issue(setup_session, owner=owner, title="Race", description="Race description.")
        route_issue(
            setup_session,
            issue=issue,
            validated=ValidatedSuggestion(
                category_id=category.id, sub_category_id=None, priority=IssuePriority.HIGH, summary="s", reasoning="r"
            ),
        )
        setup_session.commit()
        assert issue.status == IssueStatus.ASSIGNED

        issue_service.transition_status(
            setup_session, issue_id=issue.id, target_status=IssueStatus.IN_PROGRESS, current_user=resolver
        )
        setup_session.commit()

        issue_id = issue.id
        resolver_id = resolver.id
        owner_id = owner.id
        category_id = category.id
        team_id = team.id

    try:
        results = {}
        barrier = threading.Barrier(2)

        def attempt_waiting_for_user(key):
            with Session(bind=setup_engine) as session:
                resolver_ref = session.get(UserModel, resolver_id)
                barrier.wait()
                try:
                    issue_service.transition_status(
                        session, issue_id=issue_id, target_status=IssueStatus.WAITING_FOR_USER, current_user=resolver_ref
                    )
                    results[key] = "succeeded"
                except InvalidStatusTransitionError:
                    results[key] = "rejected"

        thread_a = threading.Thread(target=attempt_waiting_for_user, args=("a",))
        thread_b = threading.Thread(target=attempt_waiting_for_user, args=("b",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        outcomes = sorted(results.values())
        assert outcomes == ["rejected", "succeeded"]

        with Session(bind=setup_engine) as verify_session:
            record = verify_session.query(SLARecord).filter_by(issue_id=issue_id).one()
            open_intervals = [p for p in record.pause_intervals if p.resumed_at is None]
            assert len(open_intervals) == 1
    finally:
        with Session(bind=setup_engine) as cleanup_session:
            record = cleanup_session.query(SLARecord).filter_by(issue_id=issue_id).first()
            if record is not None:
                cleanup_session.query(SLAPauseInterval).filter_by(sla_record_id=record.id).delete()
                cleanup_session.delete(record)
            from app.models.issue import Issue
            from app.models.issue_assignment import IssueAssignment
            from app.models.issue_status_history import IssueStatusHistory

            cleanup_session.query(IssueStatusHistory).filter_by(issue_id=issue_id).delete()
            cleanup_session.query(IssueAssignment).filter_by(issue_id=issue_id).delete()
            cleanup_session.query(Issue).filter_by(id=issue_id).delete()
            cleanup_session.query(RoutingRule).filter_by(category_id=category_id).delete()
            cleanup_session.query(SLARule).filter_by(category_id=category_id).delete()
            cleanup_session.query(UserModel).filter(UserModel.id.in_([resolver_id, owner_id])).delete(
                synchronize_session=False
            )
            cleanup_session.query(Team).filter_by(id=team_id).delete()
            cleanup_session.query(Category).filter_by(id=category_id).delete()
            cleanup_session.commit()
