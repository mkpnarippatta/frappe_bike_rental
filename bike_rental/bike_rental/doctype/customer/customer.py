from __future__ import unicode_literals

import frappe
from frappe.model.document import Document


class Customer(Document):
    pass


def has_customer_permission(doc, ptype, user):
    """AR-09: Customer can read/write own profile; staff can read/write all.

    Customers can only write email and phone on their own record.
    Hub Staff, Hub Manager, System Manager have full access.
    """
    roles = frappe.get_roles(user)
    if "Hub Staff" in roles or "Hub Manager" in roles or "System Manager" in roles:
        return True

    # For list/dashboard queries, doc is the DocType name string, not a document
    if isinstance(doc, str):
        return False

    if ptype in ("read", "write"):
        customer_email = frappe.db.get_value("Customer", doc.name, "email")
        return customer_email and user.lower() == customer_email.lower()

    return False
