"""PATCH /issues/{id}/assignment: append-only assignment history
(DECISIONS.md D7), admin reassignment vs. resolver self-assign
(DECISIONS.md D41)."""

import threading
import uuid

from sqlalchemy.orm import Session

from app.models.issue_assignment import IssueAssignment
from tests.auth_helpers import auth_headers
from tests.factories import make_team, make_user_with_role


def _create_via_api(client, user):
    response = client.post(
        "/api/v1/issues", json={"title": "Needs assignment", "description": "Description text."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_admin_can_assign_a_team_to_an_unassigned_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner1@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin1@example.com")
    team = make_team(db_session, "Assign Team 1")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"team_id": str(team.id), "reason": "manual triage"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["current_team"]["id"] == str(team.id)


def test_admin_can_assign_a_resolver_belonging_to_the_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner2@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin2@example.com")
    team = make_team(db_session, "Assign Team 2")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver2@example.com", team=team)
    issue = _create_via_api(client, owner)

    client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin)
    )
    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["current_resolver"]["id"] == str(resolver.id)


def test_assignment_history_is_append_only(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin3@example.com")
    team_a = make_team(db_session, "Assign Team 3A")
    team_b = make_team(db_session, "Assign Team 3B")
    issue = _create_via_api(client, owner)

    client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin)
    )
    client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_b.id)}, headers=auth_headers(admin)
    )

    history = (
        db_session.query(IssueAssignment)
        .filter_by(issue_id=uuid.UUID(issue["id"]))
        .order_by(IssueAssignment.created_at)
        .all()
    )
    assert len(history) == 2
    assert history[0].team_id == team_a.id
    assert history[1].team_id == team_b.id


def test_resolver_can_self_assign_an_issue_on_their_own_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner4@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin4@example.com")
    team = make_team(db_session, "Assign Team 4")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver4@example.com", team=team)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin))

    response = client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={}, headers=auth_headers(resolver))

    assert response.status_code == 200
    assert response.json()["current_resolver"]["id"] == str(resolver.id)


def test_resolver_cannot_change_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner5@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin5@example.com")
    team_a = make_team(db_session, "Assign Team 5A")
    team_b = make_team(db_session, "Assign Team 5B")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver5@example.com", team=team_a)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin))

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_b.id)}, headers=auth_headers(resolver)
    )

    assert response.status_code == 403


def test_resolver_cannot_assign_someone_else(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner6@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin6@example.com")
    team = make_team(db_session, "Assign Team 6")
    resolver_a = make_user_with_role(db_session, "RESOLVER", "assign-resolver6a@example.com", team=team)
    resolver_b = make_user_with_role(db_session, "RESOLVER", "assign-resolver6b@example.com", team=team)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin))

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver_b.id)},
        headers=auth_headers(resolver_a),
    )

    assert response.status_code == 403


def test_resolver_cannot_self_assign_a_different_teams_issue(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner7@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin7@example.com")
    team_a = make_team(db_session, "Assign Team 7A")
    team_b = make_team(db_session, "Assign Team 7B")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver7@example.com", team=team_b)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin))

    response = client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={}, headers=auth_headers(resolver))

    assert response.status_code == 403


def test_user_cannot_assign_issues(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner8@example.com")
    team = make_team(db_session, "Assign Team 8")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(owner)
    )

    assert response.status_code == 403


