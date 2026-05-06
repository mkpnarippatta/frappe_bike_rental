from __future__ import unicode_literals

import re

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


@frappe.whitelist()
def get_customer_profile(customer_name):
    """Return customer profile with KYC summary and document expiry warnings.

    AR-09: Owner-only reads + Hub Staff/Manager/System Manager override.
    """
    _validate_customer(customer_name)

    if not _can_access_customer(customer_name):
        frappe.throw(
            _("You do not have permission to view this customer profile"),
            frappe.PermissionError,
        )

    customer = frappe.get_doc("Customer", customer_name)

    # Gather KYC document summary
    kyc_docs = frappe.get_all(
        "KYC Document",
        filters={"customer": customer_name},
        fields=["name", "document_type", "status", "uploaded_date", "rejection_reason", "expiry_date"],
        order_by="uploaded_date desc",
    )

    # Identify documents expiring within 30 days
    thirty_days_from_now = getdate(add_days(today(), 30))
    today_date = getdate(today())
    expiry_warnings = []
    for doc in kyc_docs:
        if doc.status == "Verified" and doc.expiry_date:
            expiry = getdate(doc.expiry_date)
            if expiry <= thirty_days_from_now:
                expiry_warnings.append({
                    "document_type": doc.document_type,
                    "expiry_date": str(doc.expiry_date),
                    "days_remaining": (expiry - today_date).days,
                })

    return {
        "status": "success",
        "profile": {
            "customer_name": customer.customer_name,
            "email": customer.email,
            "phone": customer.phone,
            "kyc_status": customer.kyc_status or "Unverified",
            "kyc_completed_date": str(customer.kyc_completed_date) if customer.kyc_completed_date else None,
            "member_since": str(customer.creation.date()) if customer.creation else None,
        },
        "kyc_documents": [
            {
                "name": d.name,
                "document_type": d.document_type,
                "status": d.status,
                "uploaded_date": str(d.uploaded_date) if d.uploaded_date else None,
                "rejection_reason": d.rejection_reason,
                "expiry_date": str(d.expiry_date) if d.expiry_date else None,
            }
            for d in kyc_docs
        ],
        "expiry_warnings": expiry_warnings,
    }


@frappe.whitelist()
def update_customer_profile(customer_name, updates=None):
    """Update customer email and/or phone.

    AR-09: Owner-only writes + Hub Staff/Manager/System Manager override.
    Only email and phone can be changed. Customer name is identity and cannot be changed.
    Sends confirmation notification on email change.
    """
    _validate_customer(customer_name)

    if not _can_access_customer(customer_name):
        frappe.throw(
            _("You do not have permission to update this customer profile"),
            frappe.PermissionError,
        )

    if not updates:
        frappe.throw(_("No updates provided"), frappe.ValidationError)

    if isinstance(updates, str):
        updates = frappe.parse_json(updates)

    # Prevent changing customer_name
    if "customer_name" in updates:
        frappe.throw(
            _("Customer name cannot be changed. It is your identity."),
            frappe.ValidationError,
        )

    customer = frappe.get_doc("Customer", customer_name)
    old_email = customer.email
    changed = []

    # Update email if provided
    if "email" in updates and updates["email"] != customer.email:
        new_email = updates["email"]
        _validate_email(new_email)
        # Prevent duplicate emails
        existing = frappe.db.exists("Customer", {"email": new_email, "name": ["!=", customer_name]})
        if existing:
            frappe.throw(
                _("Email {0} is already in use by another customer").format(new_email),
                frappe.ValidationError,
            )
        customer.email = new_email
        changed.append("email")

    # Update phone if provided
    if "phone" in updates and updates["phone"] != customer.phone:
        new_phone = updates["phone"]
        _validate_phone(new_phone)
        customer.phone = new_phone
        changed.append("phone")

    if not changed:
        return {
            "status": "success",
            "message": _("No changes were made."),
        }

    customer.save(ignore_permissions=True)

    # Send confirmation notification on email change
    if "email" in changed:
        _notify_email_change(old_email, customer.email, customer_name)

    return {
        "status": "success",
        "message": _("Profile updated: {0}").format(", ".join(changed)),
        "profile": {
            "customer_name": customer.customer_name,
            "email": customer.email,
            "phone": customer.phone,
        },
    }


