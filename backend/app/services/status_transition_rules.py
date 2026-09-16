"""The server-side status transition allow-list (DECISIONS.md D8). Pure data
and a pure function - no DB, no FastAPI - so the rule itself is trivially
testable and has exactly one place it can be read from.

RESOLVED has no outgoing transition here on purpose: RESOLVED -> CLOSED is
reserved for the dedicated user-confirmation flow built in Phase 7
(DECISIONS.md D9), not this generic transition endpoint - a resolver/admin
cannot self-close an issue through PATCH /issues/{id}/status.
"""

from typing import Dict, FrozenSet

from app.models.enums import IssueStatus

ALLOWED_TRANSITIONS: Dict[IssueStatus, FrozenSet[IssueStatus]] = {
    IssueStatus.OPEN: frozenset({IssueStatus.TRIAGED}),
    IssueStatus.TRIAGED: frozenset({IssueStatus.ASSIGNED}),
    IssueStatus.ASSIGNED: frozenset({IssueStatus.IN_PROGRESS}),
    IssueStatus.IN_PROGRESS: frozenset({IssueStatus.WAITING_FOR_USER, IssueStatus.RESOLVED}),
    IssueStatus.WAITING_FOR_USER: frozenset({IssueStatus.IN_PROGRESS}),
    IssueStatus.RESOLVED: frozenset(),
    IssueStatus.CLOSED: frozenset(),
}


def is_transition_allowed(current: IssueStatus, target: IssueStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())
