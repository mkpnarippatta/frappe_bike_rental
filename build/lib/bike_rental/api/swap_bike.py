from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist()
def swap_bike(booking_name, new_serial_no, end_km, end_battery=None, damage_notes=None, swap_reason=None):
    """Swap the bike assigned to an Active rental booking.

    Checks in the current bike (records return condition, updates serial to Available
    with current_km), assigns a new serial to the same booking, and continues the
    rental uninterrupted. Billing happens at the final check-in.

    Validates:
    - Booking is Active
    - New serial is Available and matches the booked model
    - End KM is not less than current bike's starting KM
    """
    booking = frappe.get_doc("Rental Booking", booking_name)

    if booking.status != "Active":
        frappe.throw(
            _("Booking must be Active to swap bike"),
            frappe.ValidationError,
        )

    if not booking.bike_serial:
        frappe.throw(
            _("No bike serial assigned to this booking"),
            frappe.ValidationError,
        )

    # Validate current serial is Rented
    current_serial = frappe.get_doc("Bike Serial", booking.bike_serial)
    if current_serial.status != "Rented":
        frappe.throw(
            _("Current bike serial is not in Rented status"),
            frappe.ValidationError,
        )

    # Validate end_km >= current_km
    if end_km < current_serial.current_km:
        frappe.throw(
            _("End KM ({0}) cannot be less than starting KM ({1})").format(
                end_km, current_serial.current_km
            ),
            frappe.ValidationError,
        )

    # Validate new serial exists
    new_serial = frappe.get_doc("Bike Serial", new_serial_no)
    if new_serial.status != "Available":
        frappe.throw(
            _("New bike serial ({0}) is not Available (status: {1})").format(
                new_serial_no, new_serial.status
            ),
            frappe.ValidationError,
        )

    # Validate model match
    if new_serial.bike_model != booking.bike_model:
        frappe.throw(
            _("New bike model ({0}) does not match the booked model ({1})").format(
                new_serial.bike_model, booking.bike_model
            ),
            frappe.ValidationError,
        )

    # Check if new serial is same as current
    if new_serial_no == booking.bike_serial:
        frappe.throw(
            _("New bike serial is the same as the current serial"),
            frappe.ValidationError,
        )

    # --- Perform the swap ---
    frappe.db.savepoint("before_swap")

    try:
        # Record current bike return on booking
        booking.db_set("end_km", end_km)
        if end_battery is not None:
            booking.db_set("end_battery_level", end_battery)
        if damage_notes:
            booking.db_set("damage_notes", damage_notes)

        # Release current serial
        current_serial.db_set("status", "Available")
        current_serial.db_set("current_km", end_km)

        # Assign new serial to booking
        booking.db_set("bike_serial", new_serial_no)

        # Reset check-in fields for the new bike
        booking.db_set("end_km", 0)
        booking.db_set("end_battery_level", None)
        booking.db_set("damage_notes", None)

        # Mark new serial as Rented
        new_serial.db_set("status", "Rented")

        # Store swap reason on the booking
        if swap_reason:
            booking.db_set("swap_reason", swap_reason)

        # Log the swap
        reason_text = swap_reason or "not specified"
        swap_note = _("Bike swap: {0} (end KM: {1}) replaced by {2}. Reason: {3}").format(
            current_serial.name, end_km, new_serial_no, reason_text
        )
        frappe.get_doc({
            "doctype": "Notification Log",
            "subject": swap_note,
            "type": "Alert",
            "document_type": "Rental Booking",
            "document_name": booking_name,
        }).insert(ignore_permissions=True)

    except Exception:
        frappe.db.rollback(save_point="before_swap")
        raise

    return {
        "status": "success",
        "booking_name": booking_name,
        "booking_status": "Active",
        "previous_serial": current_serial.name,
        "new_serial": new_serial_no,
        "previous_serial_status": "Available",
        "new_serial_status": "Rented",
        "swap_reason": swap_reason,
    }
