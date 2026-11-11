"""Durable single-use records for external user-system login tickets.

Replaces the process-local consumed-jti cache behind
``GET /api/v1/auth/external/login``: with more than one Gateway worker (or more
than one replica) an in-process record let the same ticket be redeemed once per
process. The primary key on ``jti`` makes the claim atomic across every process
sharing the application database.

Revision ID: 0053_external_login_tickets
Revises: 0052_batch_continuation
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_external_login_tickets"
down_revision = "0052_batch_continuation"
branch_labels = None
depends_on = None

_TABLE = "external_login_tickets"
_INDEX = "ix_external_login_tickets_expires_at"


def upgrade():
    # A fresh database gets the table from ``create_all`` (the model is registered
    # in ``deerflow.persistence.models``); only a legacy database needs this DDL.
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti", name="pk_external_login_tickets"),
    )
    op.create_index(_INDEX, _TABLE, ["expires_at"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _INDEX in {index["name"] for index in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
