"""Scenarios 3-7: roles/teams/categories/sub_categories/routing_rules/sla_rules
relationships, plus the unique-constraint half of scenario 14 for this group."""

import pytest
import sqlalchemy.exc

from app.models.category import Category
from app.models.enums import IssuePriority
from app.models.role import Role
from app.models.routing_rule import RoutingRule
from app.models.sla_rule import SLARule
from app.models.team import Team
from tests.factories import make_category, make_role, make_sla_rule, make_sub_category, make_team, make_user


def test_user_belongs_to_role(db_session):
    role = make_role(db_session, "TEST_RESOLVER")
    user = make_user(db_session, role, email="resolver@example.com")

    db_session.flush()
    db_session.refresh(user)

    assert user.role.name == "TEST_RESOLVER"


def test_user_belongs_to_team(db_session):
    role = make_role(db_session, "TEST_RESOLVER")
    team = make_team(db_session, "IT Support")
    user = make_user(db_session, role, email="resolver2@example.com", team=team)

    db_session.refresh(user)

    assert user.team.name == "IT Support"


def test_user_team_is_optional(db_session):
    role = make_role(db_session, "TEST_USER")
    user = make_user(db_session, role, email="enduser@example.com")

    assert user.team_id is None


def test_category_has_sub_categories(db_session):
    category = make_category(db_session, "IT")
    make_sub_category(db_session, category, "Network")
    make_sub_category(db_session, category, "Hardware")

    db_session.refresh(category)

    names = {sub.name for sub in category.sub_categories}
    assert names == {"Network", "Hardware"}


def test_sub_category_cannot_exist_without_category(db_session):
    from app.models.sub_category import SubCategory
    import uuid

    orphan = SubCategory(category_id=uuid.uuid4(), name="Orphan")
    db_session.add(orphan)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_routing_rule_references_category_sub_category_and_team(db_session):
    category = make_category(db_session, "IT")
    sub_category = make_sub_category(db_session, category, "Network")
    team = make_team(db_session, "Network Ops")

    rule = RoutingRule(category_id=category.id, sub_category_id=sub_category.id, team_id=team.id)
    db_session.add(rule)
    db_session.flush()
    db_session.refresh(rule)

    assert rule.category.name == "IT"
    assert rule.sub_category.name == "Network"
    assert rule.team.name == "Network Ops"


def test_routing_rule_rejects_sub_category_from_a_different_category(db_session):
    category_a = make_category(db_session, "IT")
    category_b = make_category(db_session, "Facilities")
    sub_category_of_b = make_sub_category(db_session, category_b, "Plumbing")
    team = make_team(db_session, "Facilities Ops")

    # Claims category_a but points sub_category_id at a sub-category of category_b.
    mismatched_rule = RoutingRule(
        category_id=category_a.id, sub_category_id=sub_category_of_b.id, team_id=team.id
    )
    db_session.add(mismatched_rule)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_duplicate_category_level_routing_rule_rejected(db_session):
    category = make_category(db_session, "IT")
    team = make_team(db_session, "IT Support")

    db_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
    db_session.flush()

    db_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_duplicate_sub_category_routing_rule_rejected(db_session):
    category = make_category(db_session, "IT")
    sub_category = make_sub_category(db_session, category, "Network")
    team = make_team(db_session, "IT Support")

    db_session.add(RoutingRule(category_id=category.id, sub_category_id=sub_category.id, team_id=team.id))
    db_session.flush()

    db_session.add(RoutingRule(category_id=category.id, sub_category_id=sub_category.id, team_id=team.id))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_category_level_and_sub_category_level_rules_can_coexist(db_session):
    """A category-wide catch-all rule and a specific sub-category override are not
    duplicates of each other - only exact (category, sub_category) pairs collide."""
    category = make_category(db_session, "IT")
    sub_category = make_sub_category(db_session, category, "Network")
    team = make_team(db_session, "IT Support")

    db_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
    db_session.add(RoutingRule(category_id=category.id, sub_category_id=sub_category.id, team_id=team.id))

    db_session.flush()  # should not raise


def test_sla_rule_references_category_and_priority(db_session):
    category = make_category(db_session, "IT")
    rule = make_sla_rule(db_session, category, priority=IssuePriority.HIGH)

    db_session.refresh(rule)

    assert rule.category.name == "IT"
    assert rule.priority == IssuePriority.HIGH


def test_duplicate_sla_rule_for_same_category_and_priority_rejected(db_session):
    category = make_category(db_session, "IT")
    make_sla_rule(db_session, category, priority=IssuePriority.HIGH)

    db_session.add(
        SLARule(
            category_id=category.id,
            priority=IssuePriority.HIGH,
            first_response_minutes=30,
            resolution_minutes=720,
        )
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_same_category_different_priority_sla_rules_allowed(db_session):
    category = make_category(db_session, "IT")
    make_sla_rule(db_session, category, priority=IssuePriority.HIGH)
    make_sla_rule(db_session, category, priority=IssuePriority.LOW, first_response_minutes=240)

    db_session.flush()  # should not raise


@pytest.mark.parametrize(
    "model, kwargs",
    [
        (Role, {"name": "TEST_DUPLICATE_ROLE"}),
        (Team, {"name": "IT Support"}),
        (Category, {"name": "IT"}),
    ],
)
def test_unique_name_constraints(db_session, model, kwargs):
    db_session.add(model(**kwargs))
    db_session.flush()

    db_session.add(model(**kwargs))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()
