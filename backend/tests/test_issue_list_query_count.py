"""Phase 9 performance finding: GET /issues serializes every returned issue
through build_issue_public, which touches owner/category/sub_category/
current_team/current_resolver/sla_record (and sla_record.pause_intervals)
for each one. Issue's relationships default to lazy loading, so without
eager-loading options this was an N+1 query pattern - up to ~6 extra queries
per issue, unbounded by page_size (up to 100). issue_repository.list_issues
now eager-loads all of these with selectinload, which issues a small,
constant number of extra queries (one per relationship, batched across the
whole page) regardless of how many issues are returned."""

from sqlalchemy import event

from tests.auth_helpers import auth_headers
from tests.factories import make_category, make_sub_category, make_team, make_user_with_role


def _create_via_api(client, user, title):
    response = client.post(
        "/api/v1/issues", json={"title": title, "description": "Query count test."}, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_listing_many_issues_does_not_scale_linearly_in_query_count(client, db_session, db_connection):
    owner = make_user_with_role(db_session, "USER", "querycount-owner@example.com")
    admin = make_user_with_role(db_session, "ADMIN", "querycount-admin@example.com")
    category = make_category(db_session, "QueryCountCat")
    make_sub_category(db_session, category, "QueryCountSub")
    team = make_team(db_session, "QueryCountTeam")
    db_session.commit()

    issue_ids = [_create_via_api(client, owner, f"Query count issue {i}")["id"] for i in range(8)]
    for issue_id in issue_ids:
        response = client.patch(
            f"/api/v1/issues/{issue_id}/assignment", json={"team_id": str(team.id)}, headers=auth_headers(admin)
        )
        assert response.status_code == 200

    statement_count = {"n": 0}

    def _count(*args, **kwargs):
        statement_count["n"] += 1

    event.listen(db_connection, "before_cursor_execute", _count)
    try:
        response = client.get("/api/v1/issues?page_size=20", headers=auth_headers(admin))
    finally:
        event.remove(db_connection, "before_cursor_execute", _count)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 8

    # A handful of fixed queries (count, the page select, and one
    # selectinload batch per eager-loaded relationship) - not one query per
    # issue per relationship. Generous bound: well under 8 issues x 6
    # relationships (48+) if this regressed back to N+1.
    assert statement_count["n"] < 15, f"expected a small, bounded query count, got {statement_count['n']}"
