"""PATCH /api/v1/issues/{id}/status - server-side transition validation
(DECISIONS.md D8) and the concurrency guarantee (D12): a transition is
always validated against the real current database state under a row lock,
never a client-supplied "from" status."""

import threading
import uuid

from sqlalchemy.orm import Session

from app.models.enums import IssueStatus, StatusChangeTrigger
from app.models.issue_status_history import IssueStatusHistory
from tests.auth_helpers import auth_headers
from tests.factories import make_user_with_role


def _create_via_api(client, user, title="Sample issue"):
    response = client.post(
        "/api/v1/issues", json={"title": title, "description": "Sample description."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_resolver_can_perform_a_valid_transition(client, db_session):
    owner = make_user_with_role(db_session, "USER", "trans-owner1@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver1@example.com")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "TRIAGED"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "TRIAGED"


def test_transition_writes_status_history_with_actor_and_trigger(client, db_session):
    owner = make_user_with_role(db_session, "USER", "trans-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver2@example.com")
    issue = _create_via_api(client, owner)

    client.patch(f"/api/v1/issues/{issue['id']}/status", json={"status": "TRIAGED"}, headers=auth_headers(resolver))

    rows = (
        db_session.query(IssueStatusHistory)
        .filter_by(issue_id=uuid.UUID(issue["id"]))
        .order_by(IssueStatusHistory.created_at)
        .all()
    )
    assert len(rows) == 2  # SYSTEM_CREATE, then this manual transition
    assert rows[1].previous_status == IssueStatus.OPEN
    assert rows[1].new_status == IssueStatus.TRIAGED
    assert rows[1].trigger == StatusChangeTrigger.MANUAL
    assert rows[1].changed_by_id == resolver.id


def test_invalid_transition_is_rejected(client, db_session):
    """OPEN can only go to TRIAGED - jumping straight to IN_PROGRESS is not
    on the allow-list."""
    owner = make_user_with_role(db_session, "USER", "trans-owner3@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver3@example.com")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "IN_PROGRESS"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 400


def test_resolved_to_closed_is_not_allowed_via_this_endpoint(client, db_session):
    """RESOLVED -> CLOSED is reserved for the Phase 7 user-confirmation flow
    (DECISIONS.md D9) - this generic endpoint must not be able to do it."""
    owner = make_user_with_role(db_session, "USER", "trans-owner4@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver4@example.com")
    issue = _create_via_api(client, owner)

    headers = auth_headers(resolver)
    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "RESOLVED"):
        response = client.patch(f"/api/v1/issues/{issue['id']}/status", json={"status": target}, headers=headers)
        assert response.status_code == 200, response.text

    closed_response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "CLOSED"}, headers=headers
    )
    assert closed_response.status_code == 400


def test_waiting_for_user_round_trip(client, db_session):
    owner = make_user_with_role(db_session, "USER", "trans-owner5@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver5@example.com")
    issue = _create_via_api(client, owner)
    headers = auth_headers(resolver)

    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "WAITING_FOR_USER"):
        response = client.patch(f"/api/v1/issues/{issue['id']}/status", json={"status": target}, headers=headers)
        assert response.status_code == 200

    back_response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "IN_PROGRESS"}, headers=headers
    )
    assert back_response.status_code == 200
    assert back_response.json()["status"] == "IN_PROGRESS"


def test_user_cannot_transition_status(client, db_session):
    owner = make_user_with_role(db_session, "USER", "trans-owner6@example.com")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/status", json={"status": "TRIAGED"}, headers=auth_headers(owner)
    )

    assert response.status_code == 403


def test_invalid_status_value_rejected(client, db_session):
    owner = make_user_with_role(db_session, "USER", "trans-owner9@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver9@example.com")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/status",
        json={"status": "DELETED_FOREVER"},
        headers=auth_headers(resolver),
    )

    assert response.status_code == 422


def test_transition_on_nonexistent_issue_returns_404(client, db_session):
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver7@example.com")

    response = client.patch(
        f"/api/v1/issues/{uuid.uuid4()}/status", json={"status": "TRIAGED"}, headers=auth_headers(resolver)
    )

    assert response.status_code == 404


def test_resolving_sets_resolved_at(client, db_session):
    owner = make_user_with_role(db_session, "USER", "trans-owner8@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "trans-resolver8@example.com")
    issue = _create_via_api(client, owner)
    headers = auth_headers(resolver)

    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "RESOLVED"):
        response = client.patch(f"/api/v1/issues/{issue['id']}/status", json={"status": target}, headers=headers)

    assert response.json()["resolved_at"] is not None


