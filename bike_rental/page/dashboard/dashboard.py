from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date


@frappe.whitelist()
def get_dashboard_data(hub=None):
    """Return dashboard metrics scoped to user's hub(s).

    Hub Staff/Managers see data for their assigned hub only.
    System Manager sees all hubs, with optional hub filter.
    """
    user = frappe.session.user
    roles = frappe.get_roles(user)
    is_system_manager = "System Manager" in roles

    if not is_system_manager:
        hub = _get_user_hub(user)
        if not hub:
            return {"error": _("No hub assigned to your account")}

    hub_filter = {"hub": hub} if hub else {}

    # Active bookings count
    active_bookings = frappe.db.count(
        "Rental Booking", filters={**hub_filter, "status": "Active", "docstatus": 1}
    )

    # Available bikes count (exclude Scrapped, In Transit, Maintenance, Rented)
    available_filters = {"status": "Available"}
    if hub_filter:
        available_filters["hub"] = hub
    available_bikes = frappe.db.count("Bike Serial", filters=available_filters)

    # Bikes under maintenance
    maintenance_filters = {"status": "Maintenance"}
    if hub_filter:
        maintenance_filters["hub"] = hub
    maintenance_bikes = frappe.db.count("Bike Serial", filters=maintenance_filters)

    # Pending KYC verifications
    pending_kyc = frappe.db.count(
        "KYC Document", filters={"status": "Pending Review"}
    )

    # Today's check-outs (bookings confirmed today and starting today)
    today = now_datetime().date()
    today_checkouts = frappe.db.count(
        "Rental Booking",
        filters={
            "status": "Active",
            "start_date": today,
            "docstatus": 1,
        },
    )

    # Today's check-ins (expected returns today)
    today_checkins = frappe.db.count(
        "Rental Booking",
        filters={
            "status": ["in", ["Active", "Confirmed"]],
            "end_date": today,
            "docstatus": 1,
        },
    )

    # Total capacity per hub (for context)
    total_capacity = frappe.db.count(
        "Bike Serial",
        filters={
            **({"hub": hub} if hub else {}),
            "status": ["not in", ["Scrapped", "In Transit"]],
        },
    )

    # Rented bikes count
    rented_filters = {"status": "Rented"}
    if hub_filter:
        rented_filters["hub"] = hub
    rented_bikes = frappe.db.count("Bike Serial", filters=rented_filters)

    return {
        "active_bookings": active_bookings,
        "available_bikes": available_bikes,
        "maintenance_bikes": maintenance_bikes,
        "rented_bikes": rented_bikes,
        "total_capacity": total_capacity,
        "pending_kyc": pending_kyc,
        "today_checkouts": today_checkouts,
        "today_checkins": today_checkins,
        "hub": hub,
        "is_system_manager": is_system_manager,
    }


@frappe.whitelist()
def get_pending_kyc_highlights(hub=None):
    """Return pending KYC documents, highlighting those waiting >24hr."""
    user = frappe.session.user
    roles = frappe.get_roles(user)
    is_system_manager = "System Manager" in roles

    if not is_system_manager:
        hub = _get_user_hub(user)
        if not hub:
            return {"total_pending": 0, "high_priority_count": 0, "items": []}

    twenty_four_hours_ago = add_to_date(now_datetime(), hours=-24)

    filters = {"status": "Pending Review"}
    docs = frappe.get_all(
        "KYC Document",
        filters=filters,
        fields=["name", "customer", "document_type", "uploaded_date",
                "creation", "modified"],
        order_by="creation asc",
    )

    highlights = []
    for doc in docs:
        waiting_time = now_datetime() - doc.creation
        is_high_priority = waiting_time.total_seconds() > 86400  # >24h
        customer_name = frappe.db.get_value("Customer", doc.customer, "customer_name") or doc.customer

        highlights.append({
            "name": doc.name,
            "customer": doc.customer,
            "customer_name": customer_name,
            "document_type": doc.document_type,
            "uploaded_date": str(doc.uploaded_date or doc.creation),
            "waiting_hours": round(waiting_time.total_seconds() / 3600, 1),
            "high_priority": is_high_priority,
        })

    return {
        "total_pending": len(highlights),
        "high_priority_count": sum(1 for h in highlights if h["high_priority"]),
        "items": highlights,
    }


@frappe.whitelist()
def get_prolonged_maintenance(hub=None):
    """Return bikes in maintenance for more than 7 days."""
    user = frappe.session.user
    roles = frappe.get_roles(user)
    is_system_manager = "System Manager" in roles

    if not is_system_manager:
        hub = _get_user_hub(user)
        if not hub:
            return {"total_prolonged": 0, "items": []}

    seven_days_ago = add_to_date(now_datetime(), days=-7)

    filters = {"status": "Maintenance"}
    if hub:
        filters["hub"] = hub

    serials = frappe.get_all(
        "Bike Serial",
        filters=filters,
        fields=["name", "bike_model", "hub", "modified"],
    )

    prolonged = []
    for serial in serials:
        days_in_maintenance = (now_datetime() - serial.modified).days
        if days_in_maintenance >= 7:
            prolonged.append({
                "serial_no": serial.name,
                "model": serial.bike_model,
                "hub": serial.hub,
                "days_in_maintenance": days_in_maintenance,
            })

    return {
        "total_prolonged": len(prolonged),
        "items": prolonged,
    }


def _get_user_hub(user):
    """Determine the hub assigned to a non-System-Manager user.

    Checks User's hub field, or finds a Hub where the user is the hub_manager.
    """
    # Check if User has a hub field
    user_hub = frappe.db.get_value("User", user, "hub")
    if user_hub:
        return user_hub

    # Fallback: find hub where user is the manager
    hub = frappe.db.get_value("Hub", {"hub_manager": user}, "name")
    if hub:
        return hub

    return None
