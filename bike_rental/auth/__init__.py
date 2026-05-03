from __future__ import unicode_literals

import hashlib
import random
import re

import frappe
from frappe import _
from frappe.utils import now_datetime

MOBILE_RE = re.compile(r"^\+?\d{10,15}$")


def _hash_otp(otp):
    """Return SHA-256 hex digest of OTP."""
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def _generate_otp():
    """Generate a random 6-digit OTP."""
    return str(random.randint(100000, 999999))


def _send_whatsapp_otp(mobile, message):
    """Send OTP via WhatsApp synchronously, returning True on success."""
    try:
        from bike_rental.notification.queue import send_whatsapp, enqueue_notification

        name = enqueue_notification(
            mobile, "WhatsApp",
            variables={"subject": "OTP", "message": message},
            priority="High",
        )
        queue_entry = frappe.get_doc("Notification Queue", name)
        send_whatsapp(queue_entry)
        frappe.db.set_value("Notification Queue", name, "status", "Sent")
        return True
    except Exception as e:
        frappe.logger().warning("WhatsApp send failed for %s: %s", mobile, str(e))
        return False


def _send_sms_otp(mobile, message):
    """Send OTP via SMS synchronously, returning True on success."""
    try:
        from bike_rental.notification.queue import send_sms, enqueue_notification

        name = enqueue_notification(
            mobile, "SMS",
            variables={"subject": "OTP", "message": message},
            priority="High",
        )
        queue_entry = frappe.get_doc("Notification Queue", name)
        send_sms(queue_entry)
        frappe.db.set_value("Notification Queue", name, "status", "Sent")
        return True
    except Exception as e:
        frappe.logger().warning("SMS send failed for %s: %s", mobile, str(e))
        return False


def _send_otp(mobile, otp):
    """Send OTP via available channels. Tries WhatsApp first, then SMS.

    Returns True if sent successfully via any channel.
    """
    message = _("Your Bike Rental OTP is: {0}. It expires in 5 minutes.").format(otp)
    settings = frappe.get_single("Rental Notification Settings")

    # Try WhatsApp first
    if settings.get("enable_whatsapp_channel") and settings.get("whatsapp_phone_number_id"):
        if _send_whatsapp_otp(mobile, message):
            return True

    # Fall back to SMS
    if settings.get("enable_sms_channel"):
        if _send_sms_otp(mobile, message):
            return True

    return False


@frappe.whitelist(allow_guest=True)
def send_login_otp(mobile):
    """Send OTP to mobile.

    Returns:
        {"status": "sent", ...} on success
        {"status": "rate_limited", ...} if rate limited
    """
    mobile = mobile.strip()

    if not MOBILE_RE.match(mobile):
        frappe.throw(_("Invalid mobile number format"))

    # Rate limit: max 3 OTP requests per 60s per mobile
    since = frappe.utils.add_to_date(now_datetime(), seconds=-60)
    recent_count = frappe.db.count(
        "OTP Request",
        filters={
            "mobile": mobile,
            "creation": [">=", since],
        },
    )
    if recent_count >= 3:
        return {"status": "rate_limited", "message": _("Too many OTP requests. Please try again later.")}

    # Generate and hash OTP
    otp = _generate_otp()
    otp_hash = _hash_otp(otp)

    # Create OTP Request record
    doc = frappe.get_doc({
        "doctype": "OTP Request",
        "mobile": mobile,
        "otp_hash": otp_hash,
    })
    doc.insert(ignore_permissions=True)

    # Send OTP via WhatsApp (preferred) or SMS
    sent = _send_otp(mobile, otp)

    # Dev mode fallback: return OTP in response (regardless of SMS config)
    dev_otp = None
    if frappe.conf.developer_mode:
        dev_otp = otp

    if not sent and not dev_otp:
        frappe.throw(_("Failed to send OTP. Please try again."))

    response = {"status": "sent", "message": _("OTP sent to your mobile.")}
    if dev_otp:
        response["_dev_otp"] = dev_otp
        frappe.logger().info("DEV OTP for %s: %s", mobile, otp)

    return response


@frappe.whitelist(allow_guest=True)
def verify_login_otp(mobile, otp, redirect_to=None):
    """Verify OTP, then login or route to onboarding.

    Returns:
        {"status": "success", "redirect": "/profile"} if existing user
        {"status": "new_user", "mobile": mobile, "redirect": "/register?mobile=..."} if new
    """
    mobile = mobile.strip()
    otp = otp.strip()

    # Find latest unexpired, unverified OTP Request for mobile
    otp_req = frappe.get_all(
        "OTP Request",
        filters={
            "mobile": mobile,
            "verified": 0,
            "expires_at": [">", now_datetime()],
        },
        order_by="creation desc",
        limit=1,
    )
    if not otp_req:
        frappe.throw(_("No valid OTP found. Please request a new OTP."))

    doc = frappe.get_doc("OTP Request", otp_req[0].name)

    # Check attempt count
    if doc.attempt_count >= 5:
        frappe.throw(_("Too many failed attempts. Please request a new OTP."))

    # Verify OTP hash (Password field is encrypted, use decrypted value)
    stored_hash = frappe.utils.password.get_decrypted_password(
        "OTP Request", doc.name, "otp_hash"
    )
    if stored_hash != _hash_otp(otp):
        frappe.db.set_value("OTP Request", doc.name, "attempt_count", doc.attempt_count + 1)
        remaining = 4 - doc.attempt_count
        if remaining <= 0:
            frappe.throw(_("Too many failed attempts. Please request a new OTP."))
        frappe.throw(_("Invalid OTP. {0} attempts remaining.").format(remaining))

    # Mark verified
    frappe.db.set_value("OTP Request", doc.name, "verified", 1)

    # Check if user already exists with this mobile
    users = frappe.get_all(
        "User",
        filters={"mobile_no": mobile, "enabled": 1},
        limit=1,
    )
    if users:
        # Existing user — log in
        user_email = users[0].name
        frappe.db.set_value("OTP Request", doc.name, "user_email", user_email)
        frappe.local.login_manager.login_as(user_email)
        return {"status": "success", "redirect": redirect_to or "/profile"}
    else:
        # New user — route to onboarding
        from urllib.parse import quote
        reg_url = "/register?mobile=" + quote(mobile)
        if redirect_to:
            reg_url += "&redirect_to=" + quote(redirect_to)
        return {"status": "new_user", "mobile": mobile, "redirect": reg_url}


@frappe.whitelist(allow_guest=True)
def resend_otp(mobile):
    """Invalidate old unverified OTPs and send a new one."""
    mobile = mobile.strip()

    # Invalidate all unverified OTPs for this mobile
    unverified = frappe.get_all(
        "OTP Request",
        filters={"mobile": mobile, "verified": 0},
    )
    for req in unverified:
        # Expire them by setting expires_at to now
        frappe.db.set_value("OTP Request", req.name, "expires_at", now_datetime())

    return send_login_otp(mobile)
