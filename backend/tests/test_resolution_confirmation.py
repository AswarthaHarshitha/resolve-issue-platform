"""POST /issues/{id}/resolution/confirm and .../reject - the only path to
CLOSED (DECISIONS.md D9, D30, D41): only the issue's own submitter may
confirm or reject, and RESOLVED -> CLOSED is unreachable any other way."""

import threading
import uuid

from tests.auth_helpers import auth_headers
from tests.factories import make_user_with_role


def _resolved_issue(client, owner, resolver):
    response = client.post(
        "/api/v1/issues", json={"title": "Needs resolving", "description": "Description text."}, headers=auth_headers(owner)
    )
    issue_id = response.json()["id"]
    headers = auth_headers(resolver)
    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "RESOLVED"):
        r = client.patch(f"/api/v1/issues/{issue_id}/status", json={"status": target}, headers=headers)
        assert r.status_code == 200
    return issue_id


def test_owner_can_confirm_resolution(client, db_session):
    owner = make_user_with_role(db_session, "USER", "confirm-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver1@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"


def test_resolver_cannot_confirm_resolution(client, db_session):
    """The resolver who marked it RESOLVED cannot close it themselves -
    only the submitting user can (DECISIONS.md D9)."""
    owner = make_user_with_role(db_session, "USER", "confirm-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver2@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(resolver))

    assert response.status_code == 403


def test_admin_cannot_confirm_resolution_either(client, db_session):
    """No silent admin override in this phase - see the original
    architecture review's explicit scoping decision."""
    owner = make_user_with_role(db_session, "USER", "confirm-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "confirm-admin3@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(admin))

    assert response.status_code == 403


def test_cannot_confirm_an_issue_that_is_not_resolved(client, db_session):
    owner = make_user_with_role(db_session, "USER", "confirm-owner4@example.com")
    response = client.post(
        "/api/v1/issues", json={"title": "Still open", "description": "Description text."}, headers=auth_headers(owner)
    )
    issue_id = response.json()["id"]

    confirm_response = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(owner))

    assert confirm_response.status_code == 400


def test_owner_can_reject_resolution_returning_to_in_progress(client, db_session):
    owner = make_user_with_role(db_session, "USER", "reject-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reject-resolver1@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(
        f"/api/v1/issues/{issue_id}/resolution/reject",
        json={"status": "IN_PROGRESS", "note": "Not actually fixed"},
        headers=auth_headers(owner),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


def test_other_user_cannot_reject_resolution(client, db_session):
    owner = make_user_with_role(db_session, "USER", "reject-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reject-resolver2@example.com")
    other_user = make_user_with_role(db_session, "USER", "reject-other2@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.post(
        f"/api/v1/issues/{issue_id}/resolution/reject",
        json={"status": "IN_PROGRESS"},
        headers=auth_headers(other_user),
    )

    assert response.status_code == 403


def test_resolver_can_act_again_after_rejection(client, db_session):
    """After a rejection, the issue is genuinely active again - a resolver
    can move it forward through the normal state machine."""
    owner = make_user_with_role(db_session, "USER", "reject-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "reject-resolver3@example.com")
    issue_id = _resolved_issue(client, owner, resolver)
    client.post(
        f"/api/v1/issues/{issue_id}/resolution/reject", json={"status": "IN_PROGRESS"}, headers=auth_headers(owner)
    )

    response = client.patch(
        f"/api/v1/issues/{issue_id}/status", json={"status": "RESOLVED"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 200


def test_confirm_on_nonexistent_issue_returns_404(client, db_session):
    owner = make_user_with_role(db_session, "USER", "confirm-owner5@example.com")

    response = client.post(f"/api/v1/issues/{uuid.uuid4()}/resolution/confirm", headers=auth_headers(owner))

    assert response.status_code == 404


def test_repeated_confirm_requests_do_not_corrupt_state(client, db_session):
    """Duplicate-request attack (Phase 9): a user double-clicking confirm,
    or a retried request after a slow/dropped response. The first call
    closes the issue; every subsequent call correctly finds the issue no
    longer RESOLVED and is rejected, rather than writing a second CLOSED
    history row or re-running closed_at."""
    owner = make_user_with_role(db_session, "USER", "confirm-owner7@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver7@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    first = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(owner))
    second = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(owner))
    third = client.post(f"/api/v1/issues/{issue_id}/resolution/confirm", headers=auth_headers(owner))

    assert first.status_code == 200
    assert first.json()["status"] == "CLOSED"
    assert second.status_code == 400
    assert third.status_code == 400

    from app.models.enums import IssueStatus
    from app.models.issue_status_history import IssueStatusHistory

    closed_events = (
        db_session.query(IssueStatusHistory)
        .filter_by(issue_id=uuid.UUID(issue_id), new_status=IssueStatus.CLOSED)
        .count()
    )
    assert closed_events == 1


def test_concurrent_double_confirm_closes_exactly_once(test_engine):
    """Real-thread version of the above (Phase 9 Scenario C): two genuinely
    concurrent confirm requests for the same RESOLVED issue, racing against
    each other rather than sequential HTTP calls. The row lock in
    get_issue_by_id_for_update must serialize them - exactly one succeeds
    and transitions RESOLVED -> CLOSED; the other's locked read sees the
    already-CLOSED state and is correctly rejected, never a second closure
    or a lost/duplicated history row."""
    from sqlalchemy.orm import Session

    from app.models.issue import Issue
    from app.models.issue_status_history import IssueStatusHistory
    from app.models.role import Role
    from app.models.user import User as UserModel
    from app.services import issue_service
    from app.services.issue_service import InvalidStatusTransitionError
    from app.models.enums import IssueStatus

    setup_engine = test_engine
    with Session(bind=setup_engine) as setup_session:
        user_role = setup_session.query(Role).filter_by(name="USER").one()
        resolver_role = setup_session.query(Role).filter_by(name="RESOLVER").one()

        owner = UserModel(
            email="confirm-race-owner@example.com", password_hash="x", full_name="Owner", role_id=user_role.id
        )
        resolver = UserModel(
            email="confirm-race-resolver@example.com",
            password_hash="x",
            full_name="Resolver",
            role_id=resolver_role.id,
        )
        setup_session.add_all([owner, resolver])
        setup_session.flush()

        issue = issue_service.create_issue(setup_session, owner=owner, title="Race to close", description="...")
        for target in (IssueStatus.TRIAGED, IssueStatus.ASSIGNED, IssueStatus.IN_PROGRESS, IssueStatus.RESOLVED):
            issue_service.transition_status(setup_session, issue_id=issue.id, target_status=target, current_user=resolver)
        setup_session.commit()
        issue_id = issue.id
        owner_id = owner.id
        resolver_id = resolver.id

    try:
        results = {}
        barrier = threading.Barrier(2)

        def race(name):
            with Session(bind=setup_engine) as session:
                owner_conn = session.get(UserModel, owner_id)
                barrier.wait()
                try:
                    issue_service.confirm_resolution(session, issue_id=issue_id, current_user=owner_conn)
                    results[name] = "succeeded"
                except InvalidStatusTransitionError:
                    results[name] = "rejected"

        thread_a = threading.Thread(target=race, args=("a",))
        thread_b = threading.Thread(target=race, args=("b",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        outcomes = sorted(results.values())
        assert outcomes == ["rejected", "succeeded"]

        with Session(bind=setup_engine) as verify_session:
            final_issue = verify_session.get(Issue, issue_id)
            assert final_issue.status == IssueStatus.CLOSED
            closed_events = (
                verify_session.query(IssueStatusHistory)
                .filter_by(issue_id=issue_id, new_status=IssueStatus.CLOSED)
                .count()
            )
            assert closed_events == 1
    finally:
        with Session(bind=setup_engine) as cleanup_session:
            cleanup_session.query(Issue).filter(Issue.id == issue_id).delete()
            cleanup_session.query(UserModel).filter(
                UserModel.id.in_([owner_id, resolver_id])
            ).delete(synchronize_session=False)
            cleanup_session.commit()


def test_generic_status_endpoint_still_cannot_reach_closed_after_resolution(client, db_session):
    """Belt-and-suspenders: even with a RESOLVED issue in hand, the generic
    transition endpoint (resolver/admin-only) still cannot skip the
    confirmation flow."""
    owner = make_user_with_role(db_session, "USER", "confirm-owner6@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "confirm-resolver6@example.com")
    issue_id = _resolved_issue(client, owner, resolver)

    response = client.patch(
        f"/api/v1/issues/{issue_id}/status", json={"status": "CLOSED"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 400
