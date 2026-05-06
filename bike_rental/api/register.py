from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils.password import update_password


@frappe.whitelist(allow_guest=True)
def register_customer(full_name, email, mobile, password=None, redirect_to=None):
    """Create a new Customer and User record."""
    if not full_name or not email:
        frappe.throw(_("Full name and email are required"))

    # Check if user already exists
    if frappe.db.exists("User", email):
        frappe.throw(_("A user with this email already exists"), frappe.DuplicateEntryError)

    # Create User
    user = frappe.get_doc({
        "doctype": "User",
        "email": email,
        "first_name": full_name,
        "mobile_no": mobile,
        "send_welcome_email": 0,
        "user_type": "Website User",
    })
    user.insert(ignore_permissions=True)

    # Set password (auto-generate if not provided — OTP-verified users log in via OTP)
    if not password:
        import secrets
        password = secrets.token_urlsafe(12)
    update_password(user=email, pwd=password)

    # Create Customer record (autoname is "prompt", so set name explicitly)
    customer = frappe.get_doc({
        "doctype": "Customer",
        "name": email,
        "customer_name": full_name,
        "customer_type": "Individual",
        "email": email,
        "phone": mobile,
        "kyc_status": "Unverified",
    })
    customer.insert(ignore_permissions=True)

    # Assign Customer role
    user.add_roles("Customer")

    # Auto-login
    frappe.local.login_manager.login_as(email)

    return {
        "user": email,
        "customer": customer.name,
        "redirect": redirect_to or "/profile",
        "message": _("Registration successful!"),
    }
