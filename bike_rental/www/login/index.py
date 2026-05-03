from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import today


def get_context(context):
    """Login page context."""
    context.title = _("Login - Bike Rental")
    context.use_otp_login = True
    context.developer_mode = frappe.conf.developer_mode
    return context
