from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import getdate, get_datetime, now_datetime


@frappe.whitelist()
def create_booking(model, hub, start_datetime, end_datetime, customer_email=None):
    """Create a Rental Booking in Draft status."""
    if not customer_email:
        customer_email = frappe.session.user

    # Resolve customer from user
    customer = frappe.db.get_value("Customer", {"email": customer_email}, "name")
    if not customer:
        frappe.throw(_("Customer profile not found. Please register first."))

    customer_name = frappe.db.get_value("Customer", customer, "customer_name")

    # Check availability before creating
    from bike_rental.api.availability import check_availability
    avail = check_availability(hub, model, start_datetime, end_datetime)
    if avail.get("available", 0) < 1:
        frappe.throw(_("Sorry, this model is no longer available for the selected dates."))

    # Calculate price
    start_dt = get_datetime(start_datetime)
    end_dt = get_datetime(end_datetime)
    days = max(1, (end_dt.date() - start_dt.date()).days)
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
    pe_name = None
    try:
        # Bypass permission checks for customer-facing booking flow
        booking.flags.ignore_permissions = True

        # Create Payment Entry if ERPNext is installed
        if frappe.db.exists("DocType", "Payment Entry"):
            company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
            if not company:
                frappe.throw(_("No Company set up. Please contact administrator."))

            default_cash_account = frappe.db.get_value("Company", company, "default_cash_account")
            if not default_cash_account:
                frappe.throw(_("No default cash account found for company {0}. Please configure it in accounting settings.").format(company))

            pe = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "paid_amount": paid,
                "received_amount": paid,
                "company": company,
                "target_exchange_rate": 1,
                "reference_no": booking_name,
                "reference_date": now_datetime().date(),
                "mode_of_payment": payment_method,
                "paid_to": default_cash_account,
                "paid_to_account_currency": frappe.db.get_value("Account", default_cash_account, "account_currency"),
            })
            pe.flags.ignore_mandatory = True
            pe.set_missing_values()
            pe.flags.ignore_permissions = True
            pe.insert(ignore_permissions=True, ignore_mandatory=True)
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


@frappe.whitelist()
def get_customer_bookings(customer_name, status=None):
    """Return bookings for a customer (AJAX)."""
    filters = {"customer": customer_name, "docstatus": 1}
    if status:
        filters["status"] = status

    return frappe.get_all(
        "Rental Booking",
        filters=filters,
        fields=["name", "bike_model", "pickup_hub", "status", "pickup_datetime",
                "return_datetime", "total_amount", "creation"],
        order_by="creation desc",
    )


@frappe.whitelist()
def get_booking_detail(booking_name):
    """Return booking detail data."""
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

    result = booking[0]

    # Fetch payment info
    if result.get("payment_entry"):
        payment = frappe.db.get_value(
            "Payment Entry",
            result["payment_entry"],
            ["name", "paid_amount", "mode_of_payment", "posting_date"],
            as_dict=True,
        )
        result["payment"] = payment

    return result
