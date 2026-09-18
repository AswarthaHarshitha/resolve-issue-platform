"""Phase 9 concurrency attack: run_ai_analysis vs. a concurrent manual
transition on the same issue.

Reproduced live against a real running server, then confirmed
deterministically here: run_ai_analysis loads its Issue via a plain,
unlocked db.get() at the top of the function, then spends several real
seconds calling the AI provider before it ever writes anything. Every other
issue mutator (issue_service.transition_status, comment_service.add_comment,
assignment_service.update_assignment) reads through
issue_repository.get_issue_by_id_for_update (SELECT ... FOR UPDATE) instead,
specifically so a transition is always validated against the real current
state, never a value read before a concurrent change (DECISIONS.md D12).

Before the fix, route_issue's own "only route an issue that's still OPEN"
guard was checked against the stale in-memory snapshot taken before the
provider call - so if a resolver validly transitioned the issue (e.g.
OPEN -> TRIAGED) *while* the AI call was in flight, the AI task's eventual
write would silently overwrite that already-committed, already-reported
success with its own routing decision, as if the manual transition had never
happened. The fix (db.refresh(issue, with_for_update=True) right before
route_issue) forces a fresh, locked re-read at the last possible moment, so
the guard sees real current state - a lock is never held for the multi
-second AI provider call itself, only for the brief final write, matching
every other mutator's pattern."""

import threading

from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.enums import IssueStatus
from app.models.issue import Issue
from app.models.issue_status_history import IssueStatusHistory
from app.models.role import Role
from app.models.routing_rule import RoutingRule
from app.models.team import Team
from app.models.user import User as UserModel
from app.services import issue_service
from app.services.ai_analysis_service import run_ai_analysis
from app.services.ai_provider import AIProvider, AISuggestion
from tests.factories import make_category, make_team


class _BlockingProvider(AIProvider):
    """classify() blocks until released, so the test controls exactly when
    the AI task's write (route_issue) happens relative to a concurrent
    manual transition's write."""

    def __init__(self, suggestion, release_event, started_event):
        self._suggestion = suggestion
        self._release_event = release_event
        self._started_event = started_event

    def classify(self, *, title, description):
        self._started_event.set()
        self._release_event.wait(timeout=10)
        return self._suggestion


