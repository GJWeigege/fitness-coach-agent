"""benchmark run owner

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "benchmark_runs",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE benchmark_runs
        SET created_by_user_id = (
            SELECT id FROM users WHERE role = 'admin' ORDER BY created_at ASC LIMIT 1
        )
        WHERE created_by_user_id IS NULL
          AND EXISTS (SELECT 1 FROM users WHERE role = 'admin')
        """
    )
    op.execute("DELETE FROM benchmark_runs WHERE created_by_user_id IS NULL")
    op.alter_column("benchmark_runs", "created_by_user_id", nullable=False)
    op.create_foreign_key(
        "fk_benchmark_runs_created_by_user_id_users",
        "benchmark_runs",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_benchmark_runs_created_by_user_id"),
        "benchmark_runs",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_benchmark_runs_created_by_user_id"), table_name="benchmark_runs")
    op.drop_constraint("fk_benchmark_runs_created_by_user_id_users", "benchmark_runs", type_="foreignkey")
    op.drop_column("benchmark_runs", "created_by_user_id")
