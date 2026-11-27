"""Merge the CeCe external-login compatibility branch into the current chain."""

revision = "cece_merge_0060_20261125"
down_revision = ("0060_coordination_run_settings", "cece_ext_ticket_merge_20261117")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
