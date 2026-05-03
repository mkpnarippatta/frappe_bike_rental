from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist()
def mark_for_maintenance(serial_no, issue_description):
    """Mark a Bike Serial for maintenance.

    Creates a Maintenance Log entry and sets the serial status to "Maintenance".
    Requires Hub Staff or Hub Manager role.
    The serial must be in an active state (not already Maintenance, Scrapped, or Rented).
    """
    roles = frappe.get_roles()
    if not ("Hub Manager" in roles or "Hub Staff" in roles or "System Manager" in roles):
        frappe.throw(
            _("Only Hub Staff, Hub Managers, and System Managers can mark bikes for maintenance"),
            frappe.PermissionError,
        )

    if not frappe.db.exists("Bike Serial", serial_no):
        frappe.throw(
            _("Bike Serial {0} does not exist").format(serial_no),
            frappe.ValidationError,
        )

    serial = frappe.get_doc("Bike Serial", serial_no)
    if serial.status in ("Maintenance", "Scrapped", "Rented"):
        frappe.throw(
            _("Bike Serial {0} is {1} — cannot mark for maintenance").format(serial_no, serial.status),
            frappe.ValidationError,
        )

    log = frappe.get_doc({
        "doctype": "Maintenance Log",
        "serial_no": serial_no,
        "issue_description": issue_description,
        "reported_date": frappe.utils.now_datetime(),
        "reported_by": frappe.session.user,
        "status": "In Progress",
    })
    log.insert(ignore_permissions=True)

    return {
        "status": "success",
        "maintenance_log": log.name,
        "serial_no": serial_no,
        "previous_status": serial.status,
        "new_status": "Maintenance",
    }


@frappe.whitelist()
def resolve_maintenance(log_name, resolution_notes, resolution_cost=0):
    """Resolve a maintenance log, restoring the bike serial to Available.

    Requires Hub Staff or Hub Manager role.
    Delegates to DocType hooks (before_save, on_update) which handle
    resolved_date/resolved_by setting and serial status restoration.
    """
    roles = frappe.get_roles()
    if not ("Hub Manager" in roles or "Hub Staff" in roles or "System Manager" in roles):
        frappe.throw(
            _("Only Hub Staff, Hub Managers, and System Managers can resolve maintenance logs"),
            frappe.PermissionError,
        )

    log = frappe.get_doc("Maintenance Log", log_name)

    if log.status == "Resolved":
        frappe.throw(
            _("Maintenance Log {0} is already resolved").format(log_name),
            frappe.ValidationError,
        )

    log.resolution_notes = resolution_notes
    log.resolution_cost = resolution_cost
    log.status = "Resolved"
    log.save(ignore_permissions=True)

    log.reload()
    serial = frappe.get_doc("Bike Serial", log.serial_no)

    return {
        "status": "success",
        "maintenance_log": log_name,
        "serial_no": log.serial_no,
        "serial_status": serial.status,
    }
