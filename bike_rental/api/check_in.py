from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import now_datetime

from bike_rental.pricing.calculate import calculate_charges


@frappe.whitelist()
def check_in(booking_name, end_km, end_battery=None, damage_notes=None, damage_amount=0, end_datetime=None):
    """Complete a rental: record return condition, calculate charges, generate invoice.

    Validates booking is Active, calculates charges via the pricing engine,
    generates a Sales Invoice, updates serial to Available and booking to Completed.
    """
    booking = frappe.get_doc("Rental Booking", booking_name)

    # Ensure numeric types
    end_km = frappe.utils.flt(end_km)
    damage_amount = frappe.utils.flt(damage_amount)

    # Validate booking is Active
    if booking.status != "Active":
        frappe.throw(
            _("Booking must be in Active status to check in"),
            frappe.ValidationError,
        )

    if not booking.bike_serial:
        frappe.throw(
            _("No bike serial assigned to this booking"),
            frappe.ValidationError,
        )

    serial = frappe.get_doc("Bike Serial", booking.bike_serial)

    # Validate serial is actually rented
    if serial.status != "Rented":
        frappe.throw(
            _("Bike Serial must be in Rented status to check in"),
            frappe.ValidationError,
        )

    # Validate end_km >= start_km
    if end_km < serial.current_km:
        frappe.throw(
            _("End KM reading ({0}) cannot be less than starting KM ({1})").format(
                end_km, serial.current_km
            ),
            frappe.ValidationError,
        )

    if not booking.total_amount:
        frappe.throw(
            _("Booking has no total_amount. Cannot calculate charges."),
            frappe.ValidationError,
        )

    if end_datetime is None:
        end_datetime = now_datetime()

    # Use savepoint for atomicity
    frappe.db.savepoint("before_check_in")

    try:
        # Verify accounting module is available before making any changes
        if not frappe.db.exists("DocType", "Company"):
            frappe.throw(
                _("Accounting module not installed. Cannot generate Sales Invoice. "
                  "Please install ERPNext or contact your system administrator."),
                frappe.ValidationError,
            )

        company = _get_company()
        if not company:
            frappe.throw(
                _("No Company set up. Please create a Company in Accounting > Company first."),
                frappe.ValidationError,
            )

        # Calculate charges via pricing engine
        charges = calculate_charges(booking, end_km, end_datetime, damage_amount)

        # Store check-in data on booking
        booking.db_set("end_km", end_km)
        if end_battery is not None:
            booking.db_set("end_battery_level", end_battery)
        if damage_notes:
            booking.db_set("damage_notes", damage_notes)

        booking.db_set("excess_km_charges", charges["excess_km_charges"])
        booking.db_set("late_return_fees", charges["late_return_fee"])
        booking.db_set("damage_charges", charges["damage_charges"])

        # Generate Sales Invoice
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": booking.customer,
                "company": company,
                "posting_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": "Rental Service",
                        "item_name": line["description"],
                        "qty": 1,
                        "rate": line["amount"],
                        "amount": line["amount"],
                    }
                    for line in charges["line_items"]
                ],
                "total": charges["total"],
                "outstanding_amount": charges["total"],
            }
        )
        invoice.insert(ignore_permissions=True)
        invoice.submit()

        # Link invoice to booking
        booking.db_set("invoice_ref", invoice.name)

        # Update serial: Available, current_km updated to end_km
        serial.db_set("status", "Available")
        serial.db_set("current_km", end_km)

        # Update booking to Completed with optimistic lock
        rows_affected = frappe.db.set_value(
            "Rental Booking",
            booking_name,
            "status",
            "Completed",
            update_modified=True,
        )
        if not rows_affected:
            frappe.throw(
                _("Booking could not be completed (concurrent update detected)."),
                frappe.ValidationError,
            )

        booking.db_set("deposit_released", 1)

        # Log completion info
        deposit_note = _("Check-In completed. Total charges: {0}. Invoice: {1}.").format(
            charges["total"], invoice.name
        )
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": deposit_note,
                "type": "Alert",
                "document_type": "Rental Booking",
                "document_name": booking_name,
            }
        ).insert(ignore_permissions=True)

    except Exception:
        frappe.db.rollback(save_point="before_check_in")
        raise

    return {
        "status": "success",
        "booking_name": booking_name,
        "booking_status": "Completed",
        "serial_status": "Available",
        "invoice": invoice.name,
        "charges": charges,
    }


def _get_company():
    """Get company for invoice. Falls back to first available Company doctype."""
    company = frappe.defaults.get_user_default("Company")
    if company:
        return company
    try:
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if company:
            return company
    except Exception:
        pass
    companies = frappe.get_all("Company", limit=1)
    if companies:
        return companies[0].name
    return None
