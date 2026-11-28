"""[fork] Maintenance schedules notify by date and by reading."""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import db
from app.models import Expense, MaintenanceSchedule, Trip, Vehicle
from app.services import maintenance_notifier as mn

TODAY = date(2027, 4, 20)


@pytest.fixture
def car(app, test_user):
    test_user.email_reminders = True
    test_user.notification_method = 'ntfy'
    vehicle = Vehicle(owner_id=test_user.id, name='Corolla', vehicle_type='car',
                      fuel_type='petrol', odometer_unit='mi', starting_odometer=99000)
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


def _drive(vehicle, user, start_day, start, end):
    db.session.add(Trip(vehicle_id=vehicle.id, user_id=user.id, date=start_day,
                        start_odometer=start, end_odometer=end, purpose='personal'))
    db.session.commit()


def _schedule(vehicle, user, **kw):
    s = MaintenanceSchedule(vehicle_id=vehicle.id, user_id=user.id, name=kw.pop('name', 'Oil'),
                            maintenance_type='oil_change', remind_days_before=14, **kw)
    s.calculate_next_due()
    db.session.add(s)
    db.session.commit()
    return s


def _run(today=TODAY):
    with patch.object(mn.NotificationService, 'send_notification', return_value=(True, None)) as send:
        stats = mn.process_due_maintenance(today=today)
    return stats, send


def test_date_due_soon_notifies_once(car, test_user):
    _schedule(car, test_user, interval_months=6, last_performed_date=date(2026, 11, 1))  # due 2027-05-01
    stats, send = _run()
    assert stats['sent'] == 1
    assert 'due in 11 days' in send.call_args[0][2]
    stats, send = _run()
    assert stats['sent'] == 0 and not send.called


def test_date_far_off_is_quiet(car, test_user):
    _schedule(car, test_user, interval_months=12, last_performed_date=date(2026, 11, 1))
    stats, send = _run()
    assert stats['sent'] == 0 and not send.called


def test_reading_close_at_recent_driving_rate(car, test_user):
    # 30 mi/day over 60 days: 14 days of driving is 420 mi.
    _drive(car, test_user, TODAY - timedelta(days=60), 100000, 100000)
    _drive(car, test_user, TODAY, 101500, 101800)
    _schedule(car, test_user, interval_miles=5000, last_performed_odometer=97100)  # due 102100
    stats, send = _run()
    assert stats['sent'] == 1
    body = send.call_args[0][2]
    assert 'due in about 300 mi' in body and 'roughly 10 days' in body


def test_reading_far_off_is_quiet(car, test_user):
    _drive(car, test_user, TODAY - timedelta(days=60), 100000, 100000)
    _drive(car, test_user, TODAY, 100500, 100600)
    _schedule(car, test_user, interval_miles=10000, last_performed_odometer=98918)  # due 108918
    stats, send = _run()
    assert stats['sent'] == 0


def test_without_a_rate_the_minimum_warning_applies(car, test_user):
    db.session.add(Expense(vehicle_id=car.id, user_id=test_user.id, date=TODAY, category='other', description='Car wash',
                           cost=1, odometer=102900))
    db.session.commit()
    _schedule(car, test_user, interval_miles=5000, last_performed_odometer=98000)  # due 103000
    stats, send = _run()
    assert stats['sent'] == 1 and 'about 100 mi' in send.call_args[0][2]


def test_overdue_reading_is_reported(car, test_user):
    _drive(car, test_user, TODAY, 103000, 103200)
    _schedule(car, test_user, interval_miles=5000, last_performed_odometer=98000)
    stats, send = _run()
    assert '200 mi past due' in send.call_args[0][2]


def test_completing_moves_the_due_point_and_notifies_again(car, test_user):
    s = _schedule(car, test_user, interval_months=6, last_performed_date=date(2026, 11, 1))
    assert _run()[0]['sent'] == 1
    s.last_performed_date = date(2027, 4, 25)
    s.calculate_next_due()
    db.session.commit()
    assert _run(date(2027, 10, 15))[0]['sent'] == 1


@pytest.mark.parametrize('setup', ['auto_remind_off', 'notifications_off', 'method_none', 'inactive'])
def test_opted_out_is_skipped(car, test_user, setup):
    s = _schedule(car, test_user, interval_months=6, last_performed_date=date(2026, 11, 1))
    if setup == 'auto_remind_off':
        s.auto_remind = False
    elif setup == 'notifications_off':
        test_user.email_reminders = False
    elif setup == 'method_none':
        test_user.notification_method = 'none'
    else:
        s.is_active = False
    db.session.commit()
    stats, send = _run()
    assert stats['sent'] == 0 and not send.called


def test_failed_send_is_retried_next_time(car, test_user):
    _schedule(car, test_user, interval_months=6, last_performed_date=date(2026, 11, 1))
    with patch.object(mn.NotificationService, 'send_notification', return_value=(False, 'down')):
        assert mn.process_due_maintenance(today=TODAY)['failed'] == 1
    assert _run()[0]['sent'] == 1


def test_zero_reading_counts_as_last_performed(car, test_user):
    s = _schedule(car, test_user, name='Spark plugs', interval_miles=120000, last_performed_odometer=0)
    assert s.next_due_odometer == 120000
