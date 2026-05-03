from __future__ import unicode_literals

import frappe
from frappe import _


def get_context(context):
    """Booking detail page context."""
    booking_name = frappe.form_dict.get("name")

    # Customer authorization: non-staff users can only view their own bookings
    if frappe.session.user != "Guest":
        roles = frappe.get_roles()
        is_staff = "System Manager" in roles or "Hub Manager" in roles or "Hub Staff" in roles
        if not is_staff:
            user_email = frappe.session.user
            customer = frappe.db.get_value("Customer", {"email": user_email}, "name")
            if customer and booking_name:
                booking_customer = frappe.db.get_value("Rental Booking", booking_name, "customer")
                if booking_customer and booking_customer != customer:
                    context.booking = None
                    context.title = _("Booking Not Found - Bike Rental")
                    return context

    context.title = _("Booking Detail - Bike Rental")

    if not booking_name:
        context.booking = None
        return context

    booking = frappe.get_all(
        "Rental Booking",
        filters={"name": booking_name},
        fields=["name", "bike_model", "bike_serial", "customer_name",
                "pickup_hub", "return_hub", "pickup_datetime", "return_datetime",
                "status", "total_amount", "payment_entry", "deposit_released",
                "cancellation_reason", "cancellation_refund_amount",
                "end_km", "excess_km_charges", "late_return_fees",
                "damage_charges", "creation"],
        limit=1,
    )

    context.booking = booking[0] if booking else None

    if context.booking:
        # Payment info
        context.payment = None
        if context.booking.payment_entry:
            context.payment = frappe.db.get_value(
                "Payment Entry",
                context.booking.payment_entry,
                ["name", "paid_amount", "mode_of_payment", "posting_date"],
                as_dict=True,
            )

    return context


@frappe.whitelist()
def get_booking_detail(booking_name):
    """Return booking detail data for AJAX."""
    # Customer authorization: non-staff users can only view their own bookings
    if frappe.session.user != "Guest":
        roles = frappe.get_roles()
        is_staff = "System Manager" in roles or "Hub Manager" in roles or "Hub Staff" in roles
        if not is_staff:
            user_email = frappe.session.user
            customer = frappe.db.get_value("Customer", {"email": user_email}, "name")
            if customer:
                booking_customer = frappe.db.get_value("Rental Booking", booking_name, "customer")
                if booking_customer and booking_customer != customer:
                    frappe.throw(_("Booking not found"))

    booking = frappe.get_all(
        "Rental Booking",
        filters={"name": booking_name},
        fields=["name", "bike_model", "bike_serial", "customer_name",
                "pickup_hub", "return_hub", "pickup_datetime", "return_datetime",
                "status", "total_amount", "payment_entry", "deposit_released",
                "cancellation_reason", "cancellation_refund_amount",
                "end_km", "excess_km_charges", "late_return_fees",
                "damage_charges", "creation"],
        limit=1,
    )

    if not booking:
        frappe.throw(_("Booking not found"))

    return booking[0]
