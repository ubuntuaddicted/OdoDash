"""[fork] Trip start/end times and GPS distance (ubuntuaddicted/ododash).

These tests guard the fork's own features. They run with the rest of the suite
on every pull request, including the automated upstream-sync PRs, so a change
pulled in from upstream OdoDash that breaks these fields fails here before it
can be merged.
"""
import importlib.util
from datetime import date, time
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import db
from app.models import Trip


def _create(client, headers, vehicle_id, **extra):
    body = {'date': '2026-01-31', 'start_odometer': 90971, 'purpose': 'business'}
    body.update(extra)
    return client.post(f'/api/v1/vehicles/{vehicle_id}/trips', json=body, headers=headers)


class TestCreateTripForkFields:
    def test_times_and_gps_distance_round_trip(self, client, api_headers, sample_vehicle):
        resp = _create(client, api_headers, sample_vehicle.id,
                       end_odometer=91006.5, start_time='09:37', end_time='12:13:00',
                       gps_distance=35.2)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['start_time'] == '09:37:00'
        assert data['end_time'] == '12:13:00'
        assert data['gps_distance'] == 35.2
        # The odometer stays the record of distance; GPS sits beside it.
        assert data['distance'] == 35.5

        trip = db.session.get(Trip, data['id'])
        assert trip.start_time == time(9, 37)
        assert trip.end_time == time(12, 13)

    def test_fields_are_optional(self, client, api_headers, sample_vehicle):
        resp = _create(client, api_headers, sample_vehicle.id)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['start_time'] is None
        assert data['end_time'] is None
        assert data['gps_distance'] is None

    def test_gps_distance_accepts_string_and_zero(self, client, api_headers, sample_vehicle):
        assert _create(client, api_headers, sample_vehicle.id,
                       gps_distance='12.5').get_json()['gps_distance'] == 12.5
        assert _create(client, api_headers, sample_vehicle.id,
                       gps_distance=0).get_json()['gps_distance'] == 0.0

    @pytest.mark.parametrize('field,value', [
        ('start_time', '25:00'),
        ('start_time', '9am'),
        ('end_time', 930),
        ('gps_distance', -1),
        ('gps_distance', 'far'),
        ('gps_distance', 'nan'),
        ('gps_distance', 'inf'),
        ('gps_distance', True),
    ])
    def test_rejects_bad_values(self, client, api_headers, sample_vehicle, field, value):
        resp = _create(client, api_headers, sample_vehicle.id, **{field: value})
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'
        assert Trip.query.count() == 0


class TestUpdateTripForkFields:
    @pytest.fixture
    def open_trip(self, test_user, sample_vehicle):
        """A trip opened when leaving, before the end reading is known."""
        trip = Trip(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 1, 3), start_odometer=90228.0,
                    purpose='business', start_time=time(8, 33), gps_distance=None)
        db.session.add(trip)
        db.session.commit()
        return trip

    def test_close_trip_with_patch(self, client, api_headers, open_trip):
        resp = client.patch(f'/api/v1/trips/{open_trip.id}', headers=api_headers,
                            json={'end_odometer': 90263.5, 'end_time': '10:23',
                                  'gps_distance': 35.1})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['start_time'] == '08:33:00'  # untouched when not sent
        assert data['end_time'] == '10:23:00'
        assert data['gps_distance'] == 35.1
        assert data['distance'] == 35.5

    def test_null_clears_values(self, client, api_headers, open_trip):
        resp = client.patch(f'/api/v1/trips/{open_trip.id}', headers=api_headers,
                            json={'start_time': None, 'gps_distance': None})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['start_time'] is None
        assert data['gps_distance'] is None

    def test_bad_value_changes_nothing(self, client, api_headers, open_trip):
        resp = client.patch(f'/api/v1/trips/{open_trip.id}', headers=api_headers,
                            json={'purpose': 'personal', 'end_time': 'later'})
        assert resp.status_code == 400
        db.session.expire_all()
        trip = db.session.get(Trip, open_trip.id)
        assert trip.purpose == 'business'
        assert trip.end_time is None

    def test_list_includes_fork_fields(self, client, api_headers, sample_vehicle, open_trip):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/trips', headers=api_headers)
        trip = resp.get_json()['trips'][0]
        assert trip['start_time'] == '08:33:00'
        assert 'gps_distance' in trip and 'end_time' in trip


def test_fork_trip_migration(monkeypatch):
    """Existing trips survive the upgrade, a repeat upgrade, and rollback."""
    path = (Path(__file__).resolve().parents[1]
            / 'migrations/versions/d0f1a2b3c4e5_fork_trip_times_gps_distance.py')
    spec = importlib.util.spec_from_file_location('fork_trip_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text(
            'CREATE TABLE trips (id INTEGER PRIMARY KEY, start_odometer FLOAT NOT NULL, purpose TEXT)'))
        connection.execute(sa.text("INSERT INTO trips VALUES (1, 91293, 'business')"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))

        migration.upgrade()
        cols = {c['name'] for c in sa.inspect(connection).get_columns('trips')}
        assert {'start_time', 'end_time', 'gps_distance'} <= cols
        connection.execute(sa.text('UPDATE trips SET gps_distance = 29.6'))

        migration.upgrade()  # Startup schema catch-up may already have added them.
        assert connection.execute(sa.text('SELECT gps_distance FROM trips')).scalar() == 29.6

        migration.downgrade()
        cols = {c['name'] for c in sa.inspect(connection).get_columns('trips')}
        assert not {'start_time', 'end_time', 'gps_distance'} & cols
        assert connection.execute(sa.text('SELECT start_odometer FROM trips')).scalar() == 91293
