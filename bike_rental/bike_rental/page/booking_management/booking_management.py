from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist()
def get_bookings(hub=None, status=None, date_from=None, date_to=None,
                 customer=None, booking_id=None, limit=50):
    """Return filtered list of rental bookings."""
    filters = {"docstatus": 1}

    if hub:
        filters["pickup_hub"] = hub
    if status:
        filters["status"] = status
    if date_from:
        filters["pickup_datetime"] = [">=", date_from]
    if date_to:
        filters["return_datetime"] = ["<=", date_to]
    if customer:
        filters["customer"] = ["like", "%{0}%".format(customer)]
    if booking_id:
        filters["name"] = ["like", "%{0}%".format(booking_id)]

    # Auto-scope to user's hub for non-System-Manager
    roles = frappe.get_roles()
    if "System Manager" not in roles:
        user_hub = _get_user_hub(frappe.session.user)
        if user_hub:
            filters["pickup_hub"] = user_hub

    bookings = frappe.get_all(
        "Rental Booking",
        filters=filters,
        fields=[
            "name", "customer", "customer_name", "bike_model", "bike_serial",
            "pickup_hub", "return_hub", "status",
            "pickup_datetime as start_date", "return_datetime as end_date",
            "total_amount", "payment_entry", "deposit_released",
            "creation",
        ],
        order_by="pickup_datetime desc, creation desc",
        limit=limit,
    )

    # Enrich with customer KYC status
    for b in bookings:
        b.kyc_status = frappe.db.get_value("Customer", b.customer, "kyc_status") or "Unverified"

    return bookings


@frappe.whitelist()
def get_booking_detail(booking_name):
    """Return full booking detail with customer info."""
    booking = frappe.get_doc("Rental Booking", booking_name)

    customer = frappe.get_cached_doc("Customer", booking.customer)
    hub_doc = frappe.get_cached_doc("Hub", booking.pickup_hub) if frappe.db.exists("Hub", booking.pickup_hub) else None

    return {
        "booking": booking.as_dict(),
        "customer": {
            "name": customer.name,
            "customer_name": customer.customer_name,
            "email": customer.email,
            "mobile": customer.phone,
            "kyc_status": customer.kyc_status or "Unverified",
        },
        "hub": {
            "name": hub_doc.name if hub_doc else None,
            "hub_name": hub_doc.hub_name if hub_doc else None,
            "address": hub_doc.address if hub_doc else None,
        } if hub_doc else None,
    }


@frappe.whitelist()
def process_checkout(booking_name, serial_no):
    """Process checkout for a booking using existing check_out API."""
    from bike_rental.api.check_out import check_out
    return check_out(booking_name, serial_no)


@frappe.whitelist()
def process_cancellation(booking_name, reason=None):
    """Cancel a booking with reason."""
    from bike_rental.api.cancel_booking import cancel_booking
    return cancel_booking(booking_name, reason or _("Cancelled by staff"))


def _get_user_hub(user):
    """Determine the hub assigned to a non-System-Manager user."""
    user_hub = frappe.db.get_value("User", user, "hub")
    if user_hub:
        return user_hub
    hub = frappe.db.get_value("Hub", {"hub_manager": user}, "name")
    if hub:
        return hub
    return None
