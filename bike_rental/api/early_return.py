import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from bike_rental.pricing.calculate import calculate_charges


@frappe.whitelist()
def process_early_return(booking_name, end_km, end_battery=None, damage_notes=None, damage_amount=0, end_datetime=None):
    """Process an early return with pro-rata adjustment.

    Early return >4h before scheduled end = pro-rata refund on base rental.
    Early return <4h before scheduled end = no refund (standard buffer per FR-21).

    Delegates to check_in flow but adjusts base rental to actual usage duration.
    """
    booking = frappe.get_doc("Rental Booking", booking_name)

    if booking.status != "Active":
        frappe.throw(
            _("Booking must be Active to process return"),
            frappe.ValidationError,
        )

    if not booking.bike_serial:
        frappe.throw(
            _("No bike serial assigned to this booking"),
            frappe.ValidationError,
        )

    serial = frappe.get_doc("Bike Serial", booking.bike_serial)
    if serial.status != "Rented":
        frappe.throw(
            _("Bike Serial is not in Rented status"),
            frappe.ValidationError,
        )

    if end_km < serial.current_km:
        frappe.throw(
            _("End KM ({0}) cannot be less than starting KM ({1})").format(end_km, serial.current_km),
            frappe.ValidationError,
        )

    if end_datetime is None:
        end_datetime = now_datetime()

    actual_end = get_datetime(end_datetime)
    scheduled_end = get_datetime(booking.return_datetime)
    hours_early = (scheduled_end - actual_end).total_seconds() / 3600

    # Calculate charges normally first
    charges = calculate_charges(booking, end_km, end_datetime, damage_amount)

    # Determine early return adjustment
    early_refund = 0
    if hours_early > 4:
        # Pro-rata refund: recalculate base rental for actual duration
        pickup = get_datetime(booking.pickup_datetime)
        actual_hours = (actual_end - pickup).total_seconds() / 3600
        scheduled_hours = (scheduled_end - pickup).total_seconds() / 3600
        if scheduled_hours > 0:
            # Base rental recalculated: total_amount * (actual_hours / scheduled_hours)
            adjusted_base = round((booking.total_amount or 0) * actual_hours / scheduled_hours, 2)
            early_refund = round((booking.total_amount or 0) - adjusted_base, 2)
            charges["base_rental"] = adjusted_base
            charges["total"] = round(adjusted_base + charges["excess_km_charges"] + charges["late_return_fee"] + (damage_amount or 0), 2)

    # Create Sales Invoice with adjusted charges
    frappe.db.savepoint("before_early_return")
    try:
        company = (
            frappe.defaults.get_user_default("Company")
            or frappe.db.get_single_value("Global Defaults", "default_company")
        )

        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": booking.customer,
            "company": company,
            "posting_date": frappe.utils.nowdate(),
            "items": [
                {"item_code": "Rental Service", "item_name": line["description"], "qty": 1, "rate": line["amount"], "amount": line["amount"]}
                for line in charges["line_items"]
            ],
            "total": charges["total"],
            "outstanding_amount": charges["total"],
        })
        invoice.insert(ignore_permissions=True)
        invoice.submit()

        booking.db_set("end_km", end_km)
        if end_battery is not None:
            booking.db_set("end_battery_level", end_battery)
        if damage_notes:
            booking.db_set("damage_notes", damage_notes)
        booking.db_set("invoice_ref", invoice.name)
        booking.db_set("excess_km_charges", charges["excess_km_charges"])
        booking.db_set("late_return_fees", charges["late_return_fee"])
        booking.db_set("damage_charges", charges["damage_charges"])
        booking.db_set("deposit_released", 1)

        serial.db_set("status", "Available")
        serial.db_set("current_km", end_km)

        rows = frappe.db.set_value("Rental Booking", booking_name, "status", "Completed", update_modified=True)
        if not rows:
            frappe.throw(_("Booking could not be completed (concurrent update)."), frappe.ValidationError)

        reason = _("Early return. Hours early: {0}. Refund: {1}").format(hours_early, early_refund)
        frappe.get_doc({
            "doctype": "Notification Log",
            "subject": reason,
            "type": "Alert",
            "document_type": "Rental Booking",
            "document_name": booking_name,
        }).insert(ignore_permissions=True)

    except Exception:
        frappe.db.rollback(save_point="before_early_return")
        raise

    return {
        "status": "success",
        "booking_name": booking_name,
        "booking_status": "Completed",
        "serial_status": "Available",
        "invoice": invoice.name,
        "charges": charges,
        "early_refund": early_refund,
        "hours_early": hours_early,
    }
