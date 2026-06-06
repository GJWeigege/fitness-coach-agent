"""benchmark one active run index

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-06

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_benchmark_runs_one_active
        ON benchmark_runs ((1))
        WHERE status IN ('pending', 'running')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_benchmark_runs_one_active")
