"""seed baseline roles

Revision ID: d3ba9b345743
Revises: 8f6a19a46c61
Create Date: 2026-09-16 17:42:01.891567

USER / RESOLVER / ADMIN are required reference data, not demo/fake data - the
app cannot function (e.g. registration has nothing to assign a new user to)
without them, so they belong in a migration that runs in every environment,
including production. This is distinct from the dev-only seed script planned
for later phases, which will insert throwaway local-testing data and must
never run against production.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3ba9b345743'
down_revision: Union[str, None] = '8f6a19a46c61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_NAMES = ["USER", "RESOLVER", "ADMIN"]

roles_table = sa.table(
    "roles",
    sa.column("id", sa.UUID()),
    sa.column("name", sa.String()),
)


def upgrade() -> None:
    op.bulk_insert(
        roles_table,
        [{"id": uuid.uuid4(), "name": name} for name in ROLE_NAMES],
    )


def downgrade() -> None:
    op.execute(roles_table.delete().where(roles_table.c.name.in_(ROLE_NAMES)))
