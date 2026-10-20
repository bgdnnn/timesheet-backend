"""one payslip/P60 per user, tax year and week (other documents exempt)

Revision ID: b7e8f9a0c1d2
Revises: a1f3c2d4e5b6
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e8f9a0c1d2'
down_revision: Union[str, Sequence[str], None] = 'a1f3c2d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_payslip_files_user_year_week', 'payslip_files', ['created_by', 'tax_year', 'tax_week'],
        unique=True, postgresql_where=sa.text("doc_type <> 'document'"),
    )


def downgrade() -> None:
    op.drop_index('uq_payslip_files_user_year_week', table_name='payslip_files')
