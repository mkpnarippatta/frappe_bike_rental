from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime, add_to_date

BUSINESS_HOUR_START = 7   # 7 AM
BUSINESS_HOUR_END = 22    # 10 PM

# Event types that bypass business hours and send immediately
CRITICAL_EVENTS = {"KYC Status Change", "Payment Receipt"}


def is_business_hour(dt=None):
    """Check if dt falls within business hours (7 AM – 10 PM)."""
    if dt is None:
        dt = now_datetime()
    return BUSINESS_HOUR_START <= dt.hour < BUSINESS_HOUR_END


def next_business_hour_datetime(dt=None):
    """Return the next datetime when business hours start.

    If dt is during business hours, returns dt unchanged.
    If dt is outside business hours, returns 7 AM of the same day (or next day
    if dt is after midnight but before 7 AM).
    """
    if dt is None:
        dt = now_datetime()

    if is_business_hour(dt):
        return dt

    if dt.hour < BUSINESS_HOUR_START:
        # Before 7 AM today — return 7 AM today
        return dt.replace(hour=BUSINESS_HOUR_START, minute=0, second=0, microsecond=0)
    else:
        # After 10 PM — return 7 AM tomorrow
        tomorrow = add_to_date(dt, days=1)
        return tomorrow.replace(hour=BUSINESS_HOUR_START, minute=0, second=0, microsecond=0)


def is_critical_event(event_type):
    """Check if an event type is critical and should bypass business hours."""
    return event_type in CRITICAL_EVENTS


def enqueue_with_business_hours(event_type, recipient, channel, variables=None,
                                priority="Normal", reference_doctype=None,
                                reference_docname=None, hub=None):
    """Enqueue a notification, respecting business hours for non-critical events.

    Critical events (KYC Status Change, Payment Receipt) are enqueued immediately
    regardless of time. Non-critical events outside business hours get their
    next_retry_at set to the next business hour.
    """
    from bike_rental.notification.queue import enqueue_notification

    now = now_datetime()

    if is_critical_event(event_type) or is_business_hour(now):
        return enqueue_notification(
            recipient, channel,
            template=event_type.lower().replace(" ", "_"),
            variables=variables,
            priority=priority,
            reference_doctype=reference_doctype,
            reference_docname=reference_docname,
            hub=hub,
        )

    # Non-critical outside business hours — queue for next business hour
    name = enqueue_notification(
        recipient, channel,
        template=event_type.lower().replace(" ", "_"),
        variables=variables,
        priority=priority,
        reference_doctype=reference_doctype,
        reference_docname=reference_docname,
        hub=hub,
    )

    next_bh = next_business_hour_datetime(now)
    frappe.db.set_value("Notification Queue", name, "next_retry_at", next_bh)
    return name
