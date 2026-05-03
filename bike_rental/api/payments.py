from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist()
def create_cash_payment(booking_name, amount):
    """Create a cash Payment Entry for a Rental Booking and confirm it.

    Creates a Payment Entry (Receive, Customer party, linked to the Rental
    Booking via the references child table), links it to the booking, and
    submits the booking to move it from Draft to Confirmed.
    """
    booking = frappe.get_doc("Rental Booking", booking_name)

    company = (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )

    pe = frappe.get_doc(
        {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": booking.customer,
            "paid_amount": amount,
            "received_amount": amount,
            "reference_no": booking_name,
            "reference_date": frappe.utils.nowdate(),
            "company": company,
            "references": [
                {
                    "reference_doctype": "Rental Booking",
                    "reference_name": booking_name,
                    "allocated_amount": amount,
                }
            ],
        }
    )
    pe.insert()
    pe.submit()

    # Link to booking and submit it
    booking.db_set("payment_entry", pe.name)
    booking.reload()  # Sync in-memory doc after db_set
    booking.submit()

    # Send payment receipt notification
    try:
        from bike_rental.notification.event_handlers import on_payment_receipt
        booking.reload()
        on_payment_receipt(booking, amount, "Cash")
    except Exception as e:
        frappe.log_error(
            title="Payment Receipt Notification Failed",
            message="Booking {0}: {1}".format(booking_name, str(e)),
        )

    return {"payment_entry": pe.name, "status": "Confirmed"}
