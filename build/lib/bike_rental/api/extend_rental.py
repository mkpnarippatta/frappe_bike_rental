from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from bike_rental.pricing.calculate import get_effective_rate, compute_base_rental


@frappe.whitelist()
def extend_rental(booking_name, new_return_datetime):
    """Extend an Active rental booking to a later return time.

    Checks availability for the extension period, calculates additional
    charges at the current effective rate, and updates the booking.

    Args:
        booking_name: Rental Booking name.
        new_return_datetime: New return datetime (ISO format).

    Returns:
        dict with status, new_return_datetime, additional_charge, total_amount.
    """
    booking = frappe.get_doc("Rental Booking", booking_name)

    if booking.status != "Active":
        frappe.throw(
            _("Only Active bookings can be extended"),
            frappe.ValidationError,
        )

    new_return = get_datetime(new_return_datetime)
    current_return = get_datetime(booking.return_datetime)

    if new_return <= current_return:
        frappe.throw(
            _("New return time must be later than the current return time"),
            frappe.ValidationError,
        )

    # Lock the booking row to prevent concurrent extension races
    frappe.db.sql(
        "SELECT return_datetime FROM `tabRental Booking` WHERE name=%s FOR UPDATE",
        booking_name,
    )

    # Check availability for the extension period (exclude self)
    overlapping = frappe.db.count(
        "Rental Booking",
        filters={
            "bike_model": booking.bike_model,
            "pickup_hub": booking.pickup_hub,
            "name": ("!=", booking_name),
            "status": ["in", ["Confirmed", "Active"]],
            "pickup_datetime": ["<", new_return],
            "return_datetime": [">", current_return],
        },
    )

    total_capacity = frappe.db.count(
        "Bike Serial",
        filters={
            "bike_model": booking.bike_model,
            "hub": booking.pickup_hub,
            "status": ["not in", ["Scrapped", "In Transit"]],
        },
    )

    safety_margin = (
        frappe.db.get_value("Bike Model", booking.bike_model, "safety_margin") or 0
    )
    available = max(0, total_capacity - overlapping - safety_margin)

    if available < 1:
        frappe.throw(
            _("Sorry, the bike model is not available for the requested extension period"),
            frappe.ValidationError,
        )

    # Calculate additional charge at current effective rate
    bike_model = frappe.get_doc("Bike Model", booking.bike_model)
    effective_hourly, effective_daily = get_effective_rate(
        bike_model, booking.pickup_datetime, new_return
    )

    original_rental = compute_base_rental(
        effective_hourly, effective_daily,
        booking.pickup_datetime, current_return,
    )
    extended_rental = compute_base_rental(
        effective_hourly, effective_daily,
        booking.pickup_datetime, new_return,
    )
    additional_charge = round(extended_rental - original_rental, 2)

    # Wrap writes in savepoint for atomicity
    frappe.db.savepoint("before_extend")
    try:
        # Verify the booking is still Active under lock
        current_status = frappe.db.get_value("Rental Booking", booking_name, "status")
        if current_status != "Active":
            frappe.throw(
                _("Booking status changed to {0} before extension could be applied").format(current_status),
                frappe.ValidationError,
            )

        booking.db_set("return_datetime", new_return, update_modified=False)
        booking.db_set("total_amount", extended_rental, update_modified=False)

        # Send extension notification via notification engine
        try:
            from bike_rental.notification.event_handlers import on_booking_extended
            booking_doc = frappe.get_doc("Rental Booking", booking_name)
            on_booking_extended(booking_doc, new_return, additional_charge)
        except Exception as e:
            frappe.log_error(
                title="Extension Notification Failed",
                message="Booking {0}: {1}".format(booking_name, str(e)),
            )

        # Log notification
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": _("Booking {0} extended to {1}. Additional charge: {2}").format(
                    booking_name, new_return, additional_charge
                ),
                "type": "Alert",
                "document_type": "Rental Booking",
                "document_name": booking_name,
            }
        ).insert(ignore_permissions=True)
    except Exception:
        frappe.db.rollback(save_point="before_extend")
        raise

    return {
        "status": "success",
        "booking_name": booking_name,
        "new_return_datetime": str(new_return),
        "additional_charge": additional_charge,
        "total_amount": extended_rental,
    }
