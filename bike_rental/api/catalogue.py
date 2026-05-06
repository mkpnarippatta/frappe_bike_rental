from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_catalogue_data(hub):
    """Return bike models with availability for a given hub."""
    if not hub:
        return {"models": [], "hub": None}

    models = frappe.get_all(
        "Bike Model",
        fields=["name", "brand", "category", "base_rate_daily", "safety_margin",
                "description", "image"],
        order_by="name asc",
    )

    result = []
    for model in models:
        total_serials = frappe.db.count(
            "Bike Serial",
            filters={"bike_model": model.name, "hub": hub,
                     "status": ["!=", "Scrapped"]},
        )

        rented = frappe.db.count(
            "Rental Booking",
            filters={
                "bike_model": model.name,
                "pickup_hub": hub,
                "status": ["in", ["Active", "Confirmed"]],
                "docstatus": 1,
            },
        )

        available = max(0, total_serials - rented - (model.safety_margin or 0))

        result.append({
            "name": model.name,
            "brand": model.brand,
            "category": model.category,
            "base_rate_daily": model.base_rate_daily,
            "description": model.description,
            "image": model.image,
            "total_serials": total_serials,
            "rented": rented,
            "available": available,
        })

    return {"models": result, "hub": hub}


@frappe.whitelist(allow_guest=True)
def get_bike_detail(model_name):
    """Return bike detail data."""
    bike = frappe.get_all(
        "Bike Model",
        filters={"name": model_name},
        fields=["name", "brand", "category", "base_rate_daily", "safety_margin",
                "description", "image"],
        limit=1,
    )

    if not bike:
        frappe.throw(_("Bike model not found"))

    bike = bike[0]

    total_serials = frappe.db.count(
        "Bike Serial",
        filters={"bike_model": bike.name, "status": ["!=", "Scrapped"]},
    )

    hubs = frappe.db.sql("""
        SELECT DISTINCT bs.hub
        FROM `tabBike Serial` bs
        WHERE bs.bike_model = %s AND bs.status != 'Scrapped'
        ORDER BY bs.hub
    """, bike.name, as_dict=True)

    return {
        "name": bike.name,
        "brand": bike.brand,
        "category": bike.category,
        "base_rate_daily": bike.base_rate_daily,
        "description": bike.description,
        "image": bike.image,
        "total_serials": total_serials,
        "hubs": [h["hub"] for h in hubs],
    }


@frappe.whitelist(allow_guest=True)
def get_hubs_list():
    """Return list of hubs."""
    hubs = frappe.get_all("Hub", fields=["name", "payment_methods"], order_by="name asc")
    for h in hubs:
        if h.payment_methods:
            h.payment_methods = [m.strip() for m in h.payment_methods.strip().split("\n") if m.strip()]
        else:
            h.payment_methods = ["Cash", "Card", "UPI"]
    return hubs
