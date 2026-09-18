"""GET /dashboard/summary - every number must correspond to a real query
(project rule: no fake numbers), scoped identically to issue listing."""

from tests.auth_helpers import auth_headers
from tests.factories import make_team, make_user_with_role


def _create_via_api(client, user, title="Sample"):
    response = client.post(
        "/api/v1/issues", json={"title": title, "description": "Description text."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_summary_requires_authentication(client):
    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 401


def test_user_summary_counts_only_their_own_issues(client, db_session):
    owner = make_user_with_role(db_session, "USER", "dash-owner1@example.com")
    other = make_user_with_role(db_session, "USER", "dash-other1@example.com")
    _create_via_api(client, owner, "Mine 1")
    _create_via_api(client, owner, "Mine 2")
    _create_via_api(client, other, "Not mine")

    response = client.get("/api/v1/dashboard/summary", headers=auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["open_requests"] == 2


def test_resolved_today_reflects_real_resolutions(client, db_session):
    owner = make_user_with_role(db_session, "USER", "dash-owner2@example.com")
    resolver = make_user_with_role(db_session, "RESOLVER", "dash-resolver2@example.com")
    issue = _create_via_api(client, owner)
    headers = auth_headers(resolver)
    for target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "RESOLVED"):
        client.patch(f"/api/v1/issues/{issue['id']}/status", json={"status": target}, headers=headers)

    response = client.get("/api/v1/dashboard/summary", headers=auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["resolved_today"] == 1
    assert response.json()["open_requests"] == 0  # RESOLVED is not an "open" status


def test_resolver_summary_scoped_to_team_and_unassigned(client, db_session):
    owner = make_user_with_role(db_session, "USER", "dash-owner3@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "dash-admin3@example.com")
    team_a = make_team(db_session, "Dash Team A")
    team_b = make_team(db_session, "Dash Team B")
    resolver_a = make_user_with_role(db_session, "RESOLVER", "dash-resolver3a@example.com", team=team_a)

    own_team_issue = _create_via_api(client, owner, "Team A issue")
    client.patch(
        f"/api/v1/issues/{own_team_issue['id']}/assignment", json={"team_id": str(team_a.id)}, headers=auth_headers(admin)
    )
    other_team_issue = _create_via_api(client, owner, "Team B issue")
    client.patch(
        f"/api/v1/issues/{other_team_issue['id']}/assignment", json={"team_id": str(team_b.id)}, headers=auth_headers(admin)
    )
    _create_via_api(client, owner, "Unassigned issue")

    response = client.get("/api/v1/dashboard/summary", headers=auth_headers(resolver_a))

    assert response.status_code == 200
    # Team A issue + unassigned issue = 2, team B issue excluded.
    assert response.json()["open_requests"] == 2


def test_admin_summary_sees_everything(client, db_session):
    owner = make_user_with_role(db_session, "USER", "dash-owner4@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "dash-admin4@example.com")
    _create_via_api(client, owner, "Issue 1")
    _create_via_api(client, owner, "Issue 2")

    response = client.get("/api/v1/dashboard/summary", headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json()["open_requests"] >= 2


def test_at_risk_issues_returns_a_real_list_not_just_a_count(client, db_session, ai_session_factory):
    from tests.factories import make_category, make_sla_rule, make_team
    from app.models.routing_rule import RoutingRule
    from app.services.ai_analysis_service import run_ai_analysis
    from app.services.ai_provider import AISuggestion
    from tests.fake_ai_provider import FakeAIProvider
    import uuid

    owner = make_user_with_role(db_session, "USER", "dash-owner5@example.com")
    category = make_category(db_session, f"Cat-{uuid.uuid4().hex[:8]}")
    team = make_team(db_session, f"Team-{uuid.uuid4().hex[:8]}")
    db_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
    # A 0-minute SLA duration means the deadline is effectively "now" the
    # instant the SLA record is created, so the issue is deterministically
    # breached immediately - no need to wait out a real threshold window
    # (a 1-minute SLA wouldn't cross the 20%-remaining at-risk line for
    # close to 48 seconds, which isn't something a test should wait on).
    make_sla_rule(db_session, category, first_response_minutes=0, resolution_minutes=0)
    response = client.post(
        "/api/v1/issues", json={"title": "Urgent", "description": "Description text."}, headers=auth_headers(owner)
    )
    issue_id = uuid.UUID(response.json()["id"])
    db_session.commit()

    run_ai_analysis(
        issue_id,
        provider=FakeAIProvider(
            suggestion=AISuggestion(category=category.name, sub_category=None, priority="HIGH", summary="s", reasoning="r")
        ),
        session_factory=ai_session_factory,
    )

    at_risk_response = client.get("/api/v1/dashboard/at-risk-issues", headers=auth_headers(owner))

    assert at_risk_response.status_code == 200
    ids = [item["id"] for item in at_risk_response.json()]
    assert str(issue_id) in ids


def test_breakdown_reflects_real_status_and_priority_counts(client, db_session):
    owner = make_user_with_role(db_session, "USER", "dash-owner6@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "dash-admin6@example.com")
    _create_via_api(client, owner, "Breakdown issue")

    response = client.get("/api/v1/dashboard/breakdown", headers=auth_headers(admin))

    assert response.status_code == 200
    body = response.json()
    assert body["status_counts"].get("OPEN", 0) >= 1
    assert "ai_analysis_failures" in body
    assert "team_workload" in body


def test_breakdown_team_workload_empty_for_non_admin(client, db_session):
    owner = make_user_with_role(db_session, "USER", "dash-owner7@example.com")

    response = client.get("/api/v1/dashboard/breakdown", headers=auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["team_workload"] == {}
