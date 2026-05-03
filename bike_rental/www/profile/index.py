from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import now_datetime


def get_context(context):
    """Customer profile/dashboard page."""
    context.title = _("My Dashboard - Bike Rental")

    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect_to=/profile"
        raise frappe.Redirect

    user = frappe.get_doc("User", frappe.session.user)

    customer = frappe.db.get_value(
        "Customer",
        {"email": user.email},
        ["name", "customer_name", "kyc_status", "phone"],
        as_dict=True,
    )

    context.user_email = user.email
    context.user_name = user.first_name

    if customer:
        context.customer_name = customer.customer_name
        context.kyc_status = customer.kyc_status or "Unverified"
        context.mobile = customer.phone
        context.customer_id = customer.name

        # Active booking
        context.active_booking = frappe.get_all(
            "Rental Booking",
            filters={"customer": customer.name, "status": "Active", "docstatus": 1},
            fields=["name", "bike_model", "bike_serial", "hub", "start_date",
                    "end_date", "start_time", "end_time", "total_amount",
                    "creation"],
            limit=1,
        )
        context.active_booking = context.active_booking[0] if context.active_booking else None

        # Recent bookings (excluding active)
        context.recent_bookings = frappe.get_all(
            "Rental Booking",
            filters={
                "customer": customer.name,
                "docstatus": 1,
                "status": ["!=", "Active"],
            },
            fields=["name", "bike_model", "hub", "status", "start_date",
                    "end_date", "total_amount"],
            order_by="creation desc",
            limit=5,
        )

        # KYC document status
        kyc_docs = frappe.get_all(
            "KYC Document",
            filters={"customer": customer.name},
            fields=["name", "document_type", "status", "creation"],
            order_by="creation desc",
            limit=5,
        )
        context.kyc_documents = kyc_docs
    else:
        context.kyc_status = "Unverified"
        context.active_booking = None
        context.recent_bookings = []
        context.kyc_documents = []

    return context


@frappe.whitelist()
def update_profile(full_name=None, mobile=None):
    """Update customer profile fields."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please log in first"))

    customer = frappe.db.get_value(
        "Customer", {"email": frappe.session.user}, "name"
    )
    if not customer:
        frappe.throw(_("Customer profile not found"))

    if full_name:
        frappe.db.set_value("Customer", customer, "customer_name", full_name)
        frappe.db.set_value("User", frappe.session.user, "first_name", full_name)

    if mobile:
        frappe.db.set_value("Customer", customer, "phone", mobile)

    return {"message": _("Profile updated successfully")}
