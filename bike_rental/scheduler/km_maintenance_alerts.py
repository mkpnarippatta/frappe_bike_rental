from __future__ import unicode_literals

import frappe
from frappe.utils.data import flt


def alert_maintenance_thresholds():
    """Check all active bike serials and create tiered alerts when KM readings approach thresholds.

    - 80-99% of service interval: "Service Due Soon" alert
    - 100%+ of service interval: "Service Overdue" alert (urgent)

    Runs daily via scheduler_events["daily"].
    Default service interval is 1000 KM, configurable per Bike Model.
    """
    serials = frappe.get_all(
        "Bike Serial",
        filters={"status": ["not in", ["Scrapped", "In Transit"]]},
        fields=["name", "current_km", "bike_model"],
    )

    managers = frappe.db.sql_list(
        "SELECT DISTINCT parent FROM `tabUserRole` WHERE role = 'Hub Manager'"
    )

    for serial in serials:
        threshold = flt(
            frappe.db.get_value("Bike Model", serial.bike_model, "service_interval_km") or 1000
        )
        if threshold <= 0:
            continue

        current_km = flt(serial.current_km)
        pct = current_km / threshold

        if pct >= 1.0:
            _send_alert(serial.name, current_km, threshold, "overdue", managers)
        elif pct >= 0.8:
            _send_alert(serial.name, current_km, threshold, "due_soon", managers)


def _send_alert(serial_name, current_km, threshold, tier, managers):
    """Create a ToDo for Hub Managers for the given threshold tier."""
    if tier == "overdue":
        label = "[Service Overdue]"
        description = (
            f"{label} Bike Serial {serial_name} has exceeded its service interval! "
            f"Current KM: {current_km} (threshold: {threshold} KM). "
            f"Immediate maintenance review recommended."
        )
    else:
        label = "[Service Due Soon]"
        description = (
            f"{label} Bike Serial {serial_name} is approaching its service interval. "
            f"Current KM: {current_km} ({current_km / threshold * 100:.0f}% of {threshold} KM)."
        )

    for manager in managers:
        existing = frappe.db.exists(
            "ToDo",
            {
                "allocated_to": manager,
                "description": description,
                "status": "Open",
            },
        )
        if existing:
            continue
        todo = frappe.get_doc(
            {"doctype": "ToDo", "description": description, "allocated_to": manager}
        )
        todo.insert(ignore_permissions=True)

    # Also send notification via the notification engine (Story 5.2)
    try:
        from bike_rental.notification.event_handlers import on_maintenance_alert
        on_maintenance_alert(serial_name, current_km, threshold)
    except Exception as e:
        frappe.log_error(
            title="Maintenance Alert Notification Failed",
            message="Serial {0}: {1}".format(serial_name, str(e)),
        )

    frappe.logger().info(f"{label} — {description}")
