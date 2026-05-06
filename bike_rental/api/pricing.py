from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import getdate


@frappe.whitelist(allow_guest=True)
def calculate_price(model_name, start_date, end_date):
    """Calculate price for a rental period."""
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