def test_manual_transition_during_ai_analysis_is_not_silently_overwritten(test_engine):
    setup_engine = test_engine
    with Session(bind=setup_engine) as setup_session:
        user_role = setup_session.query(Role).filter_by(name="USER").one()
        resolver_role = setup_session.query(Role).filter_by(name="RESOLVER").one()
        category = make_category(setup_session, f"ConcurCat-{id(object())}")
        team = make_team(setup_session, f"ConcurTeam-{id(object())}")
        setup_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))

        owner = UserModel(
            email="ai-race-owner@example.com", password_hash="x", full_name="Owner", role_id=user_role.id
        )
        resolver = UserModel(
            email="ai-race-resolver@example.com",
            password_hash="x",
            full_name="Resolver",
            role_id=resolver_role.id,
        )
        setup_session.add_all([owner, resolver])
        setup_session.flush()

        issue = issue_service.create_issue(setup_session, owner=owner, title="Concurrency repro", description="...")
        setup_session.commit()
        issue_id = issue.id
        resolver_id = resolver.id
        owner_id = owner.id
        category_id = category.id
        team_id = team.id

    release_event = threading.Event()
    started_event = threading.Event()
    results = {}

    def run_ai_thread():
        with Session(bind=setup_engine) as s:
            real_name = s.get(Category, category_id).name
        suggestion = AISuggestion(category=real_name, sub_category=None, priority="LOW", summary="s", reasoning="r")
        provider = _BlockingProvider(suggestion, release_event, started_event)

        def factory():
            return Session(bind=setup_engine)

        run_ai_analysis(issue_id, provider=provider, session_factory=factory)

    thread_ai = threading.Thread(target=run_ai_thread)
    thread_ai.start()

    try:
        # Wait until the AI task has taken its early, unlocked snapshot
        # (status=OPEN) and is blocked "calling the provider".
        assert started_event.wait(timeout=10), "AI task never reached the provider call"

        # While the AI task is still mid-flight, perform a real manual
        # transition through the actual authorized code path.
        with Session(bind=setup_engine) as manual_session:
            resolver_conn = manual_session.get(UserModel, resolver_id)
            manual_issue = issue_service.transition_status(
                manual_session, issue_id=issue_id, target_status=IssueStatus.TRIAGED, current_user=resolver_conn
            )
            results["manual_result_status"] = manual_issue.status

        # Now let the AI task's provider call return and proceed to route.
        release_event.set()
        thread_ai.join(timeout=10)
        assert not thread_ai.is_alive(), "AI thread did not finish"

        with Session(bind=setup_engine) as verify_session:
            final_issue = verify_session.get(Issue, issue_id)
            history = (
                verify_session.query(IssueStatusHistory)
                .filter_by(issue_id=issue_id)
                .order_by(IssueStatusHistory.created_at)
                .all()
            )

            # The manual transition told the resolver it succeeded - it must
            # actually have stuck, not be silently reverted by the AI task's
            # stale write.
            assert results["manual_result_status"] == IssueStatus.TRIAGED
            assert final_issue.status == IssueStatus.TRIAGED
            # AI routing correctly deferred to the already-progressed issue
            # (its own "only route an OPEN issue" guard, now checked against
            # fresh locked data) rather than silently re-routing it.
            assert final_issue.current_team_id is None
            assert [h.trigger.value for h in history] == ["SYSTEM_CREATE", "MANUAL"]
    finally:
        release_event.set()  # unblock the AI thread even if an assertion above failed
        thread_ai.join(timeout=10)
        with Session(bind=setup_engine) as cleanup_session:
            from app.models.ai_analysis_result import AIAnalysisResult

            cleanup_session.query(AIAnalysisResult).filter_by(issue_id=issue_id).delete()
            cleanup_session.query(IssueStatusHistory).filter_by(issue_id=issue_id).delete()
            cleanup_session.query(Issue).filter_by(id=issue_id).delete()
            cleanup_session.query(UserModel).filter(
                UserModel.id.in_([resolver_id, owner_id])
            ).delete(synchronize_session=False)
            cleanup_session.query(RoutingRule).filter_by(category_id=category_id).delete()
            cleanup_session.query(Team).filter_by(id=team_id).delete()
            cleanup_session.query(Category).filter_by(id=category_id).delete()
            cleanup_session.commit()


def test_ai_routing_still_proceeds_normally_without_a_concurrent_transition(db_session, ai_session_factory):
    """Regression guard: the db.refresh(with_for_update=True) fix must not
    break the ordinary, uncontested case - an issue with no concurrent
    manual change still gets routed normally."""
    from tests.factories import make_issue, make_user_with_role
    from app.services.ai_analysis_service import run_ai_analysis
    from app.models.enums import AIAnalysisStatus

    owner = make_user_with_role(db_session, "USER", "ai-race-normal-owner@example.com")
    category = make_category(db_session, "ConcurCatNormal")
    team = make_team(db_session, "ConcurTeamNormal")
    db_session.add(RoutingRule(category_id=category.id, sub_category_id=None, team_id=team.id))
    issue = make_issue(db_session, owner, category=None)
    db_session.commit()

    provider = _BlockingProvider(
        AISuggestion(category="ConcurCatNormal", sub_category=None, priority="LOW", summary="s", reasoning="r"),
        release_event=threading.Event(),
        started_event=threading.Event(),
    )
    provider._release_event.set()  # don't actually block for this test

    run_ai_analysis(issue.id, provider=provider, session_factory=ai_session_factory)

    db_session.refresh(issue)
    assert issue.ai_analysis_status == AIAnalysisStatus.COMPLETED
    assert issue.status == IssueStatus.ASSIGNED
    assert issue.current_team_id == team.id
