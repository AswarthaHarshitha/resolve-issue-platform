"""Admin management of reference/config data (DECISIONS.md D16, D39, D42) -
teams, categories, sub-categories, routing rules, SLA rules, and user
role/team/active-state. Replaces the dev-only seed script and manual
database inserts as the real way this configuration gets managed.

Consistent with D15: nothing here ever hard-deletes a row that other data
might reference - "delete" is always is_active=False. Uniqueness violations
(duplicate name, duplicate routing/SLA rule) are left to the database
constraints already built in Phase 2 and translated to 409 by the route
layer, not re-implemented here.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.roles import ALL_ROLE_NAMES, RoleName
from app.models.category import Category
from app.models.role import Role
from app.models.routing_rule import RoutingRule
from app.models.sla_rule import SLARule
from app.models.sub_category import SubCategory
from app.models.team import Team
from app.models.user import User


class NotFoundError(Exception):
    pass


class ValidationError(Exception):
    pass


# --- Teams -------------------------------------------------------------


def list_teams(db: Session) -> List[Team]:
    return list(db.execute(select(Team).order_by(Team.name)).scalars().all())


def create_team(db: Session, *, name: str, description: Optional[str]) -> Team:
    team = Team(name=name, description=description)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def update_team(db: Session, *, team_id: UUID, name, description, is_active) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise NotFoundError()
    if name is not None:
        team.name = name
    if description is not None:
        team.description = description
    if is_active is not None:
        team.is_active = is_active
    db.commit()
    db.refresh(team)
    return team


# --- Categories ----------------------------------------------------------


def list_categories(db: Session) -> List[Category]:
    return list(db.execute(select(Category).order_by(Category.name)).scalars().all())


def create_category(db: Session, *, name: str, description: Optional[str]) -> Category:
    category = Category(name=name, description=description)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_category(db: Session, *, category_id: UUID, name, description, is_active) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise NotFoundError()
    if name is not None:
        category.name = name
    if description is not None:
        category.description = description
    if is_active is not None:
        category.is_active = is_active
    db.commit()
    db.refresh(category)
    return category


def create_sub_category(db: Session, *, category_id: UUID, name: str) -> SubCategory:
    category = db.get(Category, category_id)
    if category is None:
        raise NotFoundError()
    sub_category = SubCategory(category_id=category_id, name=name)
    db.add(sub_category)
    db.commit()
    db.refresh(sub_category)
    return sub_category


def update_sub_category(db: Session, *, sub_category_id: UUID, name, is_active) -> SubCategory:
    sub_category = db.get(SubCategory, sub_category_id)
    if sub_category is None:
        raise NotFoundError()
    if name is not None:
        sub_category.name = name
    if is_active is not None:
        sub_category.is_active = is_active
    db.commit()
    db.refresh(sub_category)
    return sub_category


# --- Routing rules ---------------------------------------------------------


def list_routing_rules(db: Session) -> List[RoutingRule]:
    return list(db.execute(select(RoutingRule)).scalars().all())


def create_routing_rule(
    db: Session, *, category_id: UUID, sub_category_id: Optional[UUID], team_id: UUID
) -> RoutingRule:
    if db.get(Category, category_id) is None:
        raise NotFoundError("category not found")
    if db.get(Team, team_id) is None:
        raise NotFoundError("team not found")
    if sub_category_id is not None:
        sub_category = db.get(SubCategory, sub_category_id)
        if sub_category is None or sub_category.category_id != category_id:
            raise ValidationError("sub_category does not belong to the given category")

    rule = RoutingRule(category_id=category_id, sub_category_id=sub_category_id, team_id=team_id)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_routing_rule(db: Session, *, rule_id: UUID, team_id, is_active) -> RoutingRule:
    rule = db.get(RoutingRule, rule_id)
    if rule is None:
        raise NotFoundError()
    if team_id is not None:
        if db.get(Team, team_id) is None:
            raise NotFoundError("team not found")
        rule.team_id = team_id
    if is_active is not None:
        rule.is_active = is_active
    db.commit()
    db.refresh(rule)
    return rule


# --- SLA rules ------------------------------------------------------------


def list_sla_rules(db: Session) -> List[SLARule]:
    return list(db.execute(select(SLARule)).scalars().all())


def create_sla_rule(
    db: Session, *, category_id: UUID, priority, first_response_minutes: int, resolution_minutes: int
) -> SLARule:
    if db.get(Category, category_id) is None:
        raise NotFoundError("category not found")
    if resolution_minutes < first_response_minutes:
        raise ValidationError("resolution_minutes must be >= first_response_minutes")

    rule = SLARule(
        category_id=category_id,
        priority=priority,
        first_response_minutes=first_response_minutes,
        resolution_minutes=resolution_minutes,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_sla_rule(db: Session, *, rule_id: UUID, first_response_minutes, resolution_minutes, is_active) -> SLARule:
    rule = db.get(SLARule, rule_id)
    if rule is None:
        raise NotFoundError()
    if first_response_minutes is not None:
        rule.first_response_minutes = first_response_minutes
    if resolution_minutes is not None:
        rule.resolution_minutes = resolution_minutes
    if rule.resolution_minutes < rule.first_response_minutes:
        raise ValidationError("resolution_minutes must be >= first_response_minutes")
    if is_active is not None:
        rule.is_active = is_active
    db.commit()
    db.refresh(rule)
    return rule


# --- Users ------------------------------------------------------------------


def list_users(db: Session, *, page: int, page_size: int) -> List[User]:
    stmt = select(User).order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return list(db.execute(stmt).scalars().all())


def update_user(
    db: Session,
    *,
    user_id: UUID,
    role: Optional[str],
    team_id: Optional[UUID],
    is_active: Optional[bool],
) -> User:
    """Enforces the D18 rule at the one real provisioning entry point that
    now exists: a user being set to RESOLVER must end up with a team (either
    passed here or already set); a user moved away from RESOLVER has their
    team cleared, since "team" is only meaningful for resolvers."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError()

    if role is not None:
        if role not in ALL_ROLE_NAMES:
            raise ValidationError(f"Unknown role: {role!r}")
        role_row = db.execute(select(Role).where(Role.name == role)).scalar_one()
        user.role_id = role_row.id

    if team_id is not None:
        user.team_id = team_id

    final_role_name = role if role is not None else user.role.name
    if final_role_name == RoleName.RESOLVER and user.team_id is None:
        raise ValidationError("A resolver must be assigned to a team")
    if final_role_name != RoleName.RESOLVER:
        user.team_id = None

    if is_active is not None:
        user.is_active = is_active

    db.commit()
    db.refresh(user)
    return user
