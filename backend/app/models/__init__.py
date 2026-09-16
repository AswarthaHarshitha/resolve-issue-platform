"""Import every model so Base.metadata (and the declarative registry used to
resolve string-based relationship() targets) is fully populated before Alembic
autogenerate, create_all, or any query runs."""

from app.models.category import Category
from app.models.issue import Issue
from app.models.issue_assignment import IssueAssignment
from app.models.issue_comment import IssueComment
from app.models.issue_status_history import IssueStatusHistory
from app.models.role import Role
from app.models.routing_rule import RoutingRule
from app.models.sla_pause_interval import SLAPauseInterval
from app.models.sla_record import SLARecord
from app.models.sla_rule import SLARule
from app.models.sub_category import SubCategory
from app.models.team import Team
from app.models.user import User

__all__ = [
    "Category",
    "Issue",
    "IssueAssignment",
    "IssueComment",
    "IssueStatusHistory",
    "Role",
    "RoutingRule",
    "SLAPauseInterval",
    "SLARecord",
    "SLARule",
    "SubCategory",
    "Team",
    "User",
]
