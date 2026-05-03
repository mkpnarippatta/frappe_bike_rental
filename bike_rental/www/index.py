from __future__ import unicode_literals

import frappe
from frappe import _


def get_context(context):
    """Build homepage context with all bike models and availability across hubs."""
    context.title = _("Bike Rental - Rent the Perfect Bike")

    models = frappe.get_all(
        "Bike Model",
        fields=["name", "brand", "category", "base_rate_daily", "image"],
        order_by="name asc",
    )

    # Enrich with serial count and hubs across all hubs
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

    # Categories for filter chips
    categories = frappe.get_all(
        "Bike Model", fields=["category"], distinct=True, order_by="category asc"
    )
    context.categories = [c["category"] for c in categories if c["category"]]

    return context
