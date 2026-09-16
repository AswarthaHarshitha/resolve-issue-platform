import os
from urllib.parse import urlsplit, urlunsplit

os.environ.setdefault("DATABASE_URL", "postgresql://resolve:resolve@localhost:5433/resolve")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.core.config import get_settings

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _test_database_url() -> str:
    settings = get_settings()
    if settings.test_database_url:
        return settings.test_database_url
    parts = urlsplit(settings.database_url)
    return urlunsplit(parts._replace(path="/resolve_test"))


def _admin_database_url(test_url: str) -> str:
    """Same server as the test DB, but pointed at the default `postgres`
    database, needed to run CREATE DATABASE outside any transaction."""
    parts = urlsplit(test_url)
    return urlunsplit(parts._replace(path="/postgres"))


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Create a dedicated `resolve_test` database (never the dev `resolve`
    database) and run every Alembic migration against it, so tests exercise
    the exact same migration path production uses - not a create_all()
    shortcut. Test data never touches the dev/prod database."""
    test_url = _test_database_url()
    admin_url = _admin_database_url(test_url)
    test_db_name = urlsplit(test_url).path.lstrip("/")

    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": test_db_name},
        ).scalar()
        if not exists:
            conn.execute(sa.text(f'CREATE DATABASE "{test_db_name}"'))
    admin_engine.dispose()

    alembic_cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(BACKEND_ROOT, "alembic"))
    # env.py reads this attribute in preference to app settings - see the
    # comment in alembic/env.py for why set_main_option() alone isn't enough.
    alembic_cfg.attributes["sqlalchemy_url"] = test_url
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")

    return test_url


@pytest.fixture(scope="session")
def test_engine(test_db_url):
    engine = sa.create_engine(test_db_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_connection(test_engine):
    """The raw connection+outer transaction underlying db_session, exposed
    separately so a test can open an *additional*, independently
    closeable Session on the same transaction - e.g. to call
    run_ai_analysis with a session_factory that mimics "opens its own
    session" (DECISIONS.md D4) without that session's close() call tearing
    down the shared connection db_session and other fixtures still need."""
    connection = test_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def db_session(db_connection):
    """Each test runs inside its own outer transaction (db_connection),
    rolled back afterward, so tests never leak fixture data into one
    another.

    join_transaction_mode="create_savepoint" means application code that
    calls session.commit() (e.g. app/services/auth_service.py registering a
    user, which commits as part of a normal request) only ends a SAVEPOINT
    nested inside the outer transaction - a new savepoint starts
    automatically, and the outer transaction (and everything committed
    inside it) is still fully discarded when db_connection rolls it back."""
    session: Session = Session(bind=db_connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    """A TestClient wired to the same transactional db_session as the test
    itself, via FastAPI's dependency_overrides - so data a test sets up
    directly (e.g. a RESOLVER user created for an RBAC test) is visible to
    the endpoint code, and anything the endpoint writes is visible to the
    test's assertions, all inside the one transaction db_session rolls back."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def ai_session_factory(db_connection):
    """A session_factory for run_ai_analysis()/request_reanalysis() that
    shares the test's connection/transaction (so it sees data the test set
    up via db_session/client, and vice versa) while still being a genuinely
    separate Session object that run_ai_analysis's own `db.close()` can
    safely close without affecting db_session."""

    def factory() -> Session:
        return Session(bind=db_connection, join_transaction_mode="create_savepoint")

    return factory


@pytest.fixture(autouse=True)
def _reset_auth_rate_limiter():
    """Every test starts with a clean rate-limit counter - otherwise tests
    that exercise /auth/login or /auth/register would accumulate hits on the
    same TestClient-assigned host and could trip 429s for unrelated tests
    later in the suite."""
    from app.core.rate_limit import auth_rate_limiter

    auth_rate_limiter.reset()
    yield
    auth_rate_limiter.reset()
