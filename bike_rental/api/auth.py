from __future__ import unicode_literals

import frappe


@frappe.whitelist(allow_guest=True)
def send_login_otp(mobile):
    from bike_rental.auth import send_login_otp as _send_login_otp
    return _send_login_otp(mobile)


@frappe.whitelist(allow_guest=True)
def verify_login_otp(mobile, otp, redirect_to=None):
    from bike_rental.auth import verify_login_otp as _verify_login_otp
    return _verify_login_otp(mobile, otp, redirect_to)


@frappe.whitelist(allow_guest=True)
def resend_otp(mobile):
    from bike_rental.auth import resend_otp as _resend_otp
    return _resend_otp(mobile)


@frappe.whitelist(allow_guest=True)
def login_email(user, password):
    from bike_rental.auth import login_email as _login_email
    return _login_email(user, password)


@frappe.whitelist(allow_guest=True)
def get_current_user():
    from bike_rental.auth import get_current_user as _get_current_user
    return _get_current_user()
