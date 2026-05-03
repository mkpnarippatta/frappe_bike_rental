from __future__ import unicode_literals

import frappe


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


@frappe.whitelist()
def get_hubs_list():
    """Return list of hubs."""
    return frappe.get_all("Hub", fields=["name"], order_by="name asc")
