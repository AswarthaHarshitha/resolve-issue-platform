"""Scenario 1: database connection works. Scenario 2: migration can create the
expected schema. The test_engine/test_db_url fixtures (session-scoped, in
conftest.py) already proved the migration path works by running
`alembic downgrade base` then `alembic upgrade head` against a fresh
`resolve_test` database before any test in this file runs - this file just
asserts on the result."""

import sqlalchemy as sa

EXPECTED_TABLES = {
    "roles",
    "teams",
    "categories",
    "sub_categories",
    "routing_rules",
    "sla_rules",
    "users",
    "issues",
    "issue_comments",
    "issue_status_history",
    "issue_assignments",
    "sla_records",
    "sla_pause_intervals",
}


def test_database_connection_works(test_engine):
    with test_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT 1")).scalar() == 1


def test_migration_created_expected_tables(test_engine):
    inspector = sa.inspect(test_engine)
    actual_tables = set(inspector.get_table_names())

    assert EXPECTED_TABLES.issubset(actual_tables)


def test_migration_seeded_baseline_roles(db_session):
    from app.models.role import Role

    role_names = {row.name for row in db_session.query(Role).all()}

    assert role_names == {"USER", "RESOLVER", "ADMIN"}


def test_btree_gist_extension_enabled(test_engine):
    with test_engine.connect() as conn:
        installed = conn.execute(
            sa.text("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        ).scalar()

    assert installed == 1
