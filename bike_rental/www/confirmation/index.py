from __future__ import unicode_literals

import frappe
from frappe import _


def get_context(context):
    """Confirmation page context."""
    context.title = _("Booking Confirmed - Bike Rental")

    booking_name = frappe.form_dict.get("booking")
    payment_entry = frappe.form_dict.get("amount")

    if booking_name:
        booking = frappe.get_all(
            "Rental Booking",
            filters={"name": booking_name},
            fields=["name", "bike_model", "customer_name", "pickup_hub",
                    "pickup_datetime", "return_datetime", "total_amount",
                    "status", "payment_entry"],
            limit=1,
        )
        context.booking = booking[0] if booking else None
    else:
        context.booking = None

    context.payment_entry = payment_entry

    return context
