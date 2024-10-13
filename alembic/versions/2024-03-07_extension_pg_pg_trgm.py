"""extension_pg_pg_trgm

Revision ID: b780738c821f
Revises: 594149282af3
Create Date: 2024-03-07 19:11:32.863862

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b780738c821f"
down_revision = "594149282af3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    pass
