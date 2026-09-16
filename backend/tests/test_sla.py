"""Scenarios 12-13: SLA records referencing issues/sla_rules, and SLA pause
intervals supporting multiple pause windows per issue. Also the attack-review
checks on the SLA data model: overlapping pauses, a pause ending before it
starts, two simultaneously open pauses, and duplicate SLA records per issue."""

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy.exc

from app.models.sla_pause_interval import SLAPauseInterval
from app.models.sla_record import SLARecord
from tests.factories import make_category, make_issue, make_role, make_sla_rule, make_user


@pytest.fixture()
def owner(db_session):
    role = make_role(db_session, "TEST_USER_ROLE")
    return make_user(db_session, role, email="owner@example.com")


@pytest.fixture()
def issue_with_sla(db_session, owner):
    category = make_category(db_session, "IT")
    sla_rule = make_sla_rule(db_session, category, first_response_minutes=60, resolution_minutes=1440)
    issue = make_issue(db_session, owner, category=category)

    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = SLARecord(
        issue_id=issue.id,
        sla_rule_id=sla_rule.id,
        sla_started_at=started_at,
        first_response_deadline_at=started_at + timedelta(minutes=sla_rule.first_response_minutes),
        resolution_deadline_at=started_at + timedelta(minutes=sla_rule.resolution_minutes),
    )
    db_session.add(record)
    db_session.flush()
    return issue, record


def test_sla_record_references_issue_and_sla_rule(db_session, issue_with_sla):
    issue, record = issue_with_sla
    db_session.refresh(record)

    assert record.issue_id == issue.id
    assert record.sla_rule.first_response_minutes == 60


def test_sla_record_is_one_per_issue(db_session, issue_with_sla):
    issue, record = issue_with_sla

    duplicate = SLARecord(
        issue_id=issue.id,
        sla_rule_id=record.sla_rule_id,
        sla_started_at=record.sla_started_at,
        first_response_deadline_at=record.first_response_deadline_at,
        resolution_deadline_at=record.resolution_deadline_at,
    )
    db_session.add(duplicate)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_multiple_pause_intervals_reconstruct_full_timeline(db_session, issue_with_sla):
    """Create issue -> SLA starts -> pause starts -> pause ends -> second pause
    starts -> second pause ends. Verify the database holds enough information to
    reconstruct the complete pause timeline and the accumulated duration."""
    _, record = issue_with_sla
    base = record.sla_started_at

    first_pause = SLAPauseInterval(
        sla_record_id=record.id,
        paused_at=base + timedelta(hours=1),
        resumed_at=base + timedelta(hours=3),  # 2 hours paused
    )
    second_pause = SLAPauseInterval(
        sla_record_id=record.id,
        paused_at=base + timedelta(hours=5),
        resumed_at=base + timedelta(hours=5, minutes=30),  # 30 minutes paused
    )
    db_session.add_all([first_pause, second_pause])
    db_session.flush()
    db_session.refresh(record)

    intervals = record.pause_intervals
    assert len(intervals) == 2
    assert intervals[0].paused_at == base + timedelta(hours=1)
    assert intervals[0].resumed_at == base + timedelta(hours=3)
    assert intervals[1].paused_at == base + timedelta(hours=5)
    assert intervals[1].resumed_at == base + timedelta(hours=5, minutes=30)

    total_paused = sum(
        (interval.resumed_at - interval.paused_at for interval in intervals), timedelta()
    )
    assert total_paused == timedelta(hours=2, minutes=30)


def test_currently_open_pause_has_no_resumed_at(db_session, issue_with_sla):
    _, record = issue_with_sla
    open_pause = SLAPauseInterval(sla_record_id=record.id, paused_at=record.sla_started_at + timedelta(hours=1))
    db_session.add(open_pause)
    db_session.flush()
    db_session.refresh(open_pause)

    assert open_pause.resumed_at is None


def test_pause_cannot_end_before_it_starts(db_session, issue_with_sla):
    _, record = issue_with_sla
    base = record.sla_started_at

    backwards_pause = SLAPauseInterval(
        sla_record_id=record.id,
        paused_at=base + timedelta(hours=3),
        resumed_at=base + timedelta(hours=1),
    )
    db_session.add(backwards_pause)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_pause_intervals_cannot_overlap(db_session, issue_with_sla):
    _, record = issue_with_sla
    base = record.sla_started_at

    db_session.add(
        SLAPauseInterval(sla_record_id=record.id, paused_at=base + timedelta(hours=1), resumed_at=base + timedelta(hours=3))
    )
    db_session.flush()

    overlapping = SLAPauseInterval(
        sla_record_id=record.id,
        paused_at=base + timedelta(hours=2),  # starts before the first interval ends
        resumed_at=base + timedelta(hours=4),
    )
    db_session.add(overlapping)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_cannot_have_two_simultaneously_open_pauses(db_session, issue_with_sla):
    _, record = issue_with_sla
    base = record.sla_started_at

    db_session.add(SLAPauseInterval(sla_record_id=record.id, paused_at=base + timedelta(hours=1)))
    db_session.flush()

    second_open_pause = SLAPauseInterval(sla_record_id=record.id, paused_at=base + timedelta(hours=2))
    db_session.add(second_open_pause)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_cannot_delete_sla_rule_referenced_by_an_sla_record(db_session, issue_with_sla):
    _, record = issue_with_sla
    sla_rule = record.sla_rule

    db_session.delete(sla_rule)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_deleting_issue_cascades_to_sla_record_and_pause_intervals(db_session, issue_with_sla):
    issue, record = issue_with_sla
    db_session.add(SLAPauseInterval(sla_record_id=record.id, paused_at=record.sla_started_at + timedelta(hours=1)))
    db_session.flush()
    record_id = record.id

    db_session.delete(issue)
    db_session.flush()

    assert db_session.query(SLARecord).filter_by(id=record_id).count() == 0
    assert db_session.query(SLAPauseInterval).filter_by(sla_record_id=record_id).count() == 0
