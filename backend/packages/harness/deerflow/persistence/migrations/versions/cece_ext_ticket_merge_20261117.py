"""Merge historical external-login tickets with the current migration chain.

Some deployments applied the external-user integration while it lived on a
branch from 0052. The integration was later removed from the source tree but
its database revision remained deployed. This merge point keeps both histories
valid and lets bootstrap upgrade either one to a common head.
"""

revision = "cece_ext_ticket_merge_20261117"
down_revision = ("0055_thread_shares", "0053_external_login_tickets")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
