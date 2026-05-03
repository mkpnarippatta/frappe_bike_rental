from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import getdate

from bike_rental.notification.business_hours import enqueue_with_business_hours


def on_booking_confirmed(booking):
    """Send booking confirmation to customer via email + SMS."""
    customer = frappe.get_cached_doc("Customer", booking.customer)
    customer_name = customer.customer_name or booking.customer_name
    hub_name = frappe.db.get_value("Hub", booking.hub, "hub_name") or booking.hub

    variables = {
        "customer_name": customer_name,
        "booking_id": booking.name,
        "hub_name": hub_name,
        "model_name": booking.bike_model,
        "start_date": str(getdate(booking.start_date)),
        "start_time": str(booking.start_time or ""),
        "end_date": str(getdate(booking.end_date)),
        "end_time": str(booking.end_time or ""),
        "amount": str(booking.total_amount or 0),
        "date": str(getdate()),
    }

    enqueue_with_business_hours(
        "Booking Confirmation", customer.email or customer_name, "Email",
        variables=variables, priority="High",
        reference_doctype="Rental Booking", reference_docname=booking.name,
        hub=booking.hub,
    )

    if customer.phone:
        enqueue_with_business_hours(
            "Booking Confirmation", customer.phone, "SMS",
            variables=variables, priority="High",
            reference_doctype="Rental Booking", reference_docname=booking.name,
            hub=booking.hub,
        )


def on_kyc_status_change(customer, old_status, new_status):
    """Send KYC status change notification to customer."""
    customer_doc = frappe.get_cached_doc("Customer", customer)
    customer_name = customer_doc.customer_name
    hub_name = getattr(customer_doc, "hub_name", "")

    variables = {
        "customer_name": customer_name,
        "hub_name": hub_name or "System",
        "kyc_status": new_status,
        "old_kyc_status": old_status,
        "date": str(getdate()),
    }

    if customer_doc.email:
        enqueue_with_business_hours(
            "KYC Status Change", customer_doc.email, "Email",
            variables=variables, priority="High",
            reference_doctype="Customer", reference_docname=customer,
        )

    if customer_doc.phone:
        enqueue_with_business_hours(
            "KYC Status Change", customer_doc.phone, "SMS",
            variables=variables, priority="High",
            reference_doctype="Customer", reference_docname=customer,
        )


def on_cancellation(booking, reason=None):
    """Send cancellation confirmation to customer."""
    customer = frappe.get_cached_doc("Customer", booking.customer)
    customer_name = customer.customer_name or booking.customer_name
    hub_name = frappe.db.get_value("Hub", booking.hub, "hub_name") or booking.hub

    variables = {
        "customer_name": customer_name,
        "booking_id": booking.name,
        "hub_name": hub_name,
        "refund_amount": str(getattr(booking, "refund_amount", 0)),
        "reason": reason or _("No reason provided"),
        "date": str(getdate()),
    }

    if customer.email:
        enqueue_with_business_hours(
            "Cancellation Confirmation", customer.email, "Email",
            variables=variables, priority="High",
            reference_doctype="Rental Booking", reference_docname=booking.name,
            hub=booking.hub,
        )

    if customer.phone:
        enqueue_with_business_hours(
            "Cancellation Confirmation", customer.phone, "SMS",
            variables=variables, priority="High",
            reference_doctype="Rental Booking", reference_docname=booking.name,
            hub=booking.hub,
        )


def on_deposit_released(booking, amount):
    """Send deposit release notification to customer."""
    customer = frappe.get_cached_doc("Customer", booking.customer)
    customer_name = customer.customer_name or booking.customer_name
    hub_name = frappe.db.get_value("Hub", booking.hub, "hub_name") or booking.hub

    variables = {
        "customer_name": customer_name,
        "booking_id": booking.name,
        "hub_name": hub_name,
        "amount": str(amount),
        "date": str(getdate()),
    }

    if customer.email:
        enqueue_with_business_hours(
            "Deposit Release", customer.email, "Email",
            variables=variables,
            reference_doctype="Rental Booking", reference_docname=booking.name,
            hub=booking.hub,
        )


def on_booking_extended(booking, new_end_time, additional_charge=0):
    """Send booking extension confirmation."""
    customer = frappe.get_cached_doc("Customer", booking.customer)
    customer_name = customer.customer_name or booking.customer_name
    hub_name = frappe.db.get_value("Hub", booking.hub, "hub_name") or booking.hub

    variables = {
        "customer_name": customer_name,
        "booking_id": booking.name,
        "hub_name": hub_name,
        "new_end_time": str(new_end_time),
        "additional_charge": str(additional_charge),
        "date": str(getdate()),
    }

    if customer.email:
        enqueue_with_business_hours(
            "Booking Extension", customer.email, "Email",
            variables=variables,
            reference_doctype="Rental Booking", reference_docname=booking.name,
            hub=booking.hub,
        )

    if customer.phone:
        enqueue_with_business_hours(
            "Booking Extension", customer.phone, "SMS",
            variables=variables,
            reference_doctype="Rental Booking", reference_docname=booking.name,
            hub=booking.hub,
        )


