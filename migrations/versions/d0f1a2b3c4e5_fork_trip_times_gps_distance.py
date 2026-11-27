"""[fork] Add start/end times and GPS distance to trips.

Part of the ubuntuaddicted/ododash fork, not upstream OdoDash. If an upstream
migration is later added on top of a7c9e2f4b610 as well, Alembic will report
two heads; join them with ``flask db merge heads`` rather than editing either.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd0f1a2b3c4e5'
down_revision = 'a7c9e2f4b610'
branch_labels = None
depends_on = None

_COLUMNS = (
    ('start_time', sa.Time()),
    ('end_time', sa.Time()),
    ('gps_distance', sa.Float()),
)


def upgrade():
    """Add each column unless the startup schema catch-up already added it."""
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('trips')}
    missing = [(name, type_) for name, type_ in _COLUMNS if name not in existing]
    if missing:
        with op.batch_alter_table('trips') as batch:
            for name, type_ in missing:
                batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade():
    """Drop the fork's trip columns; upstream trip data is untouched."""
    with op.batch_alter_table('trips') as batch:
        for name, _ in reversed(_COLUMNS):
            batch.drop_column(name)
