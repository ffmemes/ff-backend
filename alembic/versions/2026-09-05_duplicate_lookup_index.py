"""Index duplicate-family lookups used by feed repeat protection."""

from alembic import op

revision = "c9e3a7b1d5f2"
down_revision = "b8d2f6a9c1e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "meme_duplicate_of_idx", "meme", ["duplicate_of"], postgresql_concurrently=True
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("meme_duplicate_of_idx", table_name="meme", postgresql_concurrently=True)
