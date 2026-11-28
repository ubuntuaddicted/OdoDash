"""[fork] Notify when a maintenance schedule is coming due, by date or by reading.

Upstream OdoDash stores ``auto_remind`` and ``remind_days_before`` on each
maintenance schedule but nothing acts on them: only Reminders (date-only)
ever send a notification. This runs from the same hourly scheduler and sends
one notification per due point, through the user's chosen method, when:

* the next due date is within ``remind_days_before`` days (or past), or
* the next due reading is close: within the distance the vehicle usually
  covers in ``remind_days_before`` days, judged from recent odometer
  readings, and never less than ``MIN_DISTANCE_WARNING``.

A due point is announced once. Marking the schedule complete moves the due
point, so the next one is announced in turn.
"""
import logging
from datetime import date, timedelta

from app import db
from app.models import MaintenanceSchedule, User
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)

#: Warn at least this far ahead of a due reading, whatever the driving rate.
MIN_DISTANCE_WARNING = 250
#: How far back to look when working out how much the vehicle is driven.
RATE_WINDOW_DAYS = 90
#: The readings must span at least this many days to give a usable rate.
RATE_MIN_SPAN_DAYS = 7


def usage_per_day(vehicle, today, window_days=RATE_WINDOW_DAYS):
    """Average reading change per day over the recent window, or ``None``.

    Uses every logged reading (fuel, trips, charging, expenses). Returns
    ``None`` when there are too few readings, or they span too short a time,
    to say anything useful.
    """
    since = today - timedelta(days=window_days)
    recent = [(day, value) for day, value in vehicle.get_odometer_readings() if day and day >= since]
    if len(recent) < 2:
        return None
    (first_day, first), (last_day, last) = recent[0], recent[-1]
    span = (last_day - first_day).days
    if span < RATE_MIN_SPAN_DAYS or last <= first:
        return None
    return (last - first) / span


def due_reasons(schedule, today, current_reading, per_day):
    """Why ``schedule`` should be announced now, as a list of short phrases."""
    reasons = []
    lead_days = schedule.remind_days_before if schedule.remind_days_before is not None else 14
    unit = schedule.vehicle.get_reading_unit() if schedule.vehicle else ''

    if schedule.next_due_date:
        days_left = (schedule.next_due_date - today).days
        if days_left < 0:
            reasons.append(f"{abs(days_left)} days overdue (was due {schedule.next_due_date:%B %d, %Y})")
        elif days_left <= lead_days:
            reasons.append(f"due {'today' if days_left == 0 else f'in {days_left} days'} "
                           f"({schedule.next_due_date:%B %d, %Y})")

    if schedule.next_due_odometer is not None and current_reading is not None:
        left = schedule.next_due_odometer - current_reading
        threshold = max(MIN_DISTANCE_WARNING, (per_day or 0) * lead_days)
        if left <= 0:
            reasons.append(f"{abs(left):,.0f} {unit} past due (was due at {schedule.next_due_odometer:,.0f} {unit})")
        elif left <= threshold:
            phrase = f"due in about {left:,.0f} {unit} (at {schedule.next_due_odometer:,.0f} {unit})"
            if per_day:
                phrase += f", roughly {max(1, round(left / per_day))} days at your recent driving"
            reasons.append(phrase)
    return reasons


def due_key(schedule):
    """Identifies one due point, so it is announced only once."""
    return f"{schedule.next_due_date or ''}|{schedule.next_due_odometer if schedule.next_due_odometer is not None else ''}"


def process_due_maintenance(today=None):
    """Send a notification for every schedule that has come due. Returns counts."""
    today = today or date.today()
    stats = {'checked': 0, 'sent': 0, 'failed': 0, 'skipped': 0, 'errors': []}
    rates = {}

    schedules = MaintenanceSchedule.query.filter(
        MaintenanceSchedule.is_active.isnot(False),
        MaintenanceSchedule.auto_remind.isnot(False),
    ).all()

    for schedule in schedules:
        stats['checked'] += 1
        vehicle = schedule.vehicle
        user = db.session.get(User, schedule.user_id)
        if (not vehicle or vehicle.is_active is False or not user
                or not user.email_reminders or user.notification_method == 'none'):
            stats['skipped'] += 1
            continue

        key = due_key(schedule)
        if key == '|' or schedule.last_notified_key == key:
            stats['skipped'] += 1
            continue

        if vehicle.id not in rates:
            rates[vehicle.id] = usage_per_day(vehicle, today)
        current = vehicle.get_last_odometer() or None
        reasons = due_reasons(schedule, today, current, rates[vehicle.id])
        if not reasons:
            stats['skipped'] += 1
            continue

        title = f"Maintenance due: {schedule.name} ({vehicle.name})"
        message = f"Vehicle: {vehicle.name}\nMaintenance: {schedule.name}\n"
        message += "".join(f"- {reason}\n" for reason in reasons)
        if current is not None:
            message += f"Current reading: {current:,.0f} {vehicle.get_reading_unit()}\n"
        if schedule.description:
            message += f"Details: {schedule.description}\n"
        message += "Mark it complete in OdoDash once done to schedule the next one."

        try:
            success, error = NotificationService.send_notification(user, title, message)
        except Exception as exc:  # a broken channel must not stop the loop
            success, error = False, str(exc)
        if success:
            schedule.last_notified_key = key
            db.session.commit()
            stats['sent'] += 1
            logger.info("Sent maintenance notification for schedule #%s to %s", schedule.id, user.username)
        else:
            stats['failed'] += 1
            stats['errors'].append(f"Schedule #{schedule.id}: {error}")
            logger.warning("Maintenance notification for schedule #%s failed: %s", schedule.id, error)
    return stats
