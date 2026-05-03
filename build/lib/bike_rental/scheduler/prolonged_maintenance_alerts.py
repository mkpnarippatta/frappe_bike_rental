from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime, add_to_date, get_datetime


def alert_prolonged_maintenance():
    """Check for bikes in maintenance for more than 14 days and alert Hub Managers.

    Runs daily via scheduler_events["daily"].
    Creates a ToDo for all users with the Hub Manager role.
    """
    fourteen_days_ago = add_to_date(now_datetime(), days=-14)

    prolonged = frappe.get_all(
        "Maintenance Log",
        filters={
            "status": "In Progress",
            "reported_date": ["<=", fourteen_days_ago],
        },
        fields=["name", "serial_no", "reported_date", "issue_description"],
    )

    if not prolonged:
        return

    # Get all Hub Manager users via UserRole table
    managers = frappe.db.sql_list(
        "SELECT DISTINCT parent FROM `tabUserRole` WHERE role = 'Hub Manager'"
    )

    for log in prolonged:
        reported = get_datetime(log.reported_date)
        days_in_maintenance = (now_datetime() - reported).days
        subject = f"Prolonged Maintenance Alert: {log.serial_no}"
        description = (
            f"Bike Serial {log.serial_no} has been under maintenance "
            f"for {days_in_maintenance} days (reported: {reported.date()}).\n"
            f"Issue: {log.issue_description}\n"
            f"Maintenance Log: {log.name}"
        )

        # Avoid duplicate ToDos — skip if identical one already exists for manager
        for manager in managers:
            existing = frappe.db.exists("ToDo", {
                "allocated_to": manager,
                "description": description,
                "status": "Open",
            })
            if existing:
                continue
            todo = frappe.get_doc({
                "doctype": "ToDo",
                "description": description,
                "allocated_to": manager,
            })
            todo.insert(ignore_permissions=True)

        frappe.logger().info(f"{subject} — {description}")
