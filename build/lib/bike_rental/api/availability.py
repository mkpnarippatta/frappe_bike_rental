from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def check_availability(hub, model, start_datetime, end_datetime):
    """Check real-time availability for a Bike Model at a specific hub for a date range (FR-06).

    Returns dict with total capacity, occupied bookings, safety margin, and available count.
    Available = Total Capacity - Occupied Bookings - Safety Margin.
    """
    # Input validation
    if not frappe.db.exists("Hub", hub):
        frappe.throw(_("Hub {0} does not exist").format(hub), frappe.ValidationError)

    if not frappe.db.exists("Bike Model", model):
        frappe.throw(
            _("Bike Model {0} does not exist").format(model), frappe.ValidationError
        )

    if start_datetime >= end_datetime:
        frappe.throw(
            _("Start datetime must be before end datetime"), frappe.ValidationError
        )

    # Total Capacity: Bike Serials for model+hub where status is Available or Rented
    # Excludes Scrapped, In Transit (gone or between hubs), and Maintenance (unrideable)
    total = frappe.db.count(
        "Bike Serial",
        filters={
            "bike_model": model,
            "hub": hub,
            "status": ["not in", ["Scrapped", "In Transit", "Maintenance"]],
        },
    )

    # Occupied: Confirmed + Active bookings overlapping the requested date range
    # Two ranges [A, B) and [C, D) overlap if: A < D AND C < B
    # pickup_datetime < end_datetime AND return_datetime > start_datetime
    occupied = frappe.db.count(
        "Rental Booking",
        filters={
            "bike_model": model,
            "pickup_hub": hub,
            "status": ["in", ["Confirmed", "Active"]],
            "pickup_datetime": ["<", end_datetime],
            "return_datetime": [">", start_datetime],
        },
    )

    # Safety Margin from Bike Model
    safety_margin = frappe.db.get_value("Bike Model", model, "safety_margin") or 0

    available = max(0, total - occupied - safety_margin)

    return {
        "total": total,
        "occupied": occupied,
        "available": available,
        "safety_margin": safety_margin,
    }