def on_maintenance_alert(serial_no, km_reading, threshold, hub=None):
    """Send maintenance alert to staff."""
    serial_doc = frappe.get_cached_doc("Bike Serial", serial_no)
    hub_name = hub or serial_doc.hub or "Unknown"

    variables = {
        "serial_no": serial_no,
        "model_name": serial_doc.bike_model or "",
        "hub_name": hub_name,
        "km_reading": str(km_reading),
        "threshold": str(threshold),
        "date": str(getdate()),
    }

    # Maintenance alerts go to staff — find Hub Managers
    staff_emails = frappe.get_all(
        "User",
        filters={
            "role_profile_name": ("in", ["Hub Manager", "Hub Staff"]),
            "enabled": 1,
        },
        pluck="email",
    )

    for email in staff_emails:
        enqueue_with_business_hours(
            "Maintenance Alert", email, "Email",
            variables=variables,
            reference_doctype="Bike Serial", reference_docname=serial_no,
            hub=hub,
        )


def on_payment_receipt(booking, amount, payment_method=None):
    """Send payment receipt to customer."""
    customer = frappe.get_cached_doc("Customer", booking.customer)
    customer_name = customer.customer_name or booking.customer_name
    hub_name = frappe.db.get_value("Hub", booking.hub, "hub_name") or booking.hub

    variables = {
        "customer_name": customer_name,
        "booking_id": booking.name,
        "hub_name": hub_name,
        "amount": str(amount),
        "payment_method": payment_method or _("Cash"),
        "date": str(getdate()),
    }

    if customer.email:
        enqueue_with_business_hours(
            "Payment Receipt", customer.email, "Email",
            variables=variables, priority="High",
            reference_doctype="Rental Booking", reference_docname=booking.name,
            hub=booking.hub,
        )


# ── Scheduler Helper Functions ──
# These are called by scheduler jobs, not event hooks.


def _send_checkout_reminder(booking_dict):
    """Send checkout reminder for a booking starting in ~2 hours.

    Called by scheduler/checkout_reminders.py send_checkout_reminders().
    booking_dict is a dict from frappe.get_all().
    """
    customer = frappe.get_cached_doc("Customer", booking_dict.customer)
    customer_name = customer.customer_name or booking_dict.customer_name
    hub_name = frappe.db.get_value("Hub", booking_dict.hub, "hub_name") or booking_dict.hub

    variables = {
        "customer_name": customer_name,
        "booking_id": booking_dict.name,
        "hub_name": hub_name,
        "hub_address": "",
        "model_name": booking_dict.bike_model or "",
        "start_date": str(getdate(booking_dict.start_date)),
        "start_time": str(booking_dict.start_time or ""),
        "end_date": str(getdate(booking_dict.end_date)),
        "end_time": str(booking_dict.end_time or ""),
        "date": str(getdate()),
    }

    if customer.email:
        enqueue_with_business_hours(
            "Check-Out Reminder", customer.email, "Email",
            variables=variables,
            reference_doctype="Rental Booking", reference_docname=booking_dict.name,
            hub=booking_dict.hub,
        )


def _send_return_reminder(booking_dict):
    """Send return reminder for a booking ending in ~4 hours.

    Called by scheduler/return_reminders.py send_return_reminders().
    Sends to both staff and customer.
    """
    from bike_rental.notification.queue import enqueue_notification

    customer = frappe.get_cached_doc("Customer", booking_dict.customer)
    customer_name = customer.customer_name or booking_dict.customer_name
    hub_name = frappe.db.get_value("Hub", booking_dict.hub, "hub_name") or booking_dict.hub

    variables = {
        "customer_name": customer_name,
        "booking_id": booking_dict.name,
        "hub_name": hub_name,
        "model_name": booking_dict.bike_model or "",
        "end_date": str(getdate(booking_dict.end_date)),
        "end_time": str(booking_dict.end_time or ""),
        "date": str(getdate()),
    }

    # Notify customer
    if customer.email:
        enqueue_with_business_hours(
            "Check-In Reminder", customer.email, "Email",
            variables=variables,
            reference_doctype="Rental Booking", reference_docname=booking_dict.name,
            hub=booking_dict.hub,
        )

    # Notify staff
    staff_emails = frappe.get_all(
        "User",
        filters={
            "role_profile_name": ("in", ["Hub Manager", "Hub Staff"]),
            "enabled": 1,
        },
        pluck="email",
    )
    staff_vars = dict(variables)
    for email in staff_emails:
        enqueue_notification(
            email, "Email",
            template="checkin_reminder",
            variables=staff_vars,
            reference_doctype="Rental Booking",
            reference_docname=booking_dict.name,
            hub=booking_dict.hub,
        )
