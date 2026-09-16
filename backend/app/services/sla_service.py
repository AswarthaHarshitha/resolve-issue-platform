"""SLA pause/resume and effective-elapsed/at-risk/breach computation.

Nothing here is kept in Python-process memory - every fact this module
needs (when the SLA started, every pause window, whether one is currently
open, the fixed deadlines) is read fresh from the database on every call.
A server restart mid-pause loses nothing: `compute_sla_status` reconstructs
the full picture, including an open pause's current duration, purely from
persisted rows (DECISIONS.md D19, D40). All calculations are deterministic
and backend-only - the AI is never involved in SLA math (DECISIONS.md D6).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.sla_pause_interval import SLAPauseInterval
from app.models.sla_record import SLARecord

settings = get_settings()


def open_pause(db: Session, sla_record: SLARecord) -> None:
    """Called when an issue enters WAITING_FOR_USER. The database's own
    exclusion constraint (D19) is the real guarantee against a double-open -
    this is only ever reached via a state-machine transition that already
    guarantees the issue wasn't already paused, so this should never
    conflict in practice."""
    db.add(SLAPauseInterval(sla_record_id=sla_record.id, paused_at=datetime.now(timezone.utc)))


def close_pause(db: Session, sla_record: SLARecord) -> None:
    """Called when an issue leaves WAITING_FOR_USER. Closes the open
    interval and folds its duration into the accumulated_pause_seconds
    cache (D19) - the interval row itself remains the source of truth;
    the cache just avoids re-aggregating the full pause history on every
    SLA read."""
    open_interval = (
        db.query(SLAPauseInterval)
        .filter(SLAPauseInterval.sla_record_id == sla_record.id, SLAPauseInterval.resumed_at.is_(None))
        .with_for_update()
        .first()
    )
    if open_interval is None:
        return  # Defensive: nothing to close. Shouldn't happen if the state machine is respected.

    now = datetime.now(timezone.utc)
    open_interval.resumed_at = now
    duration_seconds = int((now - open_interval.paused_at).total_seconds())
    sla_record.accumulated_pause_seconds += duration_seconds


@dataclass
class SLAStatus:
    first_response_deadline_at: datetime
    resolution_deadline_at: datetime
    effective_elapsed_seconds: int
    accumulated_pause_seconds: int
    is_paused: bool
    first_response_met: bool
    resolution_met: bool
    first_response_at_risk: bool
    first_response_breached: bool
    resolution_at_risk: bool
    resolution_breached: bool


def compute_sla_status(sla_record: SLARecord, *, now: Optional[datetime] = None) -> SLAStatus:
    """Pure function over already-loaded data (sla_record.pause_intervals
    must be loaded) - deterministic and independently auditable: given the
    same rows, this always produces the same answer, which is exactly what
    "why was this issue considered breached" requires (Phase 6 spec)."""
    now = now or datetime.now(timezone.utc)

    open_interval = next((p for p in sla_record.pause_intervals if p.resumed_at is None), None)
    current_pause_seconds = int((now - open_interval.paused_at).total_seconds()) if open_interval else 0
    total_paused_seconds = sla_record.accumulated_pause_seconds + current_pause_seconds

    wall_elapsed_seconds = (now - sla_record.sla_started_at).total_seconds()
    effective_elapsed_seconds = max(int(wall_elapsed_seconds - total_paused_seconds), 0)

    first_response_target = (sla_record.first_response_deadline_at - sla_record.sla_started_at).total_seconds()
    resolution_target = (sla_record.resolution_deadline_at - sla_record.sla_started_at).total_seconds()

    first_response_met = sla_record.first_response_met_at is not None
    resolution_met = sla_record.resolved_met_at is not None

    first_response_remaining = first_response_target - effective_elapsed_seconds
    resolution_remaining = resolution_target - effective_elapsed_seconds

    first_response_breached = (not first_response_met) and first_response_remaining <= 0
    resolution_breached = (not resolution_met) and resolution_remaining <= 0

    threshold = settings.sla_at_risk_threshold_fraction
    first_response_at_risk = (
        not first_response_met
        and not first_response_breached
        and first_response_remaining <= threshold * first_response_target
    )
    resolution_at_risk = (
        not resolution_met
        and not resolution_breached
        and resolution_remaining <= threshold * resolution_target
    )

    return SLAStatus(
        first_response_deadline_at=sla_record.first_response_deadline_at,
        resolution_deadline_at=sla_record.resolution_deadline_at,
        effective_elapsed_seconds=effective_elapsed_seconds,
        accumulated_pause_seconds=total_paused_seconds,
        is_paused=open_interval is not None,
        first_response_met=first_response_met,
        resolution_met=resolution_met,
        first_response_at_risk=first_response_at_risk,
        first_response_breached=first_response_breached,
        resolution_at_risk=resolution_at_risk,
        resolution_breached=resolution_breached,
    )
