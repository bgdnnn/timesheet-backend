"""schema cleanup after audit: exact money types, unique rules, doc_type, drop unused columns

Revision ID: a1f3c2d4e5b6
Revises: 959c93cbecc0
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f3c2d4e5b6'
down_revision: Union[str, Sequence[str], None] = '959c93cbecc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY_COLUMNS = [("users", "wage"), ("users", "guild_tax"), ("weekly_earnings", "hourly_wage"), ("weekly_earnings", "guild_tax")]
UNUSED_PROFILE_COLUMNS = [
    ("username", sa.String()), ("ni_number", sa.String()), ("region", sa.String()),
    ("pension_employee_percent", sa.Numeric(5, 4)),
    ("baseline_gross", sa.Numeric(10, 2)), ("baseline_paye", sa.Numeric(10, 2)), ("baseline_ni", sa.Numeric(10, 2)),
    ("baseline_pension", sa.Numeric(10, 2)), ("baseline_net", sa.Numeric(10, 2)),
    ("ytd_gross", sa.Numeric(10, 2)), ("ytd_tax", sa.Numeric(10, 2)), ("ytd_ni", sa.Numeric(10, 2)), ("ytd_pension", sa.Numeric(10, 2)),
    ("tax_offset", sa.Numeric(10, 2)), ("ni_offset", sa.Numeric(10, 2)),
]


def upgrade() -> None:
    # Payslip archive can also hold other payroll paperwork
    op.add_column('payslip_files', sa.Column('doc_type', sa.String(16), nullable=False, server_default='payslip'))

    for table, column in MONEY_COLUMNS:
        op.alter_column(table, column, type_=sa.Numeric(10, 2), postgresql_using=f"round({column}::numeric, 2)")

    # Model says NOT NULL; the column was added by a raw ALTER without it
    op.execute("UPDATE users SET is_auto_upload_enabled = false WHERE is_auto_upload_enabled IS NULL")
    op.alter_column('users', 'is_auto_upload_enabled', nullable=False)

    op.create_unique_constraint('uq_weekly_earnings_user_week', 'weekly_earnings', ['created_by', 'week_start'])
    op.create_unique_constraint('uq_holidays_user_date', 'holidays', ['created_by', 'date'])

    op.create_index('ix_time_entries_created_by_date', 'time_entries', ['created_by', 'date'])
    op.drop_index('ix_expenses_id', table_name='expenses')

    op.drop_column('users', 'password_hash')
    op.drop_column('time_entries', 'duration_minutes')
    op.drop_index('ix_payroll_profiles_username', table_name='payroll_profiles')
    for column, _ in UNUSED_PROFILE_COLUMNS:
        op.drop_column('payroll_profiles', column)


def downgrade() -> None:
    # Dropping doc_type would silently turn payroll documents back into "payslips"
    if op.get_bind().execute(sa.text("SELECT count(*) FROM payslip_files WHERE doc_type = 'document'")).scalar():
        raise RuntimeError("payslip_files has doc_type='document' rows; move or delete them before downgrading")

    # Dropped values are not restored; they are kept in the pre-migration backup
    for column, type_ in UNUSED_PROFILE_COLUMNS:
        op.add_column('payroll_profiles', sa.Column(column, type_, nullable=True))
    op.execute("UPDATE payroll_profiles SET region = 'rUK', tax_offset = 0, ni_offset = 0")
    for column in ("region", "tax_offset", "ni_offset"):
        op.alter_column('payroll_profiles', column, nullable=False)
    op.create_index('ix_payroll_profiles_username', 'payroll_profiles', ['username'])
    op.add_column('time_entries', sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='0'))
    op.execute("UPDATE time_entries SET duration_minutes = round((hours_worked + travel_time) * 60)")
    op.add_column('users', sa.Column('password_hash', sa.String(255), nullable=True))

    op.create_index('ix_expenses_id', 'expenses', ['id'])
    op.drop_index('ix_time_entries_created_by_date', table_name='time_entries')
    op.drop_constraint('uq_holidays_user_date', 'holidays', type_='unique')
    op.drop_constraint('uq_weekly_earnings_user_week', 'weekly_earnings', type_='unique')

    for table, column in MONEY_COLUMNS:
        op.alter_column(table, column, type_=sa.Float())

    op.alter_column('users', 'is_auto_upload_enabled', nullable=True)
    op.drop_column('payslip_files', 'doc_type')
