from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime, add_to_date


def send_return_reminders():
    """Send check-in reminder notifications for rentals ending in ~4 hours.

    Scheduled job: runs hourly via hooks.py scheduler_events["hourly"].
    Notifies staff of upcoming returns for back-to-back rental preparation.
    """
    now = now_datetime()
    window_start = add_to_date(now, hours=3, minutes=55, as_datetime=True)
    window_end = add_to_date(now, hours=4, minutes=5, as_datetime=True)

    bookings = frappe.get_all(
        "Rental Booking",
        filters={
            "status": ["in", ["Checked Out", "Confirmed"]],
            "end_time": ["between", (window_start.time(), window_end.time())],
            "end_date": ["=", now.date()],
            "docstatus": 1,
        },
        fields=["name", "customer", "hub", "bike_model",
                "start_date", "start_time", "end_date", "end_time",
                "customer_name"],
    )

    if not bookings:
        return 0

    from bike_rental.notification.event_handlers import _send_return_reminder

    for booking in bookings:
        try:
            _send_return_reminder(booking)
        except Exception as e:
            frappe.log_error(
                title="Return Reminder Failed",
                message="Booking {0}: {1}".format(booking.name, str(e)),
            )

    return len(bookings)
