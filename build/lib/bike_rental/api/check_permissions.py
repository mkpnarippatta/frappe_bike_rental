from __future__ import unicode_literals

import frappe


def has_serial_permission(doc, ptype, user):
    """Permission handler for Bike Serial."""
    if "System Manager" in frappe.get_roles(user):
        return True

    return False


def has_booking_permission(doc, ptype, user):
    """Permission handler for Rental Booking."""
    if "System Manager" in frappe.get_roles(user):
        return True

    return False
