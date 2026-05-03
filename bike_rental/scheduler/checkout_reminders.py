from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime, add_to_date


def send_checkout_reminders():
    """Send checkout reminder notifications for bookings starting in ~2 hours.

    Scheduled job: runs hourly via hooks.py scheduler_events["hourly"].
    Finds Confirmed bookings with start_time within the next 2 hours (±5 min).
    """
    now = now_datetime()
    window_start = add_to_date(now, hours=1, minutes=55, as_datetime=True)
    window_end = add_to_date(now, hours=2, minutes=5, as_datetime=True)

    bookings = frappe.get_all(
        "Rental Booking",
        filters={
            "status": "Confirmed",
            "start_time": ["between", (window_start.time(), window_end.time())],
            "start_date": ["=", now.date()],
            "docstatus": 1,
        },
        fields=["name", "customer", "hub", "bike_model",
                "start_date", "start_time", "end_date", "end_time",
                "customer_name"],
    )

    if not bookings:
        return 0

    from bike_rental.notification.event_handlers import _send_checkout_reminder

    for booking in bookings:
        try:
            _send_checkout_reminder(booking)
        except Exception as e:
            frappe.log_error(
                title="Checkout Reminder Failed",
                message="Booking {0}: {1}".format(booking.name, str(e)),
            )

    return len(bookings)
