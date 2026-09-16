"""Small, explicit object builders for tests. Each function inserts (via the
given session, not yet committed) the minimum valid row and returns it -
avoids repeating the same boilerplate across every test file."""

from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.enums import AIAnalysisStatus, IssuePriority, IssueStatus
from app.models.issue import Issue
from app.models.role import Role
from app.models.sla_rule import SLARule
from app.models.sub_category import SubCategory
from app.models.team import Team
from app.models.user import User


def make_role(session: Session, name: str = "TEST_ROLE") -> Role:
    """Uses a non-seeded name by default: the migration already seeds USER/
    RESOLVER/ADMIN (see DECISIONS.md D16), so reusing those names here would
    collide with that reference data instead of testing anything new."""
    role = Role(name=name)
    session.add(role)
    session.flush()
    return role


def make_team(session: Session, name: str = "IT Support") -> Team:
    team = Team(name=name)
    session.add(team)
    session.flush()
    return team


def make_user(session: Session, role: Role, email: str = "user@example.com", team: Team = None) -> User:
    user = User(
        email=email,
        password_hash="not-a-real-hash",
        full_name="Test User",
        role_id=role.id,
        team_id=team.id if team else None,
    )
    session.add(user)
    session.flush()
    return user


def make_category(session: Session, name: str = "IT") -> Category:
    category = Category(name=name)
    session.add(category)
    session.flush()
    return category


def make_sub_category(session: Session, category: Category, name: str = "Network") -> SubCategory:
    sub_category = SubCategory(category_id=category.id, name=name)
    session.add(sub_category)
    session.flush()
    return sub_category


def make_sla_rule(
    session: Session,
    category: Category,
    priority: IssuePriority = IssuePriority.HIGH,
    first_response_minutes: int = 60,
    resolution_minutes: int = 1440,
) -> SLARule:
    rule = SLARule(
        category_id=category.id,
        priority=priority,
        first_response_minutes=first_response_minutes,
        resolution_minutes=resolution_minutes,
    )
    session.add(rule)
    session.flush()
    return rule


def make_issue(
    session: Session,
    owner: User,
    title: str = "Wi-Fi outage in Block B",
    description: str = "The Wi-Fi in Block B has stopped working.",
    category: Category = None,
    sub_category: SubCategory = None,
) -> Issue:
    issue = Issue(
        owner_id=owner.id,
        title=title,
        description=description,
        status=IssueStatus.OPEN,
        ai_analysis_status=AIAnalysisStatus.PENDING,
        category_id=category.id if category else None,
        sub_category_id=sub_category.id if sub_category else None,
    )
    session.add(issue)
    session.flush()
    return issue
