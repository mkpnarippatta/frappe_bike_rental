from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import now_datetime


def get_context(context):
    """Checkout page context."""
    context.title = _("Checkout - Bike Rental")

    if frappe.session.user == "Guest":
        from urllib.parse import quote
        redirect_to = quote(frappe.request.url, safe="")
        frappe.local.flags.redirect_location = "/login?redirect_to=" + redirect_to
        raise frappe.Redirect

    # Get params from URL (passed from booking widget)
    model = frappe.form_dict.get("model")
    start = frappe.form_dict.get("start")
    end = frappe.form_dict.get("end")
    hub = frappe.form_dict.get("hub")

    context.model_name = model
    context.start_date = start
    context.end_date = end
    context.hub = hub

    # Calculate amount for display
    context.base_amount = 0
    context.deposit = 0
    context.total_due = 0
    context.days = 0
    context.daily_rate = 0
    if model and start and end:
        from frappe.utils import getdate
        base_rate = frappe.db.get_value("Bike Model", model, "base_rate_daily") or 0
        days = max(1, (getdate(end) - getdate(start)).days)
        base_amount = float(base_rate) * days
        deposit = max(500, round(base_amount * 0.5, 2))
        context.daily_rate = float(base_rate)
        context.days = days
        context.base_amount = base_amount
        context.deposit = deposit
        context.total_due = base_amount + deposit

    return context


@frappe.whitelist()
def create_booking(model, hub, start_datetime, end_datetime, customer_email=None):
    """Create a Rental Booking in Draft status."""
    if not customer_email:
        customer_email = frappe.session.user

    # Resolve customer from user
    customer = frappe.db.get_value("Customer", {"email": customer_email}, "name")
    if not customer:
        frappe.throw(_("Customer profile not found. Please register first."))

    # Get customer_name
    customer_name = frappe.db.get_value("Customer", customer, "customer_name")

    # Check availability before creating
    from bike_rental.api.availability import check_availability
    avail = check_availability(hub, model, start_datetime, end_datetime)
    if avail.get("available", 0) < 1:
        frappe.throw(_("Sorry, this model is no longer available for the selected dates."))

    # Calculate price
    from frappe.utils import getdate, get_datetime
    start_dt = get_datetime(start_datetime)
    end_dt = get_datetime(end_datetime)
    start_d = start_dt.date()
    end_d = end_dt.date()
    days = max(1, (end_d - start_d).days)
    base_rate = frappe.db.get_value("Bike Model", model, "base_rate_daily") or 0
    total_amount = float(base_rate) * days

    # Create booking
    booking = frappe.get_doc({
        "doctype": "Rental Booking",
        "bike_model": model,
        "customer": customer,
        "customer_name": customer_name,
        "pickup_hub": hub,
        "return_hub": hub,
        "pickup_datetime": start_dt,
        "return_datetime": end_dt,
        "total_amount": total_amount,
    })
    booking.insert(ignore_permissions=True)

    return {
        "name": booking.name,
        "total_amount": total_amount,
        "status": booking.status,
        "message": _("Booking created successfully!"),
    }


@frappe.whitelist()
def process_payment(booking_name, amount, payment_method="Cash"):
    """Record a payment and confirm the booking."""
    booking = frappe.get_doc("Rental Booking", booking_name)

    # Server-side amount validation
    expected = float(booking.total_amount or 0)
    paid = float(amount or 0)
    if abs(paid - expected) > 0.01:
        frappe.throw(_("Payment amount {0} does not match booking total {1}.").format(paid, expected))

    customer = frappe.db.get_value("Rental Booking", booking_name, "customer")

    # Transaction safety
    try:
        # Create Payment Entry if ERPNext is installed
        pe_name = None
        if frappe.db.exists("DocType", "Payment Entry"):
            pe = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "paid_amount": paid,
                "received_amount": paid,
                "reference_no": booking_name,
                "reference_date": now_datetime().date(),
                "mode_of_payment": payment_method,
            })
            pe.insert(ignore_permissions=True)
            pe.submit()
            pe_name = pe.name

        booking.db_set("payment_method", payment_method)
        if pe_name:
            booking.db_set("payment_entry", pe_name)
        booking.submit()
    except Exception:
        frappe.db.rollback()
        frappe.throw(_("Payment processing failed. Please try again."))

    return {
        "booking_name": booking_name,
        "payment_entry": pe_name,
        "status": booking.status,
        "message": _("Payment successful! Booking confirmed."),
    }
