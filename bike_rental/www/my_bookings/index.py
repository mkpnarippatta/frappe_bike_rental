from __future__ import unicode_literals

import frappe
from frappe import _


def get_context(context):
    """My Bookings page context."""
    context.title = _("My Bookings - Bike Rental")

    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect_to=/my_bookings"
        raise frappe.Redirect

    # Resolve customer
    customer = frappe.db.get_value(
        "Customer", {"email": frappe.session.user}, "name"
    )

    if not customer:
        context.bookings = []
        context.customer_name = None
        return context

    context.customer_name = frappe.db.get_value("Customer", customer, "customer_name")

    # Get all bookings
    status_filter = frappe.form_dict.get("status")

    filters = {"customer": customer, "docstatus": 1}
    if status_filter:
        filters["status"] = status_filter

    context.bookings = frappe.get_all(
        "Rental Booking",
        filters=filters,
        fields=["name", "bike_model", "hub", "status", "start_date",
                "end_date", "total_amount", "creation"],
        order_by="creation desc",
    )

    context.active_status = status_filter or ""

    return context


@frappe.whitelist()
def get_customer_bookings(customer_name, status=None):
    """Return bookings for a customer (AJAX)."""
    filters = {"customer": customer_name, "docstatus": 1}
    if status:
        filters["status"] = status

    return frappe.get_all(
        "Rental Booking",
        filters=filters,
        fields=["name", "bike_model", "hub", "status", "start_date",
                "end_date", "total_amount", "creation"],
        order_by="creation desc",
    )
