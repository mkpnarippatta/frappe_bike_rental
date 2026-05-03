from __future__ import unicode_literals

import frappe
from frappe import _

from bike_rental.api.availability import check_availability


def get_context(context):
    """Build bike listing or detail page context."""
    model_name = frappe.form_dict.get("name")

    if not model_name:
        # Show all bikes (listing view)
        context.title = _("Available Bikes")
        models = frappe.get_all(
            "Bike Model",
            fields=["name", "brand", "category", "base_rate_daily", "image"],
            order_by="name asc",
        )
        enriched = []
        for m in models:
            serials = frappe.get_all(
                "Bike Serial",
                fields=["hub"],
                filters={"bike_model": m.name, "status": ["!=", "Scrapped"]},
            )
            hub_counts = {}
            for s in serials:
                hub_counts[s.hub] = hub_counts.get(s.hub, 0) + 1
            m.total_serials = len(serials)
            m.hubs = list(hub_counts.keys())
            enriched.append(m)
        context.models = enriched
        context.models_json = frappe.as_json(enriched)
        context.bike = None

        categories = frappe.get_all(
            "Bike Model", fields=["category"], distinct=True, order_by="category asc"
        )
        context.categories = [c["category"] for c in categories if c["category"]]
        return context

    bike = frappe.get_all(
        "Bike Model",
        filters={"name": model_name},
        fields=["name", "brand", "category", "base_rate_daily", "safety_margin",
                "description", "image"],
        limit=1,
    )

    if not bike:
        context.title = _("Bike Not Found")
        context.bike = None
        return context

    bike = bike[0]

    # Get total serials count
    total_serials = frappe.db.count(
        "Bike Serial",
        filters={"bike_model": bike.name, "status": ["!=", "Scrapped"]},
    )

    # Get hubs where this model is available
    hubs = frappe.db.sql("""
        SELECT DISTINCT bs.hub, h.name as hub_name
        FROM `tabBike Serial` bs
        LEFT JOIN `tabHub` h ON h.name = bs.hub
        WHERE bs.bike_model = %s AND bs.status != 'Scrapped'
        ORDER BY bs.hub
    """, bike.name, as_dict=True)

    bike.total_serials = total_serials
    bike.hubs = hubs

    from frappe.utils import today
    context.title = _("{0} - Bike Rental").format(bike.name)
    context.bike = bike
    context.today = today()
    context.bike_json = frappe.as_json({
        "name": bike.name,
        "base_rate_daily": bike.base_rate_daily,
    })

    return context


@frappe.whitelist()
def get_bike_detail(model_name):
    """Return bike detail data for AJAX."""
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
def calculate_price(model_name, start_date, end_date):
    """Calculate price for a rental period."""
    from frappe.utils import getdate

    bike = frappe.get_all(
        "Bike Model",
        filters={"name": model_name},
        fields=["name", "base_rate_daily"],
        limit=1,
    )

    if not bike:
        frappe.throw(_("Bike model not found"))

    start = getdate(start_date)
    end = getdate(end_date)
    days = max(1, (end - start).days)

    base_rate = float(bike[0].base_rate_daily or 0)
    total = base_rate * days

    # Security deposit (50% of total, min 500)
    deposit = max(500, round(total * 0.5, 2))

    return {
        "daily_rate": base_rate,
        "days": days,
        "base_amount": round(total, 2),
        "deposit": deposit,
        "total_due": round(total + deposit, 2),
    }