def test_admin_cannot_assign_a_resolver_from_a_different_team(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner10@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin10@example.com")
    team_a = make_team(db_session, "Assign Team 10A")
    team_b = make_team(db_session, "Assign Team 10B")
    resolver_b = make_user_with_role(db_session, "RESOLVER", "assign-resolver10b@example.com", team=team_b)
    issue = _create_via_api(client, owner)
    client.patch(f"/api/v1/issues/{issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin))

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver_b.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 400


def test_cannot_assign_resolver_without_a_team_first(client, db_session):
    owner = make_user_with_role(db_session, "USER", "assign-owner9@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "assign-admin9@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "assign-resolver9@example.com")
    issue = _create_via_api(client, owner)

    response = client.patch(
        f"/api/v1/issues/{issue['id']}/assignment",
        json={"resolver_id": str(resolver.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 400


def test_two_resolvers_racing_to_self_assign_never_corrupt_state(test_engine):
    """Phase 9 concurrency attack: two resolvers on the same team both send
    a self-assign request for the same unresolved issue at nearly the same
    instant. update_assignment does not require the issue to be currently
    unassigned before a same-team resolver self-assigns (there is no
    documented "first come, first served" exclusivity rule - only "must be
    your own team's issue"), so this does not assert one specific winner.
    It asserts the actual safety invariant: the row lock
    (get_issue_by_id_for_update) serializes the two requests rather than
    interleaving them, both individually-valid requests succeed, the final
    current_resolver_id is unambiguously one of the two (never null, never
    corrupted), and the append-only issue_assignments history has exactly
    one row per request - never fewer (a lost write) and never duplicated."""
    from app.models.issue import Issue
    from app.models.role import Role
    from app.models.team import Team
    from app.models.user import User as UserModel
    from app.services import assignment_service, issue_service

    setup_engine = test_engine
    with Session(bind=setup_engine) as setup_session:
        user_role = setup_session.query(Role).filter_by(name="USER").one()
        resolver_role = setup_session.query(Role).filter_by(name="RESOLVER").one()

        team = Team(name="Race Team")
        setup_session.add(team)
        setup_session.flush()

        owner = UserModel(
            email="assign-race-owner@example.com", password_hash="x", full_name="Owner", role_id=user_role.id
        )
        resolver_a = UserModel(
            email="assign-race-resolver-a@example.com",
            password_hash="x",
            full_name="Resolver A",
            role_id=resolver_role.id,
            team_id=team.id,
        )
        resolver_b = UserModel(
            email="assign-race-resolver-b@example.com",
            password_hash="x",
            full_name="Resolver B",
            role_id=resolver_role.id,
            team_id=team.id,
        )
        setup_session.add_all([owner, resolver_a, resolver_b])
        setup_session.flush()

        issue = issue_service.create_issue(setup_session, owner=owner, title="Race to self-assign", description="...")
        issue.current_team_id = team.id
        setup_session.commit()
        issue_id = issue.id
        team_id = team.id
        resolver_a_id = resolver_a.id
        resolver_b_id = resolver_b.id
        owner_id = owner.id

    try:
        results = {}
        barrier = threading.Barrier(2)

        def race(name, resolver_id):
            with Session(bind=setup_engine) as session:
                resolver = session.get(UserModel, resolver_id)
                barrier.wait()
                try:
                    assignment_service.update_assignment(
                        session,
                        issue_id=issue_id,
                        current_user=resolver,
                        team_id=None,
                        resolver_id=None,
                        reason=None,
                    )
                    results[name] = "succeeded"
                except Exception as exc:  # pragma: no cover - would indicate a genuine defect
                    results[name] = f"unexpected: {exc!r}"

        thread_a = threading.Thread(target=race, args=("a", resolver_a_id))
        thread_b = threading.Thread(target=race, args=("b", resolver_b_id))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        assert results["a"] == "succeeded"
        assert results["b"] == "succeeded"

        with Session(bind=setup_engine) as verify_session:
            final_issue = verify_session.get(Issue, issue_id)
            assert final_issue.current_resolver_id in (resolver_a_id, resolver_b_id)
            assert final_issue.current_team_id == team_id

            history = (
                verify_session.query(IssueAssignment)
                .filter(IssueAssignment.issue_id == issue_id)
                .order_by(IssueAssignment.created_at)
                .all()
            )
            assert len(history) == 2
            assert {row.resolver_id for row in history} == {resolver_a_id, resolver_b_id}
    finally:
        with Session(bind=setup_engine) as cleanup_session:
            cleanup_session.query(IssueAssignment).filter(IssueAssignment.issue_id == issue_id).delete()
            cleanup_session.query(Issue).filter(Issue.id == issue_id).delete()
            cleanup_session.query(UserModel).filter(
                UserModel.id.in_([resolver_a_id, resolver_b_id, owner_id])
            ).delete(synchronize_session=False)
            cleanup_session.query(Team).filter(Team.id == team_id).delete()
            cleanup_session.commit()