def test_concurrent_transitions_are_serialized_against_real_current_state(test_engine, db_session):
    """The scenario DECISIONS.md D12 exists for: two genuinely concurrent
    transactions targeting the same ASSIGNED issue. This uses two real,
    separate database connections/threads (not the shared db_session's
    SAVEPOINT) so the row lock in issue_repository.get_issue_by_id_for_update
    actually has two competing transactions to serialize.

    Thread A always requests ASSIGNED -> IN_PROGRESS (valid from ASSIGNED).
    Thread B always requests -> RESOLVED, which is valid from IN_PROGRESS but
    NOT from ASSIGNED - so B's outcome directly reveals which state B's
    locked read actually saw. Which thread's SELECT FOR UPDATE wins the race
    is genuinely nondeterministic (OS thread scheduling), so this test
    doesn't assert a fixed winner; it asserts the invariant that holds
    either way: whichever thread runs second must see the real state the
    first one left behind, never a value read before the race began.
    """
    from app.models.issue import Issue
    from app.models.role import Role
    from app.models.user import User as UserModel
    from app.services import issue_service
    from app.services.issue_service import InvalidStatusTransitionError

    # Committed setup data, visible to both threads' independent connections
    # (db_session's SAVEPOINT-based data would not be, since it's never
    # actually committed to the database). Cleaned up explicitly in
    # `finally` below - real commits against the shared resolve_test
    # database must not leak between test runs, since the session-scoped
    # test_db_url fixture downgrades/upgrades that same database on the
    # *next* pytest run and a leftover user row referencing a seeded role
    # would break that downgrade (FK violation).
    setup_engine = test_engine
    with Session(bind=setup_engine) as setup_session:
        user_role = setup_session.query(Role).filter_by(name="USER").one()
        resolver_role = setup_session.query(Role).filter_by(name="RESOLVER").one()

        owner = UserModel(
            email="concurrency-owner@example.com",
            password_hash="x",
            full_name="Owner",
            role_id=user_role.id,
        )
        resolver = UserModel(
            email="concurrency-resolver@example.com",
            password_hash="x",
            full_name="Resolver",
            role_id=resolver_role.id,
        )
        setup_session.add_all([owner, resolver])
        setup_session.flush()

        issue = issue_service.create_issue(
            setup_session, owner=owner, title="Race condition test", description="..."
        )
        issue_service.transition_status(
            setup_session, issue_id=issue.id, target_status=IssueStatus.TRIAGED, current_user=resolver
        )
        issue_service.transition_status(
            setup_session, issue_id=issue.id, target_status=IssueStatus.ASSIGNED, current_user=resolver
        )
        setup_session.commit()
        issue_id = issue.id
        resolver_id = resolver.id
        owner_id = owner.id

    try:
        results = {}
        barrier = threading.Barrier(2)

        def run_a():
            with Session(bind=setup_engine) as session:
                resolver_a = session.get(UserModel, resolver_id)
                barrier.wait()
                issue_a = issue_service.transition_status(
                    session, issue_id=issue_id, target_status=IssueStatus.IN_PROGRESS, current_user=resolver_a
                )
                results["a_status"] = issue_a.status

        def run_b():
            with Session(bind=setup_engine) as session:
                resolver_b = session.get(UserModel, resolver_id)
                barrier.wait()
                try:
                    issue_service.transition_status(
                        session, issue_id=issue_id, target_status=IssueStatus.RESOLVED, current_user=resolver_b
                    )
                    results["b_outcome"] = "succeeded"
                except InvalidStatusTransitionError as exc:
                    results["b_outcome"] = "rejected"
                    results["b_current_seen"] = exc.current

        thread_a = threading.Thread(target=run_a)
        thread_b = threading.Thread(target=run_b)
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        with Session(bind=setup_engine) as verify_session:
            final_issue = verify_session.get(Issue, issue_id)

        # A's transition (ASSIGNED -> IN_PROGRESS) is valid regardless of
        # when it runs relative to B, so A always eventually succeeds.
        assert results["a_status"] == IssueStatus.IN_PROGRESS

        if results["b_outcome"] == "succeeded":
            # B's locked read happened after A's commit - it correctly saw
            # IN_PROGRESS (not the stale ASSIGNED value from before the
            # race) and validly moved the issue further, to RESOLVED.
            assert final_issue.status == IssueStatus.RESOLVED
        else:
            # B's locked read happened before A committed - it correctly
            # saw the real, still-unmodified ASSIGNED state and correctly
            # rejected ASSIGNED -> RESOLVED as invalid, exactly as a fresh
            # read should.
            assert results["b_current_seen"] == IssueStatus.ASSIGNED
            assert final_issue.status == IssueStatus.IN_PROGRESS
    finally:
        with Session(bind=setup_engine) as cleanup_session:
            cleanup_session.query(Issue).filter(Issue.id == issue_id).delete()
            cleanup_session.query(UserModel).filter(
                UserModel.id.in_([resolver_id, owner_id])
            ).delete(synchronize_session=False)
            cleanup_session.commit()