@frappe.whitelist()
def get_dashboard_summary():
    """Return customer dashboard summary (active booking, recent bookings, KYC status).

    Uses the currently logged-in user's customer record.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Please log in first"))

    customer = frappe.db.get_value(
        "Customer",
        {"email": frappe.session.user},
        ["name", "customer_name", "kyc_status", "phone", "email"],
        as_dict=True,
    )

    if not customer:
        return {
            "status": "success",
            "profile": None,
            "active_booking": None,
            "recent_bookings": [],
            "kyc_documents": [],
        }

    # Active booking
    active_booking = frappe.get_all(
        "Rental Booking",
        filters={"customer": customer.name, "status": "Active", "docstatus": 1},
        fields=["name", "bike_model", "pickup_hub", "pickup_datetime",
                "return_datetime", "total_amount", "creation"],
        limit=1,
    )
    active_booking = active_booking[0] if active_booking else None

    # Recent bookings (excluding active)
    recent_bookings = frappe.get_all(
        "Rental Booking",
        filters={
            "customer": customer.name,
            "docstatus": 1,
            "status": ["!=", "Active"],
        },
        fields=["name", "bike_model", "pickup_hub", "status", "pickup_datetime",
                "return_datetime", "total_amount"],
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

    return {
        "status": "success",
        "user_email": customer.email,
        "user_name": customer.customer_name,
        "customer": {
            "name": customer.name,
            "customer_name": customer.customer_name,
            "kyc_status": customer.kyc_status or "Unverified",
            "phone": customer.phone,
        },
        "active_booking": active_booking,
        "recent_bookings": recent_bookings,
        "kyc_documents": kyc_docs,
    }


@frappe.whitelist()
def update_own_profile(full_name=None, mobile=None):
    """Update the current user's customer profile fields."""
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

    return {"status": "success", "message": _("Profile updated successfully")}


# ── Internal helpers ──


def _validate_customer(customer_name):
    if not frappe.db.exists("Customer", customer_name):
        frappe.throw(
            _("Customer {0} does not exist").format(customer_name),
            frappe.ValidationError,
        )


def _validate_email(email):
    """Basic email format validation."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email):
        frappe.throw(
            _("Invalid email format: {0}").format(email),
            frappe.ValidationError,
        )


def _validate_phone(phone):
    """Basic phone validation — must be non-empty with reasonable length."""
    if not phone or not phone.strip():
        frappe.throw(
            _("Phone number cannot be empty"),
            frappe.ValidationError,
        )
    if len(phone.strip()) < 6 or len(phone.strip()) > 20:
        frappe.throw(
            _("Phone number must be between 6 and 20 characters"),
            frappe.ValidationError,
        )


def _notify_email_change(old_email, new_email, customer_name):
    """Send security alert to old email and confirmation to new email."""
    # Security alert to old email
    if old_email:
        alert = frappe.get_doc({
            "doctype": "Notification Log",
            "subject": _("Your email address has been changed"),
            "email_content": _(
                "Your Bike Rental account email has been changed from {0} to {1}. "
                "If you did not request this change, please contact support immediately."
            ).format(old_email, new_email),
            "for_user": old_email,
            "document_type": "Customer",
            "document_name": customer_name,
        })
        alert.insert(ignore_permissions=True)

    # Confirmation to new email
    confirmation = frappe.get_doc({
        "doctype": "Notification Log",
        "subject": _("Email address updated successfully"),
        "email_content": _(
            "Your Bike Rental account email has been updated to {0}."
        ).format(new_email),
        "for_user": new_email,
        "document_type": "Customer",
        "document_name": customer_name,
    })
    confirmation.insert(ignore_permissions=True)


def _can_access_customer(customer_name):
    """Check if the current user can access this customer's profile.

    AR-09: Owner-only access + Hub Staff/Manager/System Manager override.
    """
    roles = frappe.get_roles()
    if "Hub Staff" in roles or "Hub Manager" in roles or "System Manager" in roles:
        return True
    customer_email = frappe.db.get_value("Customer", customer_name, "email")
    return customer_email and frappe.session.user.lower() == customer_email.lower()
