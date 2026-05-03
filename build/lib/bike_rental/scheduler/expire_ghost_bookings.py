import frappe
from frappe.utils import now_datetime


def expire_ghost_bookings():
    """Mark Confirmed bookings as Expired if not checked out within 2 hours of start time.

    Runs via scheduler_events["all"] (approx every 3 minutes).
    Only queries Confirmed bookings past the 2-hour window (NFR-06).
    Uses conditional UPDATE for idempotency — never re-processes already-Expired bookings.
    Errors are logged via frappe.log_error and retry on next cycle.
    """
    try:
        cutoff = now_datetime()
        two_hours_ago = frappe.utils.add_to_date(cutoff, hours=-2)

        bookings = frappe.get_all(
            "Rental Booking",
            filters=[
                ["Rental Booking", "status", "=", "Confirmed"],
                ["Rental Booking", "pickup_datetime", "<", two_hours_ago],
            ],
            fields=["name"],
        )

        expired_count = 0
        for booking in bookings:
            rows = frappe.db.sql(
                """UPDATE `tabRental Booking`
                   SET `status` = 'Expired', `modified` = %s
                   WHERE `name` = %s AND `status` = 'Confirmed'""",
                (cutoff, booking.name),
            )
            if rows:
                expired_count += 1

        if expired_count:
            frappe.logger("scheduler").info(
                f"{expired_count} booking(s) expired due to no-show."
            )

    except Exception:
        frappe.log_error(
            title="Ghost Booking Expiry Error",
            message="Failed to expire ghost bookings",
        )
