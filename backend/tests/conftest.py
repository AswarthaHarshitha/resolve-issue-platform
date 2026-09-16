import os
from urllib.parse import urlsplit, urlunsplit

os.environ.setdefault("DATABASE_URL", "postgresql://resolve:resolve@localhost:5433/resolve")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

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
def db_session(test_engine):
    """Each test runs inside its own transaction, rolled back afterward, so
    tests never leak fixture data into one another."""
    connection = test_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session: Session = SessionLocal()

    try:
        yield session
    finally:
        session.close()
        # A test that triggers an IntegrityError (e.g. asserting a constraint is
        # enforced) leaves SQLAlchemy's own transaction already rolled back -
        # only roll back here if that didn't already happen.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
