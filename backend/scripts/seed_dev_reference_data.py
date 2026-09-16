"""Development-only convenience seed for categories/sub-categories/teams/
routing rules/SLA rules, so routing has something real to route to on a
freshly migrated local database.

This is explicitly isolated from the production path per the project rules
against fake/demo data: nothing here runs automatically, no migration or
application startup code imports this module, and it refuses to run unless
ENVIRONMENT=development. It is NOT how a real deployment would populate this
configuration - that's an admin-facing management UI, planned for a later
phase (Phase 8). Running it twice is safe (idempotent - it skips anything
that already exists by name).

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.seed_dev_reference_data
"""

import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.category import Category
from app.models.enums import IssuePriority
from app.models.routing_rule import RoutingRule
from app.models.sla_rule import SLARule
from app.models.sub_category import SubCategory
from app.models.team import Team

CATEGORIES = {
    "IT": {
        "sub_categories": ["Network", "Hardware", "Software"],
        "team": "IT Support",
    },
    "Facilities": {
        "sub_categories": ["Plumbing", "Electrical", "HVAC"],
        "team": "Facilities Ops",
    },
}

SLA_MINUTES = {
    IssuePriority.CRITICAL: (15, 240),
    IssuePriority.HIGH: (60, 1440),
    IssuePriority.MEDIUM: (240, 4320),
    IssuePriority.LOW: (480, 10080),
}


def _get_or_create_team(db, name: str) -> Team:
    team = db.query(Team).filter(Team.name == name).first()
    if team is None:
        team = Team(name=name)
        db.add(team)
        db.flush()
    return team


def _get_or_create_category(db, name: str) -> Category:
    category = db.query(Category).filter(Category.name == name).first()
    if category is None:
        category = Category(name=name)
        db.add(category)
        db.flush()
    return category


def _get_or_create_sub_category(db, category: Category, name: str) -> SubCategory:
    sub_category = (
        db.query(SubCategory).filter(SubCategory.category_id == category.id, SubCategory.name == name).first()
    )
    if sub_category is None:
        sub_category = SubCategory(category_id=category.id, name=name)
        db.add(sub_category)
        db.flush()
    return sub_category


def _get_or_create_routing_rule(db, category: Category, team: Team) -> None:
    exists = (
        db.query(RoutingRule)
        .filter(RoutingRule.category_id == category.id, RoutingRule.sub_category_id.is_(None))
        .first()
    )
    if exists is None:
        db.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))


def _get_or_create_sla_rules(db, category: Category) -> None:
    for priority, (first_response, resolution) in SLA_MINUTES.items():
        exists = (
            db.query(SLARule).filter(SLARule.category_id == category.id, SLARule.priority == priority).first()
        )
        if exists is None:
            db.add(
                SLARule(
                    category_id=category.id,
                    priority=priority,
                    first_response_minutes=first_response,
                    resolution_minutes=resolution,
                )
            )


def seed() -> None:
    settings = get_settings()
    if settings.environment != "development":
        print(
            f"Refusing to run: ENVIRONMENT={settings.environment!r}, not 'development'. "
            "This script is a local-dev convenience only.",
            file=sys.stderr,
        )
        sys.exit(1)

    db = SessionLocal()
    try:
        for category_name, config in CATEGORIES.items():
            category = _get_or_create_category(db, category_name)
            for sub_category_name in config["sub_categories"]:
                _get_or_create_sub_category(db, category, sub_category_name)
            team = _get_or_create_team(db, config["team"])
            _get_or_create_routing_rule(db, category, team)
            _get_or_create_sla_rules(db, category)
        db.commit()
        print("Dev reference data seeded (categories, sub-categories, teams, routing rules, SLA rules).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
