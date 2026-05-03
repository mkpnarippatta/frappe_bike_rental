from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime


def log_transition(doctype, docname, from_status, to_status, user=None, notes=None):
    """Log a state transition to the audit trail.

    Args:
        doctype: DocType name (e.g., "Rental Booking")
        docname: Document name/ID
        from_status: Previous status value
        to_status: New status value
        user: User who performed the action (defaults to frappe.session.user)
        notes: Optional additional context

    The built-in Frappe tabVersion captures all field changes automatically.
    This provides supplementary structured logging for key operational transitions.
    """
    frappe.get_doc(
        {
            "doctype": "Audit Log",
            "document_type": doctype,
            "document_name": docname,
            "from_status": from_status,
            "to_status": to_status,
            "timestamp": now_datetime(),
            "user": user or frappe.session.user,
            "notes": notes or "",
        }
    ).insert(ignore_permissions=True)
