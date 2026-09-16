"""app/services/sla_service.py: effective-elapsed/at-risk/breach math.
Deterministic, DB-driven - every scenario here constructs sla_records/
sla_pause_intervals rows directly and computes against them, proving the
computation depends only on persisted data (DECISIONS.md D40)."""

from datetime import datetime, timedelta, timezone

from app.models.sla_pause_interval import SLAPauseInterval
from app.models.sla_record import SLARecord
from app.services.sla_service import compute_sla_status
from tests.factories import make_category, make_issue, make_sla_rule, make_user_with_role


def _make_sla_record(db_session, *, first_response_minutes=60, resolution_minutes=1440):
    owner = make_user_with_role(db_session, "USER", f"sla-{id(object())}@example.com")
    category = make_category(db_session, f"Cat-{id(object())}")
    sla_rule = make_sla_rule(
        db_session,
        category,
        first_response_minutes=first_response_minutes,
        resolution_minutes=resolution_minutes,
    )
    issue = make_issue(db_session, owner, category=category)
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = SLARecord(
        issue_id=issue.id,
        sla_rule_id=sla_rule.id,
        sla_started_at=started_at,
        first_response_deadline_at=started_at + timedelta(minutes=first_response_minutes),
        resolution_deadline_at=started_at + timedelta(minutes=resolution_minutes),
    )
    db_session.add(record)
    db_session.flush()
    return record


def test_no_pause_effective_elapsed_equals_wall_clock(db_session):
    record = _make_sla_record(db_session)
    now = record.sla_started_at + timedelta(minutes=30)

    status = compute_sla_status(record, now=now)

    assert status.effective_elapsed_seconds == 30 * 60
    assert status.is_paused is False
    assert status.accumulated_pause_seconds == 0


def test_one_completed_pause_is_excluded_from_effective_elapsed(db_session):
    record = _make_sla_record(db_session)
    db_session.add(
        SLAPauseInterval(
            sla_record_id=record.id,
            paused_at=record.sla_started_at + timedelta(minutes=10),
            resumed_at=record.sla_started_at + timedelta(minutes=20),
        )
    )
    record.accumulated_pause_seconds = 10 * 60
    db_session.flush()

    now = record.sla_started_at + timedelta(minutes=40)
    status = compute_sla_status(record, now=now)

    # 40 minutes of wall clock, minus 10 minutes paused = 30 minutes effective.
    assert status.effective_elapsed_seconds == 30 * 60


def test_multiple_completed_pauses_all_excluded(db_session):
    record = _make_sla_record(db_session)
    db_session.add_all(
        [
            SLAPauseInterval(
                sla_record_id=record.id,
                paused_at=record.sla_started_at + timedelta(minutes=10),
                resumed_at=record.sla_started_at + timedelta(minutes=20),
            ),
            SLAPauseInterval(
                sla_record_id=record.id,
                paused_at=record.sla_started_at + timedelta(minutes=30),
                resumed_at=record.sla_started_at + timedelta(minutes=35),
            ),
        ]
    )
    record.accumulated_pause_seconds = 15 * 60  # 10 + 5 minutes
    db_session.flush()

    now = record.sla_started_at + timedelta(minutes=60)
    status = compute_sla_status(record, now=now)

    assert status.effective_elapsed_seconds == 45 * 60  # 60 - 15


def test_currently_open_pause_is_excluded_and_reported_as_paused(db_session):
    record = _make_sla_record(db_session)
    db_session.add(
        SLAPauseInterval(sla_record_id=record.id, paused_at=record.sla_started_at + timedelta(minutes=10))
    )
    db_session.flush()

    now = record.sla_started_at + timedelta(minutes=25)
    status = compute_sla_status(record, now=now)

    assert status.is_paused is True
    # 25 minutes wall clock, minus 15 minutes of the still-open pause (10->25) = 10 effective.
    assert status.effective_elapsed_seconds == 10 * 60
    assert status.accumulated_pause_seconds == 15 * 60  # includes the open pause's running duration


def test_first_response_at_risk_when_remaining_time_is_low(db_session):
    record = _make_sla_record(db_session, first_response_minutes=60)
    # Default threshold is 20% - at 50 minutes elapsed, 10 minutes (16.7%) remain.
    now = record.sla_started_at + timedelta(minutes=50)

    status = compute_sla_status(record, now=now)

    assert status.first_response_at_risk is True
    assert status.first_response_breached is False


def test_first_response_not_at_risk_with_plenty_of_time_left(db_session):
    record = _make_sla_record(db_session, first_response_minutes=60)
    now = record.sla_started_at + timedelta(minutes=10)

    status = compute_sla_status(record, now=now)

    assert status.first_response_at_risk is False
    assert status.first_response_breached is False


def test_first_response_breached_after_deadline_passes(db_session):
    record = _make_sla_record(db_session, first_response_minutes=60)
    now = record.sla_started_at + timedelta(minutes=61)

    status = compute_sla_status(record, now=now)

    assert status.first_response_breached is True
    assert status.first_response_at_risk is False  # breached, not merely "at risk"


def test_resolution_and_first_response_are_evaluated_independently(db_session):
    record = _make_sla_record(db_session, first_response_minutes=60, resolution_minutes=1440)
    now = record.sla_started_at + timedelta(minutes=61)  # first response breached, resolution barely started

    status = compute_sla_status(record, now=now)

    assert status.first_response_breached is True
    assert status.resolution_breached is False
    assert status.resolution_at_risk is False


def test_met_flags_suppress_at_risk_and_breached(db_session):
    record = _make_sla_record(db_session, first_response_minutes=60)
    record.first_response_met_at = record.sla_started_at + timedelta(minutes=5)
    db_session.flush()

    now = record.sla_started_at + timedelta(minutes=90)  # long past the deadline
    status = compute_sla_status(record, now=now)

    assert status.first_response_met is True
    assert status.first_response_breached is False
    assert status.first_response_at_risk is False


def test_reconstructs_correctly_from_a_freshly_loaded_record_simulating_a_restart(db_session):
    """Nothing about compute_sla_status depends on anything held in process
    memory - loading the same record fresh (a new query, as a restarted
    process would have to) produces the identical result."""
    record = _make_sla_record(db_session)
    db_session.add(
        SLAPauseInterval(
            sla_record_id=record.id,
            paused_at=record.sla_started_at + timedelta(minutes=5),
            resumed_at=record.sla_started_at + timedelta(minutes=15),
        )
    )
    record.accumulated_pause_seconds = 10 * 60
    db_session.commit()

    now = record.sla_started_at + timedelta(minutes=30)
    original_status = compute_sla_status(record, now=now)

    db_session.expire_all()  # force a fresh load from the database
    reloaded = db_session.get(SLARecord, record.id)
    reloaded_status = compute_sla_status(reloaded, now=now)

    assert reloaded_status == original_status
