from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime, get_datetime


def send_overdue_notifications():
    """Notify staff when an Active booking's return time is past due by more than 1 hour.

    Runs hourly via scheduler_events["hourly"].
    """
    now = now_datetime()
    overdue_bookings = frappe.get_all(
        "Rental Booking",
        filters={
            "status": "Active",
            "end_date": ("<", now),
        },
        fields=["name", "customer", "end_date"],
    )

    for booking in overdue_bookings:
        # Coerce to datetime in case end_date is a Date field
        end = get_datetime(booking.end_date)
        overdue_hours = (now - end).total_seconds() / 3600
        if overdue_hours > 1:
            _notify_staff(booking.name, booking.customer, overdue_hours)


def _notify_staff(booking_name, customer, overdue_hours):
    """Create a ToDo alert for Hub Manager about an overdue booking."""
    description = (
        f"Booking {booking_name} is overdue by {overdue_hours:.1f} hours. "
        f"Customer: {customer}"
    )

    managers = frappe.get_all(
        "User",
        filters=[["name", "in", frappe.get_roles("Hub Manager")]],
        pluck="name",
    )
    for manager in managers:
        todo = frappe.get_doc({"doctype": "ToDo", "description": description, "allocated_to": manager})
        todo.insert(ignore_permissions=True)

    frappe.log_error(title="Overdue Booking", message=description)
