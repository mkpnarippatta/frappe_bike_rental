from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist()
def check_out(booking_name, serial_no, current_km=None, battery_level=None):
    """Assign a Bike Serial to a Confirmed booking and begin the rental.

    Validates booking status (must be Confirmed), serial availability
    (must be Available), and model match (serial model == booking model).
    Updates both documents and creates an audit log entry.
    """
    booking = frappe.get_doc("Rental Booking", booking_name)
    serial = frappe.get_doc("Bike Serial", serial_no)

    # Validate booking is in Confirmed state
    if booking.status != "Confirmed":
        frappe.throw(
            _("Booking must be in Confirmed status to check out"),
            frappe.ValidationError,
        )

    # Validate serial is Available
    if serial.status != "Available":
        frappe.throw(
            _("Bike Serial is not available for check-out"),
            frappe.ValidationError,
        )

    # Validate serial matches the booked model
    if serial.bike_model != booking.bike_model:
        frappe.throw(
            _("Selected bike does not match the booked model"),
            frappe.ValidationError,
        )

    # Assign serial to booking via db_set (bypasses before_save hook)
    booking.db_set("bike_serial", serial_no)
    booking.db_set("status", "Active")

    # Update serial condition and status
    serial.db_set("status", "Rented")
    if current_km is not None:
        serial.db_set("current_km", current_km)
    if battery_level is not None:
        serial.db_set("battery_level", battery_level)

    # Create audit log entry
    frappe.get_doc(
        {
            "doctype": "Notification Log",
            "subject": _("Check-Out: {0} assigned to {1}").format(
                serial_no, booking_name
            ),
            "type": "Alert",
            "document_type": "Rental Booking",
            "document_name": booking_name,
        }
    ).insert(ignore_permissions=True)

    return {
        "status": "success",
        "booking_name": booking_name,
        "serial": serial_no,
        "booking_status": "Active",
        "serial_status": "Rented",
    }
