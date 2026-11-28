"""[fork] Remember which maintenance due point was last notified.

Part of the ubuntuaddicted/ododash fork, not upstream OdoDash. If an upstream
migration is later added on the same parent, join the heads with
``flask db merge heads`` rather than editing either.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1a2b3c4d5f6'
down_revision = 'd0f1a2b3c4e5'
branch_labels = None
depends_on = None


def upgrade():
    """Add the column unless the startup schema catch-up already added it."""
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('maintenance_schedules')}
    if 'last_notified_key' not in existing:
        with op.batch_alter_table('maintenance_schedules') as batch:
            batch.add_column(sa.Column('last_notified_key', sa.String(80), nullable=True))


def downgrade():
    with op.batch_alter_table('maintenance_schedules') as batch:
        batch.drop_column('last_notified_key')
