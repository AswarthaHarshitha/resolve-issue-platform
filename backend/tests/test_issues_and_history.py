"""Scenarios 8-11: issues, comments, status history, and assignment history.
Also covers several attack-review questions from the Phase 2 spec: deleting a
user/team/category that's referenced, invalid category/sub_category pairing on
an issue, and cascade behavior when an issue itself is deleted."""

import pytest
import sqlalchemy.exc

from app.models.enums import IssueStatus, StatusChangeTrigger
from app.models.issue import Issue
from app.models.issue_assignment import IssueAssignment
from app.models.issue_comment import IssueComment
from app.models.issue_status_history import IssueStatusHistory
from tests.factories import make_category, make_issue, make_role, make_sub_category, make_team, make_user


@pytest.fixture()
def owner(db_session):
    role = make_role(db_session, "TEST_USER_ROLE")
    return make_user(db_session, role, email="owner@example.com")


@pytest.fixture()
def resolver(db_session):
    role = make_role(db_session, "TEST_RESOLVER_ROLE")
    team = make_team(db_session, "IT Support")
    return make_user(db_session, role, email="resolver@example.com", team=team)


def test_issue_references_owner_category_sub_category(db_session, owner):
    category = make_category(db_session, "IT")
    sub_category = make_sub_category(db_session, category, "Network")

    issue = make_issue(db_session, owner, category=category, sub_category=sub_category)
    db_session.refresh(issue)

    assert issue.owner.email == "owner@example.com"
    assert issue.category.name == "IT"
    assert issue.sub_category.name == "Network"
    assert issue.status == IssueStatus.OPEN


def test_issue_rejects_sub_category_from_a_different_category(db_session, owner):
    category_a = make_category(db_session, "IT")
    category_b = make_category(db_session, "Facilities")
    sub_category_of_b = make_sub_category(db_session, category_b, "Plumbing")

    mismatched = Issue(
        owner_id=owner.id,
        title="Bad pairing",
        description="category/sub_category mismatch",
        category_id=category_a.id,
        sub_category_id=sub_category_of_b.id,
    )
    db_session.add(mismatched)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_issue_current_team_and_resolver_can_be_set(db_session, owner, resolver):
    team = resolver.team
    issue = make_issue(db_session, owner)
    issue.current_team_id = team.id
    issue.current_resolver_id = resolver.id
    db_session.flush()
    db_session.refresh(issue)

    assert issue.current_team.name == "IT Support"
    assert issue.current_resolver.email == "resolver@example.com"


def test_comment_references_issue_and_author(db_session, owner):
    issue = make_issue(db_session, owner)
    comment = IssueComment(issue_id=issue.id, author_id=owner.id, body="Any update?")
    db_session.add(comment)
    db_session.flush()
    db_session.refresh(issue)

    assert len(issue.comments) == 1
    assert issue.comments[0].author.email == "owner@example.com"


def test_status_history_records_transition_with_actor(db_session, owner, resolver):
    issue = make_issue(db_session, owner)

    creation_row = IssueStatusHistory(
        issue_id=issue.id,
        previous_status=None,
        new_status=IssueStatus.OPEN,
        trigger=StatusChangeTrigger.SYSTEM_CREATE,
        changed_by_id=owner.id,
    )
    routed_row = IssueStatusHistory(
        issue_id=issue.id,
        previous_status=IssueStatus.OPEN,
        new_status=IssueStatus.TRIAGED,
        trigger=StatusChangeTrigger.AI_ROUTING,
        changed_by_id=None,  # automated, no human actor
    )
    db_session.add_all([creation_row, routed_row])
    db_session.flush()
    db_session.refresh(issue)

    assert [row.new_status for row in issue.status_history] == [IssueStatus.OPEN, IssueStatus.TRIAGED]
    assert issue.status_history[1].changed_by_id is None
    assert issue.status_history[1].trigger == StatusChangeTrigger.AI_ROUTING


def test_assignment_history_is_append_only_and_preserves_prior_rows(db_session, owner, resolver):
    issue = make_issue(db_session, owner)
    team = resolver.team

    first_assignment = IssueAssignment(issue_id=issue.id, team_id=team.id, reason="initial routing")
    db_session.add(first_assignment)
    db_session.flush()

    second_assignment = IssueAssignment(
        issue_id=issue.id, team_id=team.id, resolver_id=resolver.id, reason="assigned to resolver"
    )
    db_session.add(second_assignment)
    db_session.flush()
    db_session.refresh(issue)

    # Both rows still exist - the second assignment did not overwrite the first.
    assert len(issue.assignments) == 2
    assert issue.assignments[0].resolver_id is None
    assert issue.assignments[1].resolver_id == resolver.id


def test_deleting_issue_cascades_to_its_owned_history(db_session, owner):
    issue = make_issue(db_session, owner)
    db_session.add(IssueComment(issue_id=issue.id, author_id=owner.id, body="hello"))
    db_session.add(
        IssueStatusHistory(
            issue_id=issue.id,
            previous_status=None,
            new_status=IssueStatus.OPEN,
            trigger=StatusChangeTrigger.SYSTEM_CREATE,
        )
    )
    db_session.flush()
    issue_id = issue.id

    db_session.delete(issue)
    db_session.flush()

    assert db_session.query(IssueComment).filter_by(issue_id=issue_id).count() == 0
    assert db_session.query(IssueStatusHistory).filter_by(issue_id=issue_id).count() == 0


def test_cannot_delete_user_who_owns_an_issue(db_session, owner):
    make_issue(db_session, owner)

    db_session.delete(owner)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_cannot_delete_team_referenced_by_current_assignment(db_session, owner, resolver):
    team = resolver.team
    issue = make_issue(db_session, owner)
    issue.current_team_id = team.id
    db_session.flush()

    db_session.delete(team)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_cannot_delete_category_referenced_by_an_issue(db_session, owner):
    category = make_category(db_session, "IT")
    make_issue(db_session, owner, category=category)

    db_session.delete(category)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()
